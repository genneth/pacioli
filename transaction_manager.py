import json
import logging
import os
import re
from datetime import date
from typing import Any

import polars as pl
from openai import OpenAI
from pydantic import BaseModel

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

    def _get_counterparty(self, tx: dict[str, Any]) -> str:
        """
        Extracts the counterparty from the transaction, merging creditor and debtor
        information if necessary.
        """
        creditor = tx.get("creditorName")
        debtor = tx.get("debtorName")
        if creditor and debtor:
            return f"FROM {debtor} TO {creditor}"
        return creditor or debtor or ""

    def _get_remittance(self, tx: dict[str, Any]) -> str:
        """
        Extracts and normalizes remittance information.

        ASSUMPTION: No transaction has both 'remittanceInformationUnstructuredArray'
        and 'remittanceInformationUnstructured'. Checks for this condition and
        warns if violated.
        """
        unstructured = tx.get("remittanceInformationUnstructured")
        unstructured_array = tx.get("remittanceInformationUnstructuredArray")

        if unstructured and unstructured_array:
            logging.warning(
                f"Transaction {tx.get('internalTransactionId')} has both "
                "'remittanceInformationUnstructured' and "
                "'remittanceInformationUnstructuredArray'. This violates the "
                "assumption that they are mutually exclusive."
            )

        if unstructured_array:
            return "\n".join(unstructured_array)
        if unstructured:
            return str(unstructured)
        return ""

    def _find_matches(self, tx: dict[str, Any]) -> dict[str, Any]:
        """
        Internal method to find all possible matches for a transaction.
        """
        tx_id = tx.get("internalTransactionId")
        if not tx_id:
            return {}

        matches = {}  # source -> result

        # 1. Check Manual Assignments
        if tx_id in self.manual_assignments:
            assign = self.manual_assignments[tx_id]
            matches["MANUAL"] = {
                "clean_name": assign.get("clean_name"),
                "category": assign.get("category"),
                "source": "MANUAL",
                "confidence": 1.0,
            }

        # Check for Zero Amount
        try:
            amount = float(tx.get("transactionAmount", {}).get("amount", 0))
            if amount == 0:
                matches["ZERO_AMOUNT"] = {
                    "clean_name": "Zero Amount",
                    "category": "Excluded",
                    "source": "ZERO_AMOUNT",
                    "confidence": 1.0,
                }
        except (ValueError, TypeError):
            pass

        # 2. Check Patterns
        counterparty = self._get_counterparty(tx)
        remittance = self._get_remittance(tx)

        pattern_matches = []
        for pattern in self.patterns:
            p_str = pattern.get("pattern", "")
            p_field = pattern.get("field", "counterparty")

            target_text = ""
            if p_field == "counterparty":
                target_text = counterparty
            elif p_field == "remittance":
                target_text = remittance
            elif p_field == "any":
                target_text = f"{counterparty} {remittance}"

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
        if tx_id in self.llm_cache:
            cached = self.llm_cache[tx_id]
            matches["AI_CACHED"] = {
                "clean_name": cached.get("clean_name"),
                "category": cached.get("category"),
                "source": "AI_CACHED",
                "confidence": cached.get("confidence", 0.7),
            }

        return matches

    def resolve_transaction(self, tx: dict[str, Any]) -> dict[str, Any]:
        """
        Resolves a single transaction against Manual, Patterns, and Cache.
        Returns the enrichment data (clean_name, category, source, confidence).
        Checks for overlaps and logs warnings.
        """
        tx_id = tx.get("internalTransactionId")
        if not tx_id:
            return {}

        matches = self._find_matches(tx)

        # Check for multiple patterns warning
        if "_ALL_PATTERNS" in matches:
            pattern_matches = matches["_ALL_PATTERNS"]
            if len(pattern_matches) > 1:
                matched_pats = [m["pattern_matched"] for m in pattern_matches]
                logging.warning(
                    f"Transaction {tx_id} matched multiple patterns: {matched_pats}. "
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
                    f"Transaction {tx_id}: Manual assignment overrides Pattern match "
                    f"'{matches['PATTERN'].get('pattern_matched')}'"
                )
            if "AI_CACHED" in matches:
                logging.info(
                    f"Transaction {tx_id}: Manual assignment overrides AI Cache"
                )

        # Priority 2: Zero Amount
        elif "ZERO_AMOUNT" in matches:
            final_result = matches["ZERO_AMOUNT"]

        # Priority 3: Pattern
        elif "PATTERN" in matches:
            final_result = matches["PATTERN"]
            if "AI_CACHED" in matches:
                logging.info(f"Transaction {tx_id}: Pattern match overrides AI Cache")

        # Priority 4: Cache
        elif "AI_CACHED" in matches:
            final_result = matches["AI_CACHED"]

        # Clean up temporary field
        if "pattern_matched" in final_result:
            del final_result["pattern_matched"]

        return final_result

    def explain_transaction(self, tx: dict[str, Any]) -> dict[str, Any]:
        """
        Returns a detailed diagnosis of how the transaction is resolved.
        """
        matches = self._find_matches(tx)

        final_result = self.resolve_transaction(tx)

        return {
            "tx_id": tx.get("internalTransactionId"),
            "counterparty": self._get_counterparty(tx),
            "remittance": self._get_remittance(tx),
            "matches": matches,
            "final_result": final_result,
        }

    def test_pattern(
        self, transactions: list[dict], pattern: str, field: str = "counterparty"
    ) -> list[dict]:
        """
        Tests a regex pattern against a list of transactions.
        Returns a list of matching transactions with details.
        """
        matches = []
        for tx in transactions:
            target_text = ""
            if field == "counterparty":
                target_text = self._get_counterparty(tx)
            elif field == "remittance":
                target_text = self._get_remittance(tx)
            elif field == "any":
                target_text = f"{self._get_counterparty(tx)} {self._get_remittance(tx)}"

            if re.search(pattern, target_text, re.IGNORECASE):
                matches.append(
                    {
                        "tx_id": tx.get("internalTransactionId"),
                        "bookingDate": tx.get("bookingDate"),
                        "amount": tx.get("transactionAmount", {}).get("amount"),
                        "counterparty": self._get_counterparty(tx),
                        "remittance": self._get_remittance(tx),
                        "matched_text": target_text,
                    }
                )
        return matches

    def enrich_transactions(
        self,
        transactions_dict: dict[str, list[dict]],
    ) -> pl.DataFrame:
        """
        Takes the dict output of read_existing_transactions and returns a flat Polars
        DataFrame with enrichment columns.
        """
        all_txs = []
        for account_id, txs in transactions_dict.items():
            for tx in txs:
                # Basic flattening (you might want to customize this based on what you
                # need)
                booking_date_str = tx.get("bookingDate")
                try:
                    booking_date = (
                        date.fromisoformat(booking_date_str)
                        if booking_date_str
                        else None
                    )
                except ValueError:
                    booking_date = None

                flat_tx = {
                    "account": account_id,
                    "id": tx.get("internalTransactionId"),
                    "bookingDate": booking_date,
                    "amount": float(tx.get("transactionAmount", {}).get("amount", 0)),
                    "currency": tx.get("transactionAmount", {}).get("currency"),
                    "counterparty": self._get_counterparty(tx),
                    "remittance": self._get_remittance(tx),
                }

                # Capture unmapped data
                unmapped = tx.copy()
                for k in [
                    "internalTransactionId",
                    "bookingDate",
                    "transactionAmount",
                    "creditorName",
                    "debtorName",
                    "remittanceInformationUnstructuredArray",
                    "remittanceInformationUnstructured",
                ]:
                    unmapped.pop(k, None)

                flat_tx["unmapped"] = json.dumps(unmapped)

                # Apply resolution
                enrichment = self.resolve_transaction(tx)
                flat_tx.update(enrichment)

                all_txs.append(flat_tx)

        return pl.DataFrame(all_txs)

    def batch_process_llm(
        self,
        transactions_dict: dict[str, list[dict]],
        force_update=False,
    ):
        """
        Identifies unlabelled transactions and queries OpenAI.
        Updates the cache and saves.
        """
        if not self.oai:
            logging.warning("No OpenAI client provided.")
            return

        to_process = []

        # Gather transactions that need processing
        for _account_id, txs in transactions_dict.items():
            for tx in txs:
                tx_id = tx.get("internalTransactionId")
                if not tx_id:
                    continue

                # Skip if already in manual or pattern matched (logic repeated to
                # ensure we don't pay for resolved ones)
                res = self.resolve_transaction(tx)
                if res["source"] in ["MANUAL", "PATTERN", "ZERO_AMOUNT"]:
                    continue

                if not force_update and res["source"] == "AI_CACHED":
                    continue

                to_process.append(tx)

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
            tx_id = tx.get("internalTransactionId")
            counterparty = self._get_counterparty(tx) or "Unknown"
            remittance = self._get_remittance(tx)
            amount = tx.get("transactionAmount", {}).get("amount", "0")
            date = tx.get("bookingDate", "")
            tx_list_str += (
                f"ID: {tx_id} | Date: {date} | Amount: {amount} | "
                f"Counterparty: {counterparty} | Remittance: {remittance}\n"
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
            response = self.oai.beta.chat.completions.parse(
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
                    # Simple fuzzy match fallback or default could go here
                    # For now, just keep what LLM gave but warn
                    logging.warning(
                        f"LLM returned unknown category '{category}' for "
                        f"{item.id}"
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
