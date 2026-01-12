import json
import logging
from typing import Any

from transaction_loader import (
    _deduplicate_and_validate,
    _elide_transaction_info,
    _get_counterparty,
    _get_remittance,
    _map_single_transaction,
    load_transactions,
)

# --- Unit Tests for Helper Functions ---


def test_elide_transaction_info():
    # 1. Match
    cp, rm = _elide_transaction_info("STARBUCKS", "STARBUCKS", "tx1")
    assert cp == "STARBUCKS"
    assert rm is None

    # 2. Differ
    cp, rm = _elide_transaction_info("STARBUCKS", "COFFEE", "tx2")
    assert cp == "STARBUCKS"
    assert rm == "COFFEE"

    # 3. Counterparty in Remittance (use longer)
    cp, rm = _elide_transaction_info("AMZN", "AMZN MKTP", "tx3")
    assert cp == "AMZN MKTP"
    assert rm is None

    # 4. Remittance in Counterparty (use longer)
    cp, rm = _elide_transaction_info("STARBUCKS LONDON", "STARBUCKS", "tx4")
    assert cp == "STARBUCKS LONDON"
    assert rm is None

    # 5. Counterparty missing (use remittance)
    cp, rm = _elide_transaction_info(None, "ONLY REMITTANCE", "tx5")
    assert cp == "ONLY REMITTANCE"
    assert rm is None

    # 6. Remittance missing
    cp, rm = _elide_transaction_info("ONLY COUNTERPARTY", None, "tx6")
    assert cp == "ONLY COUNTERPARTY"
    assert rm is None

    # 7. Both missing
    cp, rm = _elide_transaction_info(None, None, "tx7")
    assert cp is None
    assert rm is None


def test_get_counterparty_logic():
    # Case 1: Only Creditor
    tx1 = {"creditorName": "Creditor"}
    assert _get_counterparty(tx1) == "Creditor"

    # Case 2: Only Debtor
    tx2 = {"debtorName": "Debtor"}
    assert _get_counterparty(tx2) == "Debtor"

    # Case 3: Both
    tx3 = {"creditorName": "Creditor", "debtorName": "Debtor"}
    assert _get_counterparty(tx3) == "FROM Debtor TO Creditor"

    # Case 4: Neither
    tx4: dict[str, Any] = {}
    assert _get_counterparty(tx4) is None


def test_get_remittance_logic(caplog):
    # Case 1: Simple string
    tx1 = {"remittanceInformationUnstructured": "Simple"}
    assert _get_remittance(tx1) == "Simple"

    # Case 2: Array
    tx2 = {"remittanceInformationUnstructuredArray": ["Line1", "Line2"]}
    assert _get_remittance(tx2) == "Line1\nLine2"

    # Case 3: Both (should warn and prefer Array)
    tx3 = {
        "internalTransactionId": "tx3",
        "remittanceInformationUnstructured": "Simple",
        "remittanceInformationUnstructuredArray": ["Line1", "Line2"],
    }
    with caplog.at_level(logging.WARNING):
        res = _get_remittance(tx3)
        assert res == "Line1\nLine2"
        assert "has both" in caplog.text

    # Case 4: Neither
    tx4: dict[str, Any] = {}
    assert _get_remittance(tx4) is None

    # Case 5: Empty Array
    tx5: dict[str, Any] = {"remittanceInformationUnstructuredArray": []}
    assert _get_remittance(tx5) is None


# --- Unit Tests for Validation & Deduplication ---


def test_deduplicate_and_validate_edge_cases(caplog):
    raw_dumps: dict[str, list[dict[Any, Any]]] = {
        "acc1": [
            {
                "transactions": {
                    "booked": [
                        # 1. Valid
                        {
                            "internalTransactionId": "valid_1",
                            "bookingDate": "2023-01-01",
                            "val": 1,
                        },
                        # 2. Missing ID
                        {"bookingDate": "2023-01-02"},
                        # 3. Missing Date
                        {"internalTransactionId": "missing_date"},
                        # 4. Invalid Date Format
                        {
                            "internalTransactionId": "bad_date",
                            "bookingDate": "not-a-date",
                        },
                        # 5. Duplicate ID (Same list)
                        {
                            "internalTransactionId": "valid_1",
                            "bookingDate": "2023-01-01",
                            "val": 2,  # Should be ignored
                        },
                    ]
                }
            },
            # Second dump for same account
            {
                "transactions": {
                    "booked": [
                        # 6. Duplicate ID (Different list/file)
                        {
                            "internalTransactionId": "valid_1",
                            "bookingDate": "2023-01-01",
                            "val": 3,  # Should be ignored
                        },
                        # 7. Another Valid
                        {
                            "internalTransactionId": "valid_2",
                            "bookingDate": "2023-01-05",
                        },
                    ]
                }
            },
            # Malformed dump structure
            {},
            {"transactions": "not-a-dict"},
            {"transactions": {"booked": "not-a-list"}},
        ]
    }

    with caplog.at_level(logging.ERROR):
        validated = _deduplicate_and_validate(raw_dumps)

    assert "acc1" in validated
    txs = validated["acc1"]

    # Should only have valid_1 and valid_2
    assert len(txs) == 2
    ids = {tx["internalTransactionId"] for tx in txs}
    assert ids == {"valid_1", "valid_2"}

    # Verify first instance of valid_1 was kept
    valid_1 = next(t for t in txs if t["internalTransactionId"] == "valid_1")
    assert valid_1["val"] == 1

    # Verify error log for bad date
    assert "Invalid date format" in caplog.text
    assert "bad_date" in caplog.text


def test_map_single_transaction_robustness():
    # Base valid transaction
    base_tx: dict[str, Any] = {
        "internalTransactionId": "tx1",
        "bookingDate": "2023-01-01",
    }

    # Case 1: Normal Amount
    tx1 = base_tx.copy()
    tx1["transactionAmount"] = {"amount": "10.50", "currency": "EUR"}
    res1 = _map_single_transaction("acc1", tx1)
    assert res1.amount == 10.50
    assert res1.currency == "EUR"

    # Case 2: Missing Amount Block
    tx2 = base_tx.copy()
    res2 = _map_single_transaction("acc1", tx2)
    assert res2.amount == 0.0
    assert res2.currency == ""

    # Case 3: Invalid Amount Value
    tx3 = base_tx.copy()
    tx3["transactionAmount"] = {"amount": "invalid", "currency": "USD"}
    res3 = _map_single_transaction("acc1", tx3)
    assert res3.amount == 0.0
    assert res3.currency == "USD"

    # Case 4: Unmapped Data Check
    tx4 = base_tx.copy()
    tx4["extraField"] = "keepMe"
    tx4["transactionAmount"] = {"amount": "10", "currency": "USD"}
    tx4["bookingDateTime"] = "2023-01-01T15:00:00Z"
    res4 = _map_single_transaction("acc1", tx4)

    assert res4.time_of_day == "15:00"
    unmapped = json.loads(res4.unmapped)
    assert "extraField" in unmapped
    assert unmapped["extraField"] == "keepMe"
    # Ensure mapped fields (including extra extracted ones) are removed
    assert "internalTransactionId" not in unmapped
    assert "transactionAmount" not in unmapped
    assert "bookingDateTime" not in unmapped


def test_extract_extra_fields():
    from transaction_loader import _extract_extra_fields

    # Full case
    tx = {
        "bookingDateTime": "2023-01-01T12:34:56.789Z",
        "proprietaryBankTransactionCode": "CARD_PAYMENT",
        "currencyExchange": {"sourceCurrency": "USD"},
        "additionalDataStructured": {
            "cardInstrument": {"identification": "1234"}
        },
        "creditorAccount": {"iban": "GB123"},
    }
    res = _extract_extra_fields(tx)
    assert res["time_of_day"] == "12:34"
    assert res["tx_type"] == "CARD_PAYMENT"
    assert res["foreign_currency"] == "USD"
    assert res["card_last4"] == "1234"
    assert res["counterparty_account"] == "GB123"

    # Partial case
    tx2 = {
        "bookingDateTime": "2023-01-01",  # No T
        "debtorAccount": {"bban": "BB456"},
    }
    res2 = _extract_extra_fields(tx2)
    assert res2["time_of_day"] is None
    assert res2["counterparty_account"] == "BB456"

    # Empty case
    res3 = _extract_extra_fields({})
    assert all(v is None for v in res3.values())


# --- Integration Test with Temporary Directory ---


def test_load_transactions_integration(tmp_path, caplog):
    """
    Simulates a 'raw' directory structure with mixed valid and invalid files.
    """
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    # Account 1
    acc1_dir = raw_dir / "acc1"
    acc1_dir.mkdir()

    # File 1: Valid JSON, Valid Transactions
    file1_content = {
        "transactions": {
            "booked": [
                {
                    "internalTransactionId": "tx1",
                    "bookingDate": "2023-01-01",
                    "transactionAmount": {"amount": "100.00", "currency": "GBP"},
                    "creditorName": "Store A",
                }
            ]
        }
    }
    (acc1_dir / "2023-01-01.json").write_text(
        json.dumps(file1_content), encoding="utf-8"
    )

    # File 2: Invalid JSON (Syntax Error)
    (acc1_dir / "garbage.json").write_text("{ this is not json }", encoding="utf-8")

    # File 3: Valid JSON, but malformed transaction structure inside
    file3_content = {
        "transactions": {
            "booked": [
                {
                    "internalTransactionId": "tx2",
                    # Missing Date
                    "transactionAmount": {"amount": "50.00", "currency": "GBP"},
                }
            ]
        }
    }
    (acc1_dir / "2023-01-02.json").write_text(
        json.dumps(file3_content), encoding="utf-8"
    )

    # Account 2 (Empty)
    acc2_dir = raw_dir / "acc2"
    acc2_dir.mkdir()

    # Run the loader
    with caplog.at_level(logging.INFO):
        transactions = load_transactions(str(raw_dir))

    # Verification

    # 1. We expect only 1 valid transaction (tx1)
    assert len(transactions) == 1
    tx = transactions[0]
    assert tx.id == "tx1"
    assert tx.account_id == "acc1"
    assert tx.amount == 100.0

    # 2. Check Logs
    # Should see error for garbage.json
    assert "Failed to decode JSON" in caplog.text
    # Should see loaded info for valid files
    assert "Loaded 2023-01-01.json" in caplog.text
