import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Transaction:
    account_id: str
    id: str
    booking_date: date
    amount: float
    currency: str
    counterparty: str
    remittance: str
    unmapped: str  # JSON string of the original raw data excluding mapped fields


def load_transactions(data_dir: str = "raw") -> list[Transaction]:
    """
    Reads, deduplicates, and flattens transaction data from the 'raw' directory.

    Returns:
        A list of unique Transaction objects.
    """
    raw_dumps = _load_raw_json_files(data_dir)
    return _process_transactions(raw_dumps)


def _load_raw_json_files(data_dir: str) -> dict[str, list[dict]]:
    """Loads all JSON files from account subdirectories in the data_dir."""
    raw_dumps: dict[str, list[dict]] = {}
    
    if not os.path.exists(data_dir):
        return raw_dumps

    for account in os.listdir(data_dir):
        account_path = os.path.join(data_dir, account)
        if not os.path.isdir(account_path):
            continue

        raw_dumps[account] = []
        for file_name in os.listdir(account_path):
            if not file_name.endswith(".json"):
                continue
                
            file_path = os.path.join(account_path, file_name)
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    raw_dumps[account].append(data)
                    logging.info(f"Loaded {file_name} for account {account}.")
            except json.JSONDecodeError:
                logging.error(f"Failed to decode JSON from {file_name}")
    
    return raw_dumps


def _process_transactions(raw_dumps: dict[str, list[dict]]) -> list[Transaction]:
    """Deduplicates and converts raw dumps into Transaction objects."""
    all_rows = []

    for account_id, dumps in raw_dumps.items():
        # Extract all booked transactions for this account
        account_transactions = []
        for dump in dumps:
            if not isinstance(dump, dict):
                continue
            
            # Navigate checks safely
            booked = dump.get("transactions", {}).get("booked")
            if isinstance(booked, list):
                account_transactions.extend(booked)

        # Deduplicate by ID
        seen_ids = set()
        for tx in account_transactions:
            if not isinstance(tx, dict):
                continue

            internal_id = tx.get("internalTransactionId")
            if not internal_id or internal_id in seen_ids:
                continue
            
            seen_ids.add(internal_id)
            
            # Convert to Transaction object
            transaction_obj = _map_to_transaction(account_id, tx)
            if transaction_obj:
                all_rows.append(transaction_obj)

    return all_rows


def _map_to_transaction(account_id: str, tx: dict[str, Any]) -> Transaction | None:
    """Maps a raw dictionary to a Transaction object."""
    internal_id = tx.get("internalTransactionId")
    if not internal_id:
        return None

    booking_date_str = tx.get("bookingDate")
    try:
        booking_date = (
            date.fromisoformat(booking_date_str) if booking_date_str else None
        )
    except ValueError:
        logging.error(
            f"Invalid date format for transaction {internal_id}: {booking_date_str}"
        )
        return None

    if not booking_date:
        return None

    # Handle amount
    amount_dict = tx.get("transactionAmount", {})
    try:
        amount = float(amount_dict.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0.0

    currency = amount_dict.get("currency", "")
    
    counterparty = _get_counterparty(tx)
    remittance = _get_remittance(tx)

    # Capture unmapped data
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

    return Transaction(
        account_id=account_id,
        id=internal_id,
        booking_date=booking_date,
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        remittance=remittance,
        unmapped=json.dumps(unmapped),
    )


def _get_counterparty(tx: dict[str, Any]) -> str:
    """Merges creditor and debtor information."""
    creditor = tx.get("creditorName")
    debtor = tx.get("debtorName")
    if creditor and debtor:
        return f"FROM {debtor} TO {creditor}"
    return creditor or debtor or ""


def _get_remittance(tx: dict[str, Any]) -> str:
    """Extracts and normalizes remittance information."""
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