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

    # 1. Match
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

    # 2. Differ
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

    # 3. Counterparty in Remittance (use longer)
    tx_cp_sub = Transaction(
        account_id="acc1",
        id="tx3",
        booking_date=date(2023, 1, 1),
        amount=30.0,
        currency="USD",
        counterparty="AMZN",
        remittance="AMZN MKTP",
        unmapped="{}",
    )

    # 4. Remittance in Counterparty (use longer)
    tx_rm_sub = Transaction(
        account_id="acc1",
        id="tx4",
        booking_date=date(2023, 1, 1),
        amount=40.0,
        currency="USD",
        counterparty="STARBUCKS LONDON",
        remittance="STARBUCKS",
        unmapped="{}",
    )

    # 5. Counterparty missing (use remittance)
    tx_cp_miss = Transaction(
        account_id="acc1",
        id="tx5",
        booking_date=date(2023, 1, 1),
        amount=50.0,
        currency="USD",
        counterparty="",
        remittance="ONLY REMITTANCE",
        unmapped="{}",
    )

    # 6. Remittance missing (remittance becomes None)
    tx_rm_miss = Transaction(
        account_id="acc1",
        id="tx6",
        booking_date=date(2023, 1, 1),
        amount=60.0,
        currency="USD",
        counterparty="ONLY COUNTERPARTY",
        remittance="",
        unmapped="{}",
    )

    # 7. Both missing
    tx_both_miss = Transaction(
        account_id="acc1",
        id="tx7",
        booking_date=date(2023, 1, 1),
        amount=70.0,
        currency="USD",
        counterparty="",
        remittance="",
        unmapped="{}",
    )

    df = tm.enrich_transactions(
        [tx_match, tx_diff, tx_cp_sub, tx_rm_sub, tx_cp_miss, tx_rm_miss, tx_both_miss]
    )

    # 1. Match -> remittance None
    assert df.filter(C.id == "tx1").select(C.remittance).item(0, 0) is None
    assert df.filter(C.id == "tx1").select(C.counterparty).item(0, 0) == "STARBUCKS"

    # 2. Diff -> Both kept
    assert df.filter(C.id == "tx2").select(C.remittance).item(0, 0) == "COFFEE"
    assert df.filter(C.id == "tx2").select(C.counterparty).item(0, 0) == "STARBUCKS"

    # 3. cp in rm -> cp becomes rm, rm becomes None
    assert df.filter(C.id == "tx3").select(C.counterparty).item(0, 0) == "AMZN MKTP"
    assert df.filter(C.id == "tx3").select(C.remittance).item(0, 0) is None

    # 4. rm in cp -> cp stays, rm becomes None
    assert df.filter(C.id == "tx4").select(C.counterparty).item(0, 0) == "STARBUCKS LONDON"
    assert df.filter(C.id == "tx4").select(C.remittance).item(0, 0) is None

    # 5. cp missing -> cp becomes "ONLY REMITTANCE", rm becomes None
    assert df.filter(C.id == "tx5").select(C.counterparty).item(0, 0) == "ONLY REMITTANCE"
    assert df.filter(C.id == "tx5").select(C.remittance).item(0, 0) is None

    # 6. rm missing -> rm becomes None
    assert df.filter(C.id == "tx6").select(C.counterparty).item(0, 0) == "ONLY COUNTERPARTY"
    assert df.filter(C.id == "tx6").select(C.remittance).item(0, 0) is None

    # 7. Both missing -> Both None
    assert df.filter(C.id == "tx7").select(C.counterparty).item(0, 0) is None
    assert df.filter(C.id == "tx7").select(C.remittance).item(0, 0) is None


def test_enrich_warning_on_empty_fields(temp_data_dir, caplog):
    tm = TransactionManager(data_dir=temp_data_dir)
    tx = Transaction(
        account_id="acc1",
        id="tx_empty",
        booking_date=date(2023, 1, 1),
        amount=10.0,
        currency="USD",
        counterparty="",
        remittance="",
        unmapped="{}",
    )

    import logging

    with caplog.at_level(logging.WARNING):
        tm.enrich_transactions([tx])

    assert "Transaction tx_empty has no counterparty or remittance data." in caplog.text
