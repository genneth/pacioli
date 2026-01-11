from polars import col as C
from transaction_manager import TransactionManager

def test_enrich_transactions_remittance_normalized():
    tm = TransactionManager()
    
    # Mock data
    raw_txs = {
        "acc1": [
            {
                "internalTransactionId": "tx1",
                "transactionId": "t1",
                "bookingDate": "2023-01-01",
                "transactionAmount": {"amount": "10.00", "currency": "USD"},
                "creditorName": "Test Creditor",
                "remittanceInformationUnstructuredArray": ["part1", "part2"]
            }
        ]
    }
    
    # enrich
    df = tm.enrich_transactions(raw_txs)
    
    assert "counterparty" in df.columns
    assert "creditorName" not in df.columns
    assert df.select(C.counterparty).item(0, 0) == "Test Creditor"
    
    # check remittance type
    remittance_val = df.select(C.remittance).item(0, 0)
    
    assert isinstance(remittance_val, str)
    assert remittance_val == "part1 part2"

def test_remittance_normalization_and_warning(caplog):
    import logging
    tm = TransactionManager()

    # Case 1: Just Unstructured String
    tx_str = {
        "internalTransactionId": "tx_str",
        "remittanceInformationUnstructured": "simple string"
    }
    assert tm._get_remittance(tx_str) == "simple string"

    # Case 2: Both (should warn)
    tx_both = {
        "internalTransactionId": "tx_both",
        "remittanceInformationUnstructured": "simple string",
        "remittanceInformationUnstructuredArray": ["part1", "part2"]
    }
    
    with caplog.at_level(logging.WARNING):
        rem = tm._get_remittance(tx_both)
        # It prefers array if both are present based on implementation order, 
        # but we just want to ensure it warns.
        assert "violates the assumption" in caplog.text
        # Based on implementation: returns array joined
        assert rem == "part1 part2" 


def test_resolve_transaction_pattern_matching_with_array():
    # Verify that pattern matching works with the normalized remittance string.
    
    tm = TransactionManager()
    # Add a pattern that matches the joined remittance
    tm.add_pattern("part1 part2", "Clean Name", "Test Category", field="remittance")
    
    tx = {
        "internalTransactionId": "tx1",
        "remittanceInformationUnstructuredArray": ["part1", "part2"],
        "transactionAmount": {"amount": "100.00", "currency": "GBP"}
    }
    
    result = tm.resolve_transaction(tx)
    
    assert result["source"] == "PATTERN"
    assert result["clean_name"] == "Clean Name"
