import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

import polars as pl


### Read existing transactions from raw
def read_existing_transactions() -> dict[str, list[dict]]:
    """
    Reads and aggregates transaction data from the 'raw' directory.

    Assumptions:
    1. Directory Structure:
       - A 'raw' directory exists in the current working directory.
       - Subdirectories within 'raw' represent unique accounts.
       - Inside each account directory, files ending in '.json' contain transaction
         data.

    2. JSON File Structure:
       - Each JSON file contains a root dictionary.
       - The root dictionary has a 'transactions' key, which is itself a dictionary.
       - The 'transactions' dictionary has a 'booked' key, which is a list of
         transaction objects.

    3. Transaction Object Structure:
       - Each item in the 'booked' list is a dictionary representing a transaction.
       - Each transaction dictionary MUST contain a truthy 'internalTransactionId'
         field used for deduplication.

    Returns:
        A dictionary mapping account IDs (directory names) to a list of unique
        transaction dictionaries.
    """
    # load existing json dumps
    raw_dumps: dict[str, list] = {}
    if os.path.exists("raw"):
        for account in os.listdir("raw"):
            account_path = os.path.join("raw", account)
            if not os.path.isdir(account_path):
                continue

            raw_dumps[account] = []
            for file in os.listdir(account_path):
                if not file.endswith(".json"):
                    logging.getLogger().warning(
                        f"File {file} is not a JSON file. Skipping."
                    )
                    continue
                file_full_path = os.path.join(account_path, file)
                with open(file_full_path, encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                        raw_dumps[account].append(data)
                        logging.getLogger().info(
                            f"Loaded {file} for account {account}."
                        )
                    except json.JSONDecodeError:
                        logging.getLogger().error(f"Failed to decode JSON from {file}")

    # Merge and deduplicate
    per_account_transactions = {}

    for account, dumps in raw_dumps.items():
        all_transactions = []
        for i, dump in enumerate(dumps):
            if not isinstance(dump, dict):
                raise ValueError(
                    f"Dump {i} for account '{account}' is not a dictionary."
                )

            transactions_wrapper = dump.get("transactions")
            if not isinstance(transactions_wrapper, dict):
                raise ValueError(
                    f"Dump {i} for account '{account}' missing 'transactions' dict."
                )

            txs = transactions_wrapper.get("booked")
            if not isinstance(txs, list):
                raise ValueError(
                    f"Dump {i} for account '{account}' missing 'booked' list in "
                    "'transactions'."
                )

            all_transactions.extend(txs)

        # Deduplication based on internalTransactionId
        unique_transactions = []
        seen_ids = set()

        for tx in all_transactions:
            if not isinstance(tx, dict):
                raise ValueError(f"Found non-dict transaction in account '{account}'.")

            tx_id = tx.get("internalTransactionId")

            if not tx_id:
                raise ValueError(
                    "Transaction missing internalTransactionId in "
                    f"account '{account}'. Transaction dump: {json.dumps(tx)}"
                )

            if tx_id not in seen_ids:
                seen_ids.add(tx_id)
                unique_transactions.append(tx)

        per_account_transactions[account] = unique_transactions

    return per_account_transactions


@dataclass
class TransactionRow:
    account_id: str
    internalTransactionId: str
    bookingDate: str
    amount: float
    currency: str
    counterparty: str
    remittance: str
    unmapped_data: str


def _get_counterparty(tx: dict[str, Any]) -> str:
    """
    Extracts the counterparty from the transaction, merging creditor and debtor
    information if necessary.
    """
    creditor = tx.get("creditorName")
    debtor = tx.get("debtorName")
    if creditor and debtor:
        return f"FROM {debtor} TO {creditor}"
    return creditor or debtor or ""


def _get_remittance(tx: dict[str, Any]) -> str:
    """
    Extracts and normalizes remittance information.
    """
    unstructured = tx.get("remittanceInformationUnstructured")
    unstructured_array = tx.get("remittanceInformationUnstructuredArray")

    if unstructured and unstructured_array:
        logging.warning(
            f"Transaction {tx.get('internalTransactionId')} has both "
            "'remittanceInformationUnstructured' and "
            "'remittanceInformationUnstructuredArray'."
        )

    if unstructured_array:
        return "\n".join(unstructured_array)
    if unstructured:
        return str(unstructured)
    return ""


def flatten_transactions(transactions_dict: dict[str, list[dict]]) -> pl.DataFrame:
    """
    Flattens the dictionary of transactions into a Polars DataFrame.
    """
    all_rows = []
    for account_id, txs in transactions_dict.items():
        for tx in txs:
            # Extract basic fields
            internal_id = tx.get("internalTransactionId")
            if not internal_id:
                # Should be handled by read_existing_transactions but good to be safe
                continue

            booking_date = tx.get("bookingDate")

            # Handle amount safely
            amount_dict = tx.get("transactionAmount", {})
            try:
                amount = float(amount_dict.get("amount", 0))
            except (ValueError, TypeError):
                amount = 0.0

            currency = amount_dict.get("currency", "")

            counterparty = _get_counterparty(tx)
            remittance = _get_remittance(tx)

            # Capture unmapped data
            # Create a copy to remove mapped fields
            unmapped = tx.copy()
            mapped_keys = [
                "internalTransactionId",
                "bookingDate",
                "transactionAmount",
                "creditorName",
                "debtorName",
                "remittanceInformationUnstructuredArray",
                "remittanceInformationUnstructured",
            ]
            for k in mapped_keys:
                unmapped.pop(k, None)

            unmapped_json = json.dumps(unmapped)

            row = TransactionRow(
                account_id=account_id,
                internalTransactionId=internal_id,
                bookingDate=booking_date,  # type: ignore
                amount=amount,
                currency=currency,
                counterparty=counterparty,
                remittance=remittance,
                unmapped_data=unmapped_json,
            )
            all_rows.append(asdict(row))

    if not all_rows:
        return pl.DataFrame(
            [],
            schema={
                "account_id": pl.Utf8,
                "internalTransactionId": pl.Utf8,
                "bookingDate": pl.Utf8,
                "amount": pl.Float64,
                "currency": pl.Utf8,
                "counterparty": pl.Utf8,
                "remittance": pl.Utf8,
                "unmapped_data": pl.Utf8,
            },
        )

    return pl.DataFrame(all_rows)


def get_transactions_df() -> pl.DataFrame:
    """
    Reads existing transactions and returns them as a flattened DataFrame.
    """
    return flatten_transactions(read_existing_transactions())
