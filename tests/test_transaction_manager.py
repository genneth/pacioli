from datetime import date, time

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
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
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
    assert "time_of_day" in df.columns
    assert "tx_type" in df.columns
    assert df.select(C.counterparty).item(0, 0) == "Test Creditor"
    assert df.select(C.remittance).item(0, 0) == "part1\npart2"


def test_resolve_transaction_pattern_matching(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    # Add a pattern that matches the joined remittance
    tm.add_pattern("part1\npart2", "Clean Name", "Test Category", field="remittance")

    tx = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
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
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
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
        id="tx_zero",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=0.0,
        currency="GBP",
        counterparty="Unknown",
        remittance="Unknown",
        unmapped="{}",
    )
    result = tm.resolve_transaction(tx)
    assert result["source"] == "ZERO_AMOUNT"


def test_purge_override_cache(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)

    # 1. Setup a transaction
    tx_id = "tx_cached"
    tx = Transaction(
        id=tx_id,
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=50.0,
        currency="GBP",
        counterparty="Some Shop",
        remittance="Some Shop Remittance",
        unmapped="{}",
    )

    # 2. Add to LLM cache
    tm.llm_cache[tx_id] = {
        "clean_name": "Cached Name",
        "category": "Cached Category",
        "source": "AI_CACHED",
        "confidence": 0.8,
    }
    tm.save_data()

    # Verify it is in cache
    assert tx_id in tm.llm_cache

    # 3. Add manual override
    tm.update_manual(tx_id, "Manual Name", "Manual Category")

    # 4. Run purge
    tm.purge_override_cache([tx])

    # 5. Assert removed from cache
    assert tx_id not in tm.llm_cache


def test_test_pattern_returns_transactions(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tx1 = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=10.0,
        currency="USD",
        counterparty="Target Match",
        remittance="ref1",
        unmapped="{}",
    )
    tx2 = Transaction(
        id="tx2",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=20.0,
        currency="USD",
        counterparty="Other Store",
        remittance="ref2",
        unmapped="{}",
    )

    results = tm.test_pattern([tx1, tx2], "Match", field="counterparty")

    assert isinstance(results, list)
    assert len(results) == 1
    assert isinstance(results[0], Transaction)
    assert results[0].id == "tx1"
