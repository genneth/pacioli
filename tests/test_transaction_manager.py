from datetime import date

import pytest
from polars import col as C

from transaction_loader import Transaction
from transaction_manager import TransactionManager


@pytest.fixture
def temp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


def test_enrich_transactions_structure(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)

    # Mock data using Transaction object
    tx = Transaction(
        account_id="acc1",
        id="tx1",
        booking_date=date(2023, 1, 1),
        amount=10.0,
        currency="USD",
        counterparty="Test Creditor",
        remittance="part1\npart2",
        unmapped="{}",
    )

    # enrich
    df = tm.enrich_transactions([tx])

    assert "counterparty" in df.columns
    assert "clean_name" in df.columns
    assert df.select(C.counterparty).item(0, 0) == "Test Creditor"
    assert df.select(C.remittance).item(0, 0) == "part1\npart2"


def test_resolve_transaction_pattern_matching(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    # Add a pattern that matches the joined remittance
    tm.add_pattern("part1\npart2", "Clean Name", "Test Category", field="remittance")

    tx = Transaction(
        account_id="acc1",
        id="tx1",
        booking_date=date(2023, 1, 1),
        amount=100.0,
        currency="GBP",
        counterparty="Unknown",
        remittance="part1\npart2",
        unmapped="{}",
    )

    result = tm.resolve_transaction(tx)

    assert result["source"] == "PATTERN"
    assert result["clean_name"] == "Clean Name"


def test_manual_override(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.update_manual("tx1", "Manual Name", "Manual Cat")

    tx = Transaction(
        account_id="acc1",
        id="tx1",
        booking_date=date(2023, 1, 1),
        amount=100.0,
        currency="GBP",
        counterparty="Unknown",
        remittance="Unknown",
        unmapped="{}",
    )

    result = tm.resolve_transaction(tx)
    assert result["source"] == "MANUAL"
    assert result["clean_name"] == "Manual Name"


def test_zero_amount(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tx = Transaction(
        account_id="acc1",
        id="tx_zero",
        booking_date=date(2023, 1, 1),
        amount=0.0,
        currency="GBP",
        counterparty="Unknown",
        remittance="Unknown",
        unmapped="{}",
    )

    result = tm.resolve_transaction(tx)
    assert result["source"] == "ZERO_AMOUNT"


def test_remittance_deduplication(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)

    # Case where they match
    tx_match = Transaction(
        account_id="acc1",
        id="tx1",
        booking_date=date(2023, 1, 1),
        amount=10.0,
        currency="USD",
        counterparty="STARBUCKS",
        remittance="STARBUCKS",
        unmapped="{}",
    )

    # Case where they differ
    tx_diff = Transaction(
        account_id="acc1",
        id="tx2",
        booking_date=date(2023, 1, 1),
        amount=20.0,
        currency="USD",
        counterparty="STARBUCKS",
        remittance="COFFEE",
        unmapped="{}",
    )

    df = tm.enrich_transactions([tx_match, tx_diff])

    # Row 0: match -> remittance should be None
    assert df.filter(C.id == "tx1").select(C.remittance).item(0, 0) is None
    # Row 1: diff -> remittance should be "COFFEE"
    assert df.filter(C.id == "tx2").select(C.remittance).item(0, 0) == "COFFEE"
