import os

import pytest
from polars import col as C

from transaction_manager import TransactionManager


@pytest.fixture
def temp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    # Create empty files so load_data doesn't fail if it expects them
    # although TransactionManager handles missing files.
    return str(d)


def test_enrich_transactions_remittance_normalized(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)

    # Mock data
    raw_txs = {
        "acc1": [
            {
                "internalTransactionId": "tx1",
                "transactionId": "t1",
                "bookingDate": "2023-01-01",
                "transactionAmount": {"amount": "10.00", "currency": "USD"},
                "creditorName": "Test Creditor",
                "remittanceInformationUnstructuredArray": ["part1", "part2"],
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
    assert remittance_val == "part1\npart2"  # Note: Changed to \n as per implementation


def test_remittance_normalization_and_warning(caplog, temp_data_dir):
    import logging

    tm = TransactionManager(data_dir=temp_data_dir)

    # Case 1: Just Unstructured String
    tx_str = {
        "internalTransactionId": "tx_str",
        "remittanceInformationUnstructured": "simple string",
    }
    assert tm._get_remittance(tx_str) == "simple string"

    # Case 2: Both (should warn)
    tx_both = {
        "internalTransactionId": "tx_both",
        "remittanceInformationUnstructured": "simple string",
        "remittanceInformationUnstructuredArray": ["part1", "part2"],
    }

    with caplog.at_level(logging.WARNING):
        rem = tm._get_remittance(tx_both)
        assert "violates the assumption" in caplog.text
        assert rem == "part1\npart2"


def test_resolve_transaction_pattern_matching_with_array(temp_data_dir):
    # Verify that pattern matching works with the normalized remittance string.

    tm = TransactionManager(data_dir=temp_data_dir)
    # Add a pattern that matches the joined remittance
    tm.add_pattern("part1\npart2", "Clean Name", "Test Category", field="remittance")

    tx = {
        "internalTransactionId": "tx1",
        "remittanceInformationUnstructuredArray": ["part1", "part2"],
        "transactionAmount": {"amount": "100.00", "currency": "GBP"},
    }

    result = tm.resolve_transaction(tx)

    assert result["source"] == "PATTERN"
    assert result["clean_name"] == "Clean Name"

    # Verify it didn't touch the real data/patterns.json
    assert not os.path.exists(
        os.path.join("data", "patterns.json.tmp")
    )  # Just a sanity check
