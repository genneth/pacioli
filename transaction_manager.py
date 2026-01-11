import json
import logging
import os
import re
from dataclasses import asdict
from typing import Any

import polars as pl
from openai import OpenAI
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


class CategorizationResponse(BaseModel):
    transactions: list[TransactionResult]


class TransactionManager:
    def __init__(self, oai_client: OpenAI | None = None, data_dir: str = DATA_DIR):
        self.oai = oai_client
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

    def _find_matches(self, tx: Transaction) -> dict[str, Any]:
        """
        Internal method to find all possible matches for a transaction.
        """
        if not tx.id:
            return {}

        matches: dict[str, Any] = {}  # source -> result

        # 1. Check Manual Assignments
        if tx.id in self.manual_assignments:
            assign = self.manual_assignments[tx.id]
            matches["MANUAL"] = {
                "clean_name": assign.get("clean_name"),
                "category": assign.get("category"),
                "source": "MANUAL",
                "confidence": 1.0,
            }

        # Check for Zero Amount
        if tx.amount == 0:
            matches["ZERO_AMOUNT"] = {
                "clean_name": "Zero Amount",
                "category": "Excluded",
                "source": "ZERO_AMOUNT",
                "confidence": 1.0,
            }

        # 2. Check Patterns
        pattern_matches = []
        for pattern in self.patterns:
            p_str = pattern.get("pattern", "")
            p_field = pattern.get("field", "counterparty")

            target_text = ""
            if p_field == "counterparty":
                target_text = tx.counterparty
            elif p_field == "remittance":
                target_text = tx.remittance
            elif p_field == "any":
                target_text = f"{tx.counterparty} {tx.remittance}"

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

        # 3. Check LLM Cache
        if tx.id in self.llm_cache:
            cached = self.llm_cache[tx.id]
            matches["AI_CACHED"] = {
                "clean_name": cached.get("clean_name"),
                "category": cached.get("category"),
                "source": "AI_CACHED",
                "confidence": cached.get("confidence", 0.7),
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

        final_result: dict[str, Any] = {
            "clean_name": None,
            "category": None,
            "source": None,
            "confidence": 0.0,
        }

        # Priority 1: Manual
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

        # Priority 2: Zero Amount
        elif "ZERO_AMOUNT" in matches:
            final_result = matches["ZERO_AMOUNT"]

        # Priority 3: Pattern
        elif "PATTERN" in matches:
            final_result = matches["PATTERN"]
            if "AI_CACHED" in matches:
                logging.info(f"Transaction {tx.id}: Pattern match overrides AI Cache")

        # Priority 4: Cache
        elif "AI_CACHED" in matches:
            final_result = matches["AI_CACHED"]

        # Clean up temporary field
        if "pattern_matched" in final_result:
            del final_result["pattern_matched"]

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
    ) -> list[dict]:
        """
        Tests a regex pattern against a list of transactions.
        Returns a list of matching transactions with details.
        """
        matches = []
        for tx in transactions:
            target_text = ""
            if field == "counterparty":
                target_text = tx.counterparty
            elif field == "remittance":
                target_text = tx.remittance
            elif field == "any":
                target_text = f"{tx.counterparty} {tx.remittance}"

            if re.search(pattern, target_text, re.IGNORECASE):
                matches.append(
                    {
                        "tx_id": tx.id,
                        "bookingDate": str(tx.booking_date),
                        "amount": tx.amount,
                        "counterparty": tx.counterparty,
                        "remittance": tx.remittance,
                        "matched_text": target_text,
                    }
                )
        return matches

    def enrich_transactions(
        self,
        transactions: list[Transaction],
    ) -> pl.DataFrame:
        """
        Takes a list of Transactions and returns a flat Polars DataFrame with
        enrichment columns.
        """
        all_txs = []
        for tx in transactions:
            # Basic flattening
            flat_tx = asdict(tx)

            # Elide remittance where possible
            cp = flat_tx.get("counterparty")
            rm = flat_tx.get("remittance")

            if not cp:
                if rm:
                    flat_tx["counterparty"] = rm
                    flat_tx["remittance"] = None
                else:
                    logging.warning(
                        f"Transaction {tx.id} has no counterparty or remittance data."
                    )
            else:
                if rm:
                    if cp in rm:
                        flat_tx["counterparty"] = rm
                        flat_tx["remittance"] = None
                    elif rm in cp:
                        flat_tx["counterparty"] = cp
                        flat_tx["remittance"] = None
                # else:  # nothing to do

            # Apply resolution
            enrichment = self.resolve_transaction(tx)
            flat_tx.update(enrichment)

            all_txs.append(flat_tx)

        if not all_txs:
            raise ValueError("No transactions to enrich.")

        return pl.DataFrame(all_txs)

    def batch_process_llm(
        self,
        transactions: list[Transaction],
        force_update=False,
    ):
        """
        Identifies unlabelled transactions and queries OpenAI.
        Updates the cache and saves.
        """
        if not self.oai:
            logging.warning("No OpenAI client provided.")
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
        chunk_size = 50
        for i in range(0, len(to_process), chunk_size):
            chunk = to_process[i : i + chunk_size]
            self._query_llm_chunk(chunk)
            self.save_data()  # Save incrementally

    def _query_llm_chunk(self, tx_chunk: list[dict]):
        """
        Helper to query OpenAI for a chunk of transactions.
        """
        if not self.oai:
            return

        # Prepare prompt
        tx_list_str = ""
        for tx in tx_chunk:
            # tx is a dict from Polars
            tx_id = tx.get("id")
            booking_date = tx.get("booking_date")
            amount = tx.get("amount")
            counterparty = tx.get("counterparty") or "Unknown"

            # enrich_transactions handles remittance deduplication
            remittance_val = tx.get("remittance")
            remittance_str = f"| Remittance: {remittance_val}" if remittance_val else ""

            tx_list_str += (
                f"ID: {tx_id} | Date: {booking_date} | Amount: {amount} | "
                f"Counterparty: {counterparty} {remittance_str}\n"
            )

        categories_str = "\n".join(self.categories)

        prompt = f"""
You are a financial assistant.
Categorize the following transactions and provide a clean merchant name.
Use ONLY the provided categories. If none fit perfectly, use the best available or
"Uncategorized".

Categories:
{categories_str}

Transactions:
{tx_list_str}
"""

        try:
            response = self.oai.chat.completions.parse(
                model="gpt-5.2-chat-latest",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful financial categorization "
                        "assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format=CategorizationResponse,
            )

            result: CategorizationResponse | None = response.choices[0].message.parsed

            if not result or not result.transactions:
                logging.error("Empty or invalid response from LLM")
                return

            for item in result.transactions:
                # Validate category is in our allowed list, fallback if LLM hallucinated
                category = item.category
                if category not in self.categories and category != "Uncategorized":
                    logging.warning(
                        f"LLM returned unknown category '{category}' for {item.id}"
                    )

                self.llm_cache[item.id] = {
                    "clean_name": item.clean_name,
                    "category": category,
                    "confidence": 0.8,  # arbitrary confidence for LLM
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
