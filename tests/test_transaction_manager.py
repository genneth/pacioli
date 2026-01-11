import pytest
import polars as pl
from polars import col as C
from transaction_manager import TransactionManager

def test_enrich_transactions_remittance_is_list():
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
    
    # check remittance type
    remittance_val = df.select(C.remittance).item(0, 0)
    
    # Polars might return a Series for List type cells
    if isinstance(remittance_val, pl.Series):
        remittance_val = remittance_val.to_list()
    
    assert isinstance(remittance_val, list)
    assert remittance_val == ["part1", "part2"]

def test_resolve_transaction_pattern_matching_with_array():
    # Verify that pattern matching still works even though enrich_transactions returns a list,
    # because resolve_transaction handles the join internally.
    
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
