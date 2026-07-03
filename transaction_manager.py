import json
import logging
import os
import re
from dataclasses import asdict
from datetime import time
from typing import Any, Literal

import polars as pl
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from transaction_loader import Transaction

load_dotenv()

DATA_DIR = "data"

# The resolution hierarchy, highest priority first. Cheap deterministic rules always
# win over expensive probabilistic ones. This tuple is the single source of truth:
# resolve_transaction, get_priority_source, and purge_override_cache all derive
# their ordering from it.
SOURCE_PRIORITY = ("MANUAL", "TRANSFER", "ZERO_AMOUNT", "PATTERN", "AI_AGENT")


class PatternRule(BaseModel):
    """Schema gate for patterns.json entries.

    A malformed entry is dangerous: a missing/empty "pattern" key would regex-match
    every transaction, and cleanup_cache.py would then purge the whole AI cache.
    Validation happens at load time only; the original dicts are kept untouched so
    the JSON file round-trips byte-identically.
    """

    model_config = ConfigDict(extra="forbid")

    pattern: str
    clean_name: str | None = None
    field: Literal["counterparty", "remittance", "any"] = "counterparty"
    min_amount: float | None = None
    max_amount: float | None = None
    min_day: int | None = None
    max_day: int | None = None
    min_time: str | None = None
    max_time: str | None = None

    @field_validator("pattern")
    @classmethod
    def _pattern_is_nonempty_and_compiles(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("pattern must be a non-empty regex")
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"pattern is not a valid regex: {e}") from e
        return v

    @field_validator("min_time", "max_time")
    @classmethod
    def _time_is_parseable(cls, v: str | None) -> str | None:
        if v is not None:
            time.fromisoformat(v)
        return v


def _dump_json_atomic(path: str, obj: Any) -> None:
    """Write JSON via a temp file + rename so a crash can't truncate the target.

    These files hold months of hand-curated labelling with no other backup, so a
    partial write must never replace a good copy.
    """
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


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
        self._transfers_detected = False

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
                            self._validate_pattern(p, category)
                            p_copy = p.copy()
                            p_copy["category"] = category
                            self.patterns.append(p_copy)
                else:
                    # Legacy flat list format (will be migrated on next save)
                    for p in data:
                        category = p.get("category", "Uncategorized")
                        self._validate_pattern(
                            {k: v for k, v in p.items() if k != "category"}, category
                        )
                    self.patterns = data
                    self.categories = sorted(
                        list(set(p.get("category", "Uncategorized") for p in data))
                    )

        if os.path.exists(self.cache_file):
            with open(self.cache_file) as f:
                self.llm_cache = json.load(f)
            for tx_id, entry in self.llm_cache.items():
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"Invalid llm_cache entry for '{tx_id}': expected an object, "
                        f"got {type(entry).__name__}"
                    )

    @staticmethod
    def _validate_pattern(p: dict[str, Any], category: str) -> None:
        try:
            PatternRule.model_validate(p)
        except ValidationError as e:
            raise ValueError(
                f"Invalid pattern in category '{category}' "
                f"(clean_name={p.get('clean_name')!r}): {e}"
            ) from e

    def save_data(self):
        os.makedirs(self.data_dir, exist_ok=True)
        _dump_json_atomic(self.manual_assignments_file, self.manual_assignments)
        _dump_json_atomic(self.patterns_file, self._regroup_patterns())
        _dump_json_atomic(self.cache_file, self.llm_cache)

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
        self._transfers_detected = True

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

        # Transfer matching depends on state that only detect_transfers() builds;
        # resolving without it silently labels transfers as ordinary spending.
        if not self._transfers_detected:
            logging.warning(
                "Resolving transactions without detect_transfers() having run — "
                "inter-account transfers will not be recognized."
            )
            self._transfers_detected = True  # warn once per manager, not per tx

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
        for source in SOURCE_PRIORITY:
            if source == "PATTERN":
                return None
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

        for i, source in enumerate(SOURCE_PRIORITY):
            if source not in matches:
                continue
            final_result = matches[source]
            # Surface shadowed lower-priority matches so redundant cache entries
            # (and overlapping rules) can be cleaned up.
            for shadowed in SOURCE_PRIORITY[i + 1 :]:
                if shadowed in matches:
                    logging.info(
                        f"Transaction {tx.id}: {source} overrides {shadowed}"
                    )
            break

        # pattern_matched is only used for overlap warnings, not returned to callers
        if "pattern_matched" in final_result:
            del final_result["pattern_matched"]

        # Catch typos or stale categories from LLM/manual assignments
        category = final_result.get("category")
        if category and category not in self.categories and category != "Uncategorized":
            logging.warning(
                f"Transaction {tx.id} resolved to unknown category "
                f"'{category}' from {final_result.get('source')}"
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
                if source in SOURCE_PRIORITY and source != "AI_AGENT":
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
