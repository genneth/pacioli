import json
from datetime import date
from transaction_loader import (
    Transaction,
    _get_counterparty,
    _get_remittance,
    _map_to_transaction,
    load_transactions,
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


def test_map_to_transaction_structure():
    tx_dict = {
        "internalTransactionId": "tx1",
        "bookingDate": "2023-01-01",
        "transactionAmount": {"amount": "10.00", "currency": "USD"},
        "creditorName": "Test Creditor",
        "remittanceInformationUnstructured": "Test Remittance",
        "extraField": "extraValue",
    }
    
    tx = _map_to_transaction("acc1", tx_dict)
    
    assert isinstance(tx, Transaction)
    assert tx.account_id == "acc1"
    assert tx.id == "tx1"
    assert tx.booking_date == date(2023, 1, 1)
    assert tx.amount == 10.0
    assert tx.currency == "USD"
    assert tx.counterparty == "Test Creditor"
    assert tx.remittance == "Test Remittance"

    unmapped = json.loads(tx.unmapped)
    assert "extraField" in unmapped
    assert unmapped["extraField"] == "extraValue"
    assert "internalTransactionId" not in unmapped


def test_map_to_transaction_missing_date():
    tx_dict = {
        "internalTransactionId": "tx2",
        # Missing date
        "transactionAmount": {"amount": "10.00", "currency": "USD"},
    }
    tx = _map_to_transaction("acc1", tx_dict)
    assert tx is None

def test_map_to_transaction_invalid_date():
    tx_dict = {
        "internalTransactionId": "tx3",
        "bookingDate": "invalid-date",
        "transactionAmount": {"amount": "10.00", "currency": "USD"},
    }
    tx = _map_to_transaction("acc1", tx_dict)
    assert tx is None

def test_load_transactions_mock():
    # Mock os.listdir and open/json.load
    # This is a bit complex to mock fully efficiently, 
    # so we might rely on integration tests or a small data fixture.
    # For now, let's just test the process logic if we can mock _load_raw_json_files
    
    mock_raw = {
        "acc1": [
            {
                "transactions": {
                    "booked": [
                         {
                            "internalTransactionId": "tx1",
                            "bookingDate": "2023-01-01",
                            "transactionAmount": {"amount": "10.00", "currency": "USD"},
                         }
                    ]
                }
            }
        ]
    }
    
    # We can test the private _process_transactions method directly
    from transaction_loader import _process_transactions
    rows = _process_transactions(mock_raw)
    
    assert len(rows) == 1
    assert rows[0].id == "tx1"
    assert rows[0].account_id == "acc1"