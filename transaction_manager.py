import json
import logging
import os
import re
from dataclasses import asdict
from datetime import time
from typing import Any

import polars as pl
from dotenv import load_dotenv

from transaction_loader import Transaction

load_dotenv()

DATA_DIR = "data"


class TransactionManager:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.manual_assignments_file = os.path.join(
            self.data_dir, "manual_assignments.json"
        )
        self.patterns_file = os.path.join(self.data_dir, "patterns.json")
        self.cache_file = os.path.join(self.data_dir, "llm_cache.json")

        self.manual_assignments: dict[str, dict[str, str]] = {}
        self.patterns: list[dict[str, Any]] = []
        self.categories: list[str] = []
        self.llm_cache: dict[str, dict[str, Any]] = {}
        self.transfer_map: dict[str, dict[str, Any]] = {}

        self.load_data()

    def load_data(self):
        if os.path.exists(self.manual_assignments_file):
            with open(self.manual_assignments_file) as f:
                self.manual_assignments = json.load(f)

        if os.path.exists(self.patterns_file):
            with open(self.patterns_file) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Master format: {"Category": [ {pattern...}, ... ]}
                    self.categories = sorted(list(data.keys()))
                    self.patterns = []
                    for category, patterns in data.items():
                        for p in patterns:
                            p_copy = p.copy()
                            p_copy["category"] = category
                            self.patterns.append(p_copy)
                else:
                    # Legacy flat list format (will be migrated on next save)
                    self.patterns = data
                    self.categories = sorted(
                        list(set(p.get("category", "Uncategorized") for p in data))
                    )

        if os.path.exists(self.cache_file):
            with open(self.cache_file) as f:
                self.llm_cache = json.load(f)

    def save_data(self):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.manual_assignments_file, "w") as f:
            json.dump(self.manual_assignments, f, indent=2)

        with open(self.patterns_file, "w") as f:
            json.dump(self._regroup_patterns(), f, indent=2)

        with open(self.cache_file, "w") as f:
            json.dump(self.llm_cache, f, indent=2)

    def _regroup_patterns(self) -> dict[str, list[dict[str, Any]]]:
        """Convert flat internal pattern list back to grouped-by-category format for JSON.

        Seed with all known categories so that empty categories survive the round-trip
        (they define the master category list even if no patterns exist yet).
        """
        grouped: dict[str, list[dict[str, Any]]] = {cat: [] for cat in self.categories}

        for p in self.patterns:
            p_copy = p.copy()
            cat = p_copy.pop("category", "Uncategorized")
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(p_copy)

        return dict(sorted(grouped.items()))

    def detect_transfers(self, transactions: list[Transaction]) -> None:
        """Pair up inter-account transfers so they don't pollute spending totals.

        Heuristic: two transactions are a transfer if they have opposite amounts,
        are on different accounts, settle within 3 days, and both mention the
        user's name (TRANSFER_NAME env var) in the description.
        """
        self.transfer_map = {}

        # Index by amount so we can find opposite-amount candidates in O(1)
        amount_map: dict[float, list[Transaction]] = {}
        for tx in transactions:
            amt = round(tx.amount, 2)
            if amt not in amount_map:
                amount_map[amt] = []
            amount_map[amt].append(tx)

        name_to_match = os.getenv("TRANSFER_NAME", "USER")
        name_pattern = re.compile(re.escape(name_to_match), re.IGNORECASE)

        for tx in transactions:
            if tx.id in self.transfer_map:
                continue

            # Look for opposite amount
            target_amt = round(-tx.amount, 2)
            candidates = amount_map.get(target_amt, [])

            for cand in candidates:
                if cand.id == tx.id:
                    continue
                if cand.id in self.transfer_map:
                    continue
                if cand.account_id == tx.account_id:
                    continue  # Same account transfer? Unlikely for this use case

                # Date check
                if abs((tx.booking_date - cand.booking_date).days) > 3:
                    continue

                # Description check
                # Both must likely involve the user's name to be safe

                tx_desc = (tx.counterparty or "") + " " + (tx.remittance or "")
                cand_desc = (cand.counterparty or "") + " " + (cand.remittance or "")

                match_tx = name_pattern.search(tx_desc)
                match_cand = name_pattern.search(cand_desc)

                if match_tx and match_cand:
                    # Found a pair!
                    self.transfer_map[tx.id] = {
                        "clean_name": "Internal Transfer",
                        "category": "Transfers > Matched",
                        "source": "TRANSFER",
                        "confidence": 1.0,
                        "linked_tx": cand.id,
                    }
                    self.transfer_map[cand.id] = {
                        "clean_name": "Internal Transfer",
                        "category": "Transfers > Matched",
                        "source": "TRANSFER",
                        "confidence": 1.0,
                        "linked_tx": tx.id,
                    }
                    # We continue to find potential other matches?
                    # Usually pairs are unique. But let's just break for this tx.
                    break

    def _find_matches(self, tx: Transaction) -> dict[str, Any]:
        if not tx.id:
            return {}

        matches: dict[str, Any] = {}

        if tx.id in self.manual_assignments:
            assign = self.manual_assignments[tx.id]
            matches["MANUAL"] = {
                "clean_name": assign.get("clean_name"),
                "category": assign.get("category"),
                "source": "MANUAL",
                "confidence": 1.0,
            }

        if tx.id in self.transfer_map:
            matches["TRANSFER"] = self.transfer_map[tx.id]

        if tx.amount == 0:
            matches["ZERO_AMOUNT"] = {
                "clean_name": "Zero Amount",
                "category": "Excluded",
                "source": "ZERO_AMOUNT",
                "confidence": 1.0,
            }

        pattern_matches = []
        for pattern in self.patterns:
            if not self._tx_matches_pattern(tx, pattern):
                continue

            pattern_matches.append(
                {
                    "clean_name": pattern.get("clean_name"),
                    "category": pattern.get("category"),
                    "source": "PATTERN",
                    "confidence": 0.9,
                    "pattern_matched": pattern.get("pattern", ""),
                }
            )

        if pattern_matches:
            matches["PATTERN"] = pattern_matches[0]
            matches["_ALL_PATTERNS"] = pattern_matches

        if tx.id in self.llm_cache:
            cached = self.llm_cache[tx.id]
            matches["AI_AGENT"] = {
                "clean_name": cached.get("clean_name"),
                "category": cached.get("category"),
                "category_reason": cached.get("category_reason"),
                "source": cached.get("source", "AI_AGENT"),
                "confidence": cached.get("confidence", 0.7),
                "suggested_category": cached.get("suggested_category"),
                "suggestion_reason": cached.get("suggestion_reason"),
            }

        return matches

    def get_priority_source(self, tx: Transaction) -> str | None:
        """Return the highest-priority non-pattern source, or None if patterns would apply."""
        matches = self._find_matches(tx)
        for source in ("MANUAL", "TRANSFER", "ZERO_AMOUNT"):
            if source in matches:
                return source
        return None

    def resolve_transaction(self, tx: Transaction) -> dict[str, Any]:
        """Pick the single best categorization from all match sources.

        Enforces a strict priority (MANUAL > TRANSFER > ZERO > PATTERN > AI)
        so that cheap deterministic rules always win over expensive probabilistic ones.
        Logs when a higher-priority source shadows a lower one, to surface
        redundant cache entries for cleanup.
        """
        if not tx.id:
            return {}

        matches = self._find_matches(tx)

        # Check for multiple patterns warning
        if "_ALL_PATTERNS" in matches:
            pattern_matches = matches["_ALL_PATTERNS"]
            if len(pattern_matches) > 1:
                matched_pats = [m["pattern_matched"] for m in pattern_matches]
                logging.warning(
                    f"Transaction {tx.id} matched multiple patterns: {matched_pats}. "
                    "Using the first one."
                )

        final_result: dict[str, Any] = {
            "clean_name": None,
            "category": None,
            "source": None,
            "confidence": 0.0,
        }

        if "MANUAL" in matches:
            final_result = matches["MANUAL"]
            if "PATTERN" in matches:
                logging.info(
                    f"Transaction {tx.id}: Manual assignment overrides Pattern match "
                    f"'{matches['PATTERN'].get('pattern_matched')}'"
                )
            if "AI_AGENT" in matches:
                logging.info(
                    f"Transaction {tx.id}: Manual assignment overrides AI Cache"
                )

        elif "TRANSFER" in matches:
            final_result = matches["TRANSFER"]
            if "AI_AGENT" in matches:
                logging.info(f"Transaction {tx.id}: Transfer match overrides AI Cache")

        elif "ZERO_AMOUNT" in matches:
            final_result = matches["ZERO_AMOUNT"]
            if "AI_AGENT" in matches:
                logging.info(f"Transaction {tx.id}: Zero Amount overrides AI Cache")

        elif "PATTERN" in matches:
            final_result = matches["PATTERN"]
            if "AI_AGENT" in matches:
                logging.info(f"Transaction {tx.id}: Pattern match overrides AI Cache")

        elif "AI_AGENT" in matches:
            final_result = matches["AI_AGENT"]

        # pattern_matched is only used for overlap warnings, not returned to callers
        if "pattern_matched" in final_result:
            del final_result["pattern_matched"]

        # Catch typos or stale categories from LLM/manual assignments
        category = final_result.get("category")
        source = final_result.get("source")
        if category and category not in self.categories and category != "Uncategorized":
            logging.warning(
                f"Transaction {tx.id} resolved to unknown category "
                f"'{category}' from {source}"
            )

        return final_result

    def explain_transaction(self, tx: Transaction) -> dict[str, Any]:
        """
        Returns a detailed diagnosis of how the transaction is resolved.
        """
        matches = self._find_matches(tx)
        final_result = self.resolve_transaction(tx)

        return {
            "tx_id": tx.id,
            "counterparty": tx.counterparty,
            "remittance": tx.remittance,
            "matches": matches,
            "final_result": final_result,
        }

    @staticmethod
    def _tx_matches_pattern(tx: Transaction, pattern: dict[str, Any]) -> bool:
        """Checks if a transaction matches a pattern's regex and all constraints."""
        p_str = pattern.get("pattern", "")
        p_field = pattern.get("field", "counterparty")

        target_text = ""
        if p_field == "counterparty":
            target_text = tx.counterparty or ""
        elif p_field == "remittance":
            target_text = tx.remittance or ""
        elif p_field == "any":
            target_text = f"{tx.counterparty or ''} {tx.remittance or ''}"

        if not re.search(p_str, target_text, re.IGNORECASE):
            return False

        amt = abs(tx.amount)
        min_amt = pattern.get("min_amount")
        if min_amt is not None and amt < float(min_amt):
            return False

        max_amt = pattern.get("max_amount")
        if max_amt is not None and amt > float(max_amt):
            return False

        min_day = pattern.get("min_day")
        if min_day is not None and tx.booking_date.day < int(min_day):
            return False

        max_day = pattern.get("max_day")
        if max_day is not None and tx.booking_date.day > int(max_day):
            return False

        min_time = pattern.get("min_time")
        if min_time is not None:
            try:
                if tx.time_of_day < time.fromisoformat(min_time):
                    return False
            except ValueError:
                logging.warning(f"Invalid min_time format in pattern: {min_time}")

        max_time = pattern.get("max_time")
        if max_time is not None:
            try:
                if tx.time_of_day > time.fromisoformat(max_time):
                    return False
            except ValueError:
                logging.warning(f"Invalid max_time format in pattern: {max_time}")

        return True

    def test_pattern(
        self,
        transactions: list[Transaction],
        pattern: str,
        field: str = "counterparty",
        min_amount: float | None = None,
        max_amount: float | None = None,
        min_day: int | None = None,
        max_day: int | None = None,
        min_time: str | None = None,
        max_time: str | None = None,
    ) -> list[Transaction]:
        """
        Tests a regex pattern against a list of transactions with optional filters.
        Returns a list of transactions matching the pattern and filters.
        """
        p = {
            "pattern": pattern,
            "field": field,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "min_day": min_day,
            "max_day": max_day,
            "min_time": min_time,
            "max_time": max_time,
        }
        return [tx for tx in transactions if self._tx_matches_pattern(tx, p)]

    def purge_override_cache(self, transactions: list[Transaction]) -> int:
        """Remove stale LLM cache entries that are now shadowed by higher-priority rules.

        After adding new patterns or manual assignments, cached AI labels for those
        transactions are dead weight. This keeps the cache lean and avoids confusion
        when inspecting it.
        """
        self.detect_transfers(transactions)

        count = 0
        for tx in transactions:
            if tx.id in self.llm_cache:
                # Check how it would resolve
                resolution = self.resolve_transaction(tx)
                source = resolution.get("source")

                # If it resolves to something definitive that overrides cache
                if source in ["MANUAL", "PATTERN", "TRANSFER", "ZERO_AMOUNT"]:
                    del self.llm_cache[tx.id]
                    count += 1

        if count > 0:
            self.save_data()
            logging.info(f"Purged {count} overridden entries from LLM cache.")

        return count

    def enrich_transactions(
        self,
        transactions: list[Transaction],
    ) -> pl.DataFrame:
        """
        Takes a list of Transactions and returns a flat Polars DataFrame with
        enrichment columns.
        """
        # Run transfer detection first
        self.detect_transfers(transactions)

        all_txs = []
        for tx in transactions:
            # Flatten via asdict and resolve
            flat_tx = asdict(tx)

            enrichment = self.resolve_transaction(tx)
            flat_tx.update(enrichment)

            all_txs.append(flat_tx)

        if not all_txs:
            raise ValueError("No transactions to enrich.")

        return pl.DataFrame(all_txs, infer_schema_length=None)
