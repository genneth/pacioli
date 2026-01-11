import json

import polars as pl

from read_existing_transactions import (
    _get_counterparty,
    _get_remittance,
    flatten_transactions,
)


def test_get_counterparty_logic():
    tx1 = {"creditorName": "Creditor"}
    assert _get_counterparty(tx1) == "Creditor"

    tx2 = {"debtorName": "Debtor"}
    assert _get_counterparty(tx2) == "Debtor"

    tx3 = {"creditorName": "Creditor", "debtorName": "Debtor"}
    assert _get_counterparty(tx3) == "FROM Debtor TO Creditor"

    tx4 = {}
    assert _get_counterparty(tx4) == ""


def test_get_remittance_logic(caplog):
    import logging

    # Case 1: Simple string
    tx1 = {"remittanceInformationUnstructured": "Simple"}
    assert _get_remittance(tx1) == "Simple"

    # Case 2: Array
    tx2 = {"remittanceInformationUnstructuredArray": ["Line1", "Line2"]}
    assert _get_remittance(tx2) == "Line1\nLine2"

    # Case 3: Both (should warn)
    tx3 = {
        "internalTransactionId": "tx3",
        "remittanceInformationUnstructured": "Simple",
        "remittanceInformationUnstructuredArray": ["Line1", "Line2"],
    }
    with caplog.at_level(logging.WARNING):
        res = _get_remittance(tx3)
        assert res == "Line1\nLine2"
        assert "has both" in caplog.text


def test_flatten_transactions_structure():
    raw_txs = {
        "acc1": [
            {
                "internalTransactionId": "tx1",
                "bookingDate": "2023-01-01",
                "transactionAmount": {"amount": "10.00", "currency": "USD"},
                "creditorName": "Test Creditor",
                "remittanceInformationUnstructured": "Test Remittance",
                "extraField": "extraValue",
            },
            {
                "internalTransactionId": "tx2",
                "bookingDate": "2023-01-02",
                # Missing amount
                "debtorName": "Test Debtor",
            },
        ],
        "acc2": [],  # Empty account
    }
    df = flatten_transactions(raw_txs)

    assert isinstance(df, pl.DataFrame)
    assert df.height == 2

    # Check Row 1
    row1 = df.filter(pl.col("internalTransactionId") == "tx1").row(0, named=True)
    assert row1["account_id"] == "acc1"
    assert row1["amount"] == 10.0
    assert row1["currency"] == "USD"
    assert row1["counterparty"] == "Test Creditor"

    unmapped1 = json.loads(row1["unmapped_data"])
    assert "extraField" in unmapped1
    assert unmapped1["extraField"] == "extraValue"
    assert "internalTransactionId" not in unmapped1

    # Check Row 2
    row2 = df.filter(pl.col("internalTransactionId") == "tx2").row(0, named=True)
    assert row2["amount"] == 0.0  # Default
    assert row2["counterparty"] == "Test Debtor"


def test_flatten_empty():
    df = flatten_transactions({})
    assert isinstance(df, pl.DataFrame)
    assert df.height == 0
    assert "unmapped_data" in df.columns
