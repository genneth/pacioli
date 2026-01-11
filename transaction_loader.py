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
    validated_data = _deduplicate_and_validate(raw_dumps)
    return _map_to_transactions(validated_data)


def get_latest_booking_dates(data_dir: str = "raw") -> dict[str, date]:
    """
    Returns the latest booking date for each account.
    Safe and robust: ensures all considered transactions have valid dates.
    """
    raw_dumps = _load_raw_json_files(data_dir)
    validated_data = _deduplicate_and_validate(raw_dumps)

    max_dates = {}
    for account, txs in validated_data.items():
        if not txs:
            continue
        # We can safely parse because _deduplicate_and_validate checked the format
        latest = max(date.fromisoformat(tx["bookingDate"]) for tx in txs)
        max_dates[account] = latest

    return max_dates


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


def _deduplicate_and_validate(
    raw_dumps: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """
    Deduplicates raw transactions and validates essential fields (ID, Date).
    Returns a dictionary mapping account IDs to lists of unique, valid transaction
    dicts.
    """
    validated_transactions = {}

    for account_id, dumps in raw_dumps.items():
        unique_txs = []
        seen_ids = set()

        # Extract all booked transactions for this account
        raw_txs = []
        for dump in dumps:
            if not isinstance(dump, dict):
                continue
            booked = dump.get("transactions", {}).get("booked")
            if isinstance(booked, list):
                raw_txs.extend(booked)

        for tx in raw_txs:
            if not isinstance(tx, dict):
                continue

            # Check ID
            internal_id = tx.get("internalTransactionId")
            if not internal_id:
                continue

            # Check Date
            booking_date_str = tx.get("bookingDate")
            if not booking_date_str:
                continue
            try:
                date.fromisoformat(booking_date_str)
            except ValueError:
                logging.error(
                    f"Invalid date format for transaction {internal_id} in "
                    f"{account_id}: {booking_date_str}"
                )
                continue

            # Deduplicate
            if internal_id in seen_ids:
                continue

            seen_ids.add(internal_id)
            unique_txs.append(tx)

        validated_transactions[account_id] = unique_txs

    return validated_transactions


def _map_to_transactions(validated_data: dict[str, list[dict]]) -> list[Transaction]:
    """Converts validated transaction dicts into Transaction objects."""
    all_rows = []
    for account_id, txs in validated_data.items():
        for tx in txs:
            transaction_obj = _map_single_transaction(account_id, tx)
            if transaction_obj:
                all_rows.append(transaction_obj)
    return all_rows


def _map_single_transaction(account_id: str, tx: dict[str, Any]) -> Transaction | None:
    """Maps a raw dictionary to a Transaction object."""
    # These are already checked in _deduplicate_and_validate, but safe to keep or
    # assumes valid
    internal_id = tx["internalTransactionId"]
    booking_date = date.fromisoformat(tx["bookingDate"])

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
