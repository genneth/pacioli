import json
import logging
import os
import re
from dataclasses import asdict
from typing import Any

import polars as pl
from google import genai
from pydantic import BaseModel

from transaction_loader import Transaction

# Paths
DATA_DIR = "data"
MANUAL_ASSIGNMENTS_FILE = os.path.join(DATA_DIR, "manual_assignments.json")
PATTERNS_FILE = os.path.join(DATA_DIR, "patterns.json")
CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.json")
CACHE_FILE = os.path.join(DATA_DIR, "llm_cache.json")


class TransactionResult(BaseModel):
    id: str
    clean_name: str
    category: str
    category_reason: str
    suggested_category: str | None = None
    suggestion_reason: str | None = None


class CategorizationResponse(BaseModel):
    transactions: list[TransactionResult]


class TransactionManager:
    def __init__(
        self, genai_client: genai.Client | None = None, data_dir: str = DATA_DIR
    ):
        self.client = genai_client
        self.data_dir = data_dir
        self.manual_assignments_file = os.path.join(
            self.data_dir, "manual_assignments.json"
        )
        self.patterns_file = os.path.join(self.data_dir, "patterns.json")
        self.categories_file = os.path.join(self.data_dir, "categories.json")
        self.cache_file = os.path.join(self.data_dir, "llm_cache.json")

        self.manual_assignments: dict[str, dict[str, str]] = {}
        self.patterns: list[dict[str, str]] = []
        self.categories: list[str] = []
        self.llm_cache: dict[str, dict[str, Any]] = {}
        self.transfer_map: dict[str, dict[str, Any]] = {}

        self.load_data()

    def load_data(self):
        """Loads all configuration and data files."""
        if os.path.exists(self.manual_assignments_file):
            with open(self.manual_assignments_file) as f:
                self.manual_assignments = json.load(f)

        if os.path.exists(self.patterns_file):
            with open(self.patterns_file) as f:
                self.patterns = json.load(f)

        if os.path.exists(self.categories_file):
            with open(self.categories_file) as f:
                self.categories = json.load(f)

        if os.path.exists(self.cache_file):
            with open(self.cache_file) as f:
                self.llm_cache = json.load(f)

    def save_data(self):
        """Saves all configuration and data files."""
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.manual_assignments_file, "w") as f:
            json.dump(self.manual_assignments, f, indent=2)

        with open(self.patterns_file, "w") as f:
            json.dump(self.patterns, f, indent=2)

        with open(self.categories_file, "w") as f:
            json.dump(self.categories, f, indent=2)

        with open(self.cache_file, "w") as f:
            json.dump(self.llm_cache, f, indent=2)

    def detect_transfers(self, transactions: list[Transaction]) -> None:
        """
        Identifies transfers between accounts.
        Populates self.transfer_map with transaction IDs identified as transfers.
        """
        self.transfer_map = {}  # Reset

        # Group by amount for O(N) lookup
        amount_map: dict[float, list[Transaction]] = {}
        for tx in transactions:
            amt = round(tx.amount, 2)
            if amt not in amount_map:
                amount_map[amt] = []
            amount_map[amt].append(tx)

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
                name_pattern = re.compile(r"SMITH", re.IGNORECASE)

                tx_desc = (tx.counterparty or "") + " " + (tx.remittance or "")
                cand_desc = (cand.counterparty or "") + " " + (cand.remittance or "")

                match_tx = name_pattern.search(tx_desc)
                match_cand = name_pattern.search(cand_desc)

                if match_tx and match_cand:
                    # Found a pair!
                    self.transfer_map[tx.id] = {
                        "clean_name": "Internal Transfer",
                        "category": "Transfers > Matched",
                        "source": "TRANSFER_MATCH",
                        "confidence": 1.0,
                        "linked_tx": cand.id,
                    }
                    self.transfer_map[cand.id] = {
                        "clean_name": "Internal Transfer",
                        "category": "Transfers > Matched",
                        "source": "TRANSFER_MATCH",
                        "confidence": 1.0,
                        "linked_tx": tx.id,
                    }
                    # We continue to find potential other matches?
                    # Usually pairs are unique. But let's just break for this tx.
                    break

    def _find_matches(self, tx: Transaction) -> dict[str, Any]:
        """
        Internal method to find all possible matches for a transaction.
        """
        if not tx.id:
            return {}

        matches: dict[str, Any] = {}  # source -> result

        # 1. Manual Assignments: User overrides always take precedence
        if tx.id in self.manual_assignments:
            assign = self.manual_assignments[tx.id]
            matches["MANUAL"] = {
                "clean_name": assign.get("clean_name"),
                "category": assign.get("category"),
                "source": "MANUAL",
                "confidence": 1.0,
            }

        # 2. Transfers: Detected internal movements
        if tx.id in self.transfer_map:
            matches["TRANSFER"] = self.transfer_map[tx.id]

        # 3. Zero Amount: Accounting artifacts or failed txs usually irrelevant
        if tx.amount == 0:
            matches["ZERO_AMOUNT"] = {
                "clean_name": "Zero Amount",
                "category": "Excluded",
                "source": "ZERO_AMOUNT",
                "confidence": 1.0,
            }

        # 3. Patterns: Regex rules for recurring/known merchants
        pattern_matches = []
        for pattern in self.patterns:
            p_str = pattern.get("pattern", "")
            p_field = pattern.get("field", "counterparty")

            target_text = ""
            if p_field == "counterparty":
                target_text = tx.counterparty or ""
            elif p_field == "remittance":
                target_text = tx.remittance or ""
            elif p_field == "any":
                target_text = f"{tx.counterparty or ''} {tx.remittance or ''}"

            if re.search(p_str, target_text, re.IGNORECASE):
                pattern_matches.append(
                    {
                        "clean_name": pattern.get("clean_name"),
                        "category": pattern.get("category"),
                        "source": "PATTERN",
                        "confidence": 0.9,
                        "pattern_matched": p_str,
                    }
                )

        if pattern_matches:
            matches["PATTERN"] = pattern_matches[0]
            matches["_ALL_PATTERNS"] = pattern_matches

        # 4. LLM Cache: Fallback to previously AI-categorized results
        if tx.id in self.llm_cache:
            cached = self.llm_cache[tx.id]
            matches["AI_CACHED"] = {
                "clean_name": cached.get("clean_name"),
                "category": cached.get("category"),
                "category_reason": cached.get("category_reason"),
                "source": "AI_CACHED",
                "confidence": cached.get("confidence", 0.7),
                "suggested_category": cached.get("suggested_category"),
                "suggestion_reason": cached.get("suggestion_reason"),
            }

        return matches

    def resolve_transaction(self, tx: Transaction) -> dict[str, Any]:
        """
        Resolves a single transaction against Manual, Patterns, and Cache.
        Returns the enrichment data (clean_name, category, source, confidence).
        Checks for overlaps and logs warnings.
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

        # --- Hierarchy & Overlap Warnings ---
        # We enforce a strict priority order to ensure deterministic and user-controlled
        # categorization.

        final_result: dict[str, Any] = {
            "clean_name": None,
            "category": None,
            "source": None,
            "confidence": 0.0,
        }

        # Priority 1: Manual - The user is always right.
        if "MANUAL" in matches:
            final_result = matches["MANUAL"]
            if "PATTERN" in matches:
                logging.info(
                    f"Transaction {tx.id}: Manual assignment overrides Pattern match "
                    f"'{matches['PATTERN'].get('pattern_matched')}'"
                )
            if "AI_CACHED" in matches:
                logging.info(
                    f"Transaction {tx.id}: Manual assignment overrides AI Cache"
                )

        # Priority 2: Transfers - Internal movements are distinct
        elif "TRANSFER" in matches:
            final_result = matches["TRANSFER"]
            if "AI_CACHED" in matches:
                logging.info(f"Transaction {tx.id}: Transfer match overrides AI Cache")

        # Priority 3: Zero Amount - Technical/failed txs are noise.
        elif "ZERO_AMOUNT" in matches:
            final_result = matches["ZERO_AMOUNT"]
            if "AI_CACHED" in matches:
                logging.info(f"Transaction {tx.id}: Zero Amount overrides AI Cache")

        # Priority 3: Pattern - Deterministic rules are cheaper and faster than AI.
        elif "PATTERN" in matches:
            final_result = matches["PATTERN"]
            if "AI_CACHED" in matches:
                logging.info(f"Transaction {tx.id}: Pattern match overrides AI Cache")

        # Priority 4: Cache - Expensive/probabilistic AI result.
        elif "AI_CACHED" in matches:
            final_result = matches["AI_CACHED"]

        # Clean up temporary field
        if "pattern_matched" in final_result:
            del final_result["pattern_matched"]

        # Warning for unknown categories
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

    def test_pattern(
        self, transactions: list[Transaction], pattern: str, field: str = "counterparty"
    ) -> list[Transaction]:
        """
        Tests a regex pattern against a list of transactions.
        Returns a list of transactions matching the pattern.
        """
        matches = []
        for tx in transactions:
            target_text = ""
            if field == "counterparty":
                target_text = tx.counterparty or ""
            elif field == "remittance":
                target_text = tx.remittance or ""
            elif field == "any":
                target_text = f"{tx.counterparty or ''} {tx.remittance or ''}"

            if re.search(pattern, target_text, re.IGNORECASE):
                matches.append(tx)
        return matches

    def purge_override_cache(self, transactions: list[Transaction]) -> int:
        """
        Removes entries from llm_cache if they are currently resolved via
        MANUAL, PATTERN, TRANSFER_MATCH, or ZERO_AMOUNT.
        """
        # Ensure transfer map is up to date for this set of transactions
        self.detect_transfers(transactions)

        count = 0
        for tx in transactions:
            if tx.id in self.llm_cache:
                # Check how it would resolve
                resolution = self.resolve_transaction(tx)
                source = resolution.get("source")

                # If it resolves to something definitive that overrides cache
                if source in ["MANUAL", "PATTERN", "TRANSFER_MATCH", "ZERO_AMOUNT"]:
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

    def batch_process_llm(
        self,
        transactions: list[Transaction],
        force_update=False,
    ):
        """
        Identifies unlabelled transactions and queries Gemini.
        Updates the cache and saves.
        """
        if not self.client:
            logging.warning("No Gemini client provided.")
            return

        if not transactions:
            return

        # Use enrich_transactions to get current state
        # This returns a Polars DataFrame
        try:
            df = self.enrich_transactions(transactions)
        except ValueError:
            # Handle case where enrich_transactions might fail on empty list
            return

        # Filter for rows that need processing
        # 1. source is null (Uncategorized/Unmatched)
        # 2. force_update is True AND source is 'AI_CACHED'

        filter_expr = pl.col("source").is_null()
        if force_update:
            filter_expr = filter_expr | (pl.col("source") == "AI_CACHED")

        to_process_df = df.filter(filter_expr)
        to_process = to_process_df.to_dicts()

        if not to_process:
            logging.info("No new transactions to process with LLM.")
            return

        logging.info(f"Sending {len(to_process)} transactions to LLM...")

        # Chunking to avoid context limits
        # Gemini 3.0 Flash has a 64k output token limit.
        # ~150 txs * ~200 tokens/tx (conservative) = 30k tokens output.
        # This leaves a safe buffer.
        chunk_size = 150
        for i in range(0, len(to_process), chunk_size):
            chunk = to_process[i : i + chunk_size]
            self._query_llm_chunk(chunk)
            self.save_data()  # Save incrementally

    def _query_llm_chunk(self, tx_chunk: list[dict]):
        """
        Helper to query Gemini for a chunk of transactions.
        """
        if not self.client:
            return

        # Prepare prompt
        tx_list_str = ""
        for tx in tx_chunk:
            # tx is a dict from Polars
            tx_id = tx.get("id")
            booking_date = tx.get("booking_date")
            time_of_day = tx.get("time_of_day", "")
            amount = tx.get("amount")
            currency = tx.get("currency", "")
            counterparty = tx.get("counterparty") or "Unknown"
            account_id = tx.get("account_id", "")

            parts = [
                f"ID: {tx_id}",
                f"Date: {booking_date}",
                f"Time: {time_of_day}",
                f"Amt: {amount} {currency}",
                f"Acct: {account_id}",
                f"Party: {counterparty}",
            ]

            if remittance := tx.get("remittance"):
                parts.append(f"Remit: {remittance}")

            if tx_type := tx.get("tx_type"):
                parts.append(f"Type: {tx_type}")

            if f_curr := tx.get("foreign_currency"):
                parts.append(f"F.Curr: {f_curr}")

            if cp_acc := tx.get("counterparty_account"):
                parts.append(f"CP Acc: {cp_acc}")

            if card := tx.get("card_last4"):
                parts.append(f"Card: {card}")

            if unmapped := tx.get("unmapped"):
                if unmapped != "{}":
                    parts.append(f"Extra: {unmapped}")

            tx_list_str += " | ".join(parts) + "\n"

        categories_str = "\n".join(self.categories)

        prompt = f"""
You are an expert financial data analyst.
Your task is to categorize the following transactions and identify a "Clean Name"
(merchant or entity name).

Guidelines:
1. **Clean Name**: Extract the real merchant name (e.g., "Uber" from "Uber *Trip ..."). 
   - Remove location codes, dates, and random identifiers.
   - For individuals, use "First Last".
   - For transfers, use "Transfer to/from X".
2. **Category**: Choose the BEST fit from the provided list.
   - Use "Time" to distinguish meals (Breakfast vs Lunch vs Dinner vs Nightlife).
   - Use "Amt" to distinguish subscriptions (fixed/round #s) vs regular spending.
   - Use "Extra" JSON data if standard fields are ambiguous.
   - If no category fits well, use "Uncategorized".
   - **Explain your choice** in the 'category_reason' field (short note).
3. **Suggestions**: If you believe a NEW category is strictly necessary:
   - Provide it in the 'suggested_category' field.
   - Explain WHY in the 'suggestion_reason' field.
   - Still pick the best existing match (or "Uncategorized") for the 'category' field.


Categories:
{categories_str}

Transactions:
{tx_list_str}
"""

        try:
            response = self.client.models.generate_content(
                model="gemini-3.0-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": CategorizationResponse,
                },
            )

            # Access the parsed result directly
            from typing import cast

            result = cast(CategorizationResponse | None, response.parsed)

            if not result or not result.transactions:
                logging.error("Empty or invalid response from LLM")
                return

            for item in result.transactions:
                if item.suggested_category:
                    logging.info(
                        f"LLM suggested new category '{item.suggested_category}' "
                        f"for {item.id}. Reason: {item.suggestion_reason}"
                    )

                self.llm_cache[item.id] = {
                    "clean_name": item.clean_name,
                    "category": item.category,
                    "category_reason": item.category_reason,
                    "confidence": 0.8,  # arbitrary confidence for LLM
                    "suggested_category": item.suggested_category,
                    "suggestion_reason": item.suggestion_reason,
                }

        except Exception as e:
            logging.error(f"Error querying LLM: {e}")

    def update_manual(self, tx_id: str, clean_name: str, category: str):
        """Manually verify/update a transaction."""
        self.manual_assignments[tx_id] = {
            "clean_name": clean_name,
            "category": category,
        }
        self.save_data()

    def add_pattern(
        self,
        pattern: str,
        clean_name: str,
        category: str,
        field: str = "counterparty",
    ):
        """Add a regex pattern."""
        self.patterns.append(
            {
                "pattern": pattern,
                "field": field,
                "clean_name": clean_name,
                "category": category,
            }
        )
        self.save_data()

    def add_category(self, category: str):
        """Add a new category if it doesn't exist."""
        if category not in self.categories:
            self.categories.append(category)
            self.save_data()
