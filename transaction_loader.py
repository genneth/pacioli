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
    counterparty: str | None
    remittance: str | None
    time_of_day: str | None = None
    tx_type: str | None = None
    foreign_currency: str | None = None
    card_last4: str | None = None
    counterparty_account: str | None = None
    unmapped: str = "{}"  # JSON string of the original raw data excluding mapped fields


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

            transactions = dump.get("transactions")
            if not isinstance(transactions, dict):
                continue

            booked = transactions.get("booked")
            if isinstance(booked, list):
                raw_txs.extend(booked)
        for tx in raw_txs:
            if not isinstance(tx, dict):
                continue

            # We need a stable ID to deduplicate across overlapping fetch windows
            internal_id = tx.get("internalTransactionId")
            if not internal_id:
                continue

            # We need a valid booking date to ensure the transaction can be ordered
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

            # Deduplicate by ID
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


def _extract_extra_fields(tx: dict[str, Any]) -> dict[str, Any]:
    """Extracts additional high-value fields for categorization."""
    extras: dict[str, Any] = {
        "time_of_day": None,
        "tx_type": None,
        "foreign_currency": None,
        "card_last4": None,
        "counterparty_account": None,
    }

    # 1. Time of Day
    booking_dt = tx.get("bookingDateTime")
    if booking_dt and "T" in booking_dt:
        try:
            # Extract HH:MM from ISO format "YYYY-MM-DDTHH:MM:SS.mmmmmmZ"
            time_part = booking_dt.split("T")[1]
            extras["time_of_day"] = time_part[:5]  # HH:MM
        except IndexError:
            pass

    # 2. Transaction Type
    extras["tx_type"] = tx.get("proprietaryBankTransactionCode")

    # 3. Foreign Currency
    currency_exchange = tx.get("currencyExchange")
    if isinstance(currency_exchange, dict):
        extras["foreign_currency"] = currency_exchange.get("sourceCurrency")

    # 4. Card Last 4
    ads = tx.get("additionalDataStructured")
    if isinstance(ads, dict):
        card_inst = ads.get("cardInstrument")
        if isinstance(card_inst, dict):
            extras["card_last4"] = card_inst.get("identification")

    # 5. Counterparty Account
    # Check creditor first, then debtor (assuming usually one is the 'other' party)
    # Note: Logic might need refinement if 'debtor' is always the user for outgoing
    # and 'creditor' for incoming. For now, grab whichever has a bban/iban that isn't
    # empty.

    # Actually, we want to know who the *other* party is.
    # If amount is negative, user is debtor, so counterparty is creditorAccount.
    # If amount is positive, user is creditor, so counterparty is debtorAccount.
    # However, 'transactionAmount' isn't passed here easily without parsing again or
    # passing it in. We'll just look for both and extracting the one that seems to be
    # the external entity. Since we can't easily know which is 'us' without account
    # context, we'll try to extract useful info from either.

    creditor_acc = tx.get("creditorAccount", {})
    debtor_acc = tx.get("debtorAccount", {})

    # Simplistic approach: Just grab IBAN or BBAN if present
    acc_id = (
        creditor_acc.get("bban")
        or creditor_acc.get("iban")
        or debtor_acc.get("bban")
        or debtor_acc.get("iban")
    )

    extras["counterparty_account"] = acc_id

    return extras


def _map_single_transaction(account_id: str, tx: dict[str, Any]) -> Transaction:
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

    counterparty, remittance = _elide_transaction_info(
        counterparty, remittance, internal_id
    )

    extras = _extract_extra_fields(tx)

    # We want to preserve all raw data that hasn't been extracted into first-class
    # fields. This allows for future reprocessing or debugging without needing to
    # re-fetch from the bank.
    unmapped = tx.copy()
    mapped_keys = [
        "internalTransactionId",
        "bookingDate",
        "transactionAmount",
        "creditorName",
        "debtorName",
        "remittanceInformationUnstructuredArray",
        "remittanceInformationUnstructured",
        # Extracted extra fields
        "bookingDateTime",
        "proprietaryBankTransactionCode",
        "currencyExchange",
        "creditorAccount",
        "debtorAccount",
        # Safe to drop fields (technical or redundant)
        "transactionId",
        "valueDate",
        "valueDateTime",
        "balanceAfterTransaction",
    ]
    for k in mapped_keys:
        unmapped.pop(k, None)

    # Clean up additionalDataStructured if present
    if "additionalDataStructured" in unmapped:
        ads = unmapped["additionalDataStructured"]
        if isinstance(ads, dict):
            # Remove chargeAmount
            ads.pop("chargeAmount", None)

            # Clean up cardInstrument
            if "cardInstrument" in ads:
                ci = ads["cardInstrument"]
                if isinstance(ci, dict):
                    ci.pop("cardSchemeName", None)
                    ci.pop("name", None)
                    # We extracted identification, so remove it too
                    ci.pop("identification", None)

                    # If cardInstrument is now empty (only had dropped fields),
                    # remove it
                    if not ci:
                        ads.pop("cardInstrument", None)

            # If additionalDataStructured is now empty, remove it
            if not ads:
                unmapped.pop("additionalDataStructured", None)

    return Transaction(
        account_id=account_id,
        id=internal_id,
        booking_date=booking_date,
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        remittance=remittance,
        time_of_day=extras["time_of_day"],
        tx_type=extras["tx_type"],
        foreign_currency=extras["foreign_currency"],
        card_last4=extras["card_last4"],
        counterparty_account=extras["counterparty_account"],
        unmapped=json.dumps(unmapped),
    )


def _get_counterparty(tx: dict[str, Any]) -> str | None:
    """Merges creditor and debtor information."""
    creditor = tx.get("creditorName")
    debtor = tx.get("debtorName")
    if creditor and debtor:
        return f"FROM {debtor} TO {creditor}"
    return creditor or debtor or None


def _get_remittance(tx: dict[str, Any]) -> str | None:
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
    return None


def _elide_transaction_info(
    counterparty: str | None, remittance: str | None, internal_id: str
) -> tuple[str | None, str | None]:
    """
    Elides counterparty and remittance information to avoid duplication.
    If one contains the other, keep the longer one in counterparty and clear remittance.

    This reduces token usage when sending data to the LLM and reduces visual noise
    for the user.
    """
    new_cp = counterparty
    new_rm = remittance

    if not counterparty:
        if remittance:
            new_cp = remittance
            new_rm = None
        else:
            logging.warning(
                f"Transaction {internal_id} has no counterparty or remittance data."
            )
            new_cp = None
            new_rm = None
    else:
        if remittance:
            # If one string is contained in the other, take the longer/richer one as
            # counterparty
            if counterparty in remittance:
                new_cp = remittance
                new_rm = None
            elif remittance in counterparty:
                new_cp = counterparty
                new_rm = None
        else:
            new_rm = None

    return new_cp, new_rm
