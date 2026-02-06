import logging
from datetime import date, time

import pytest
from polars import col as C

from transaction_loader import Transaction
from transaction_manager import TransactionManager


def test_unknown_category_warning(temp_data_dir, caplog):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.categories = ["Groceries"]  # Only Groceries is allowed

    # Patterns without a known category now default to 'Uncategorized' during loading
    # or are explicitly assigned via the grouped JSON key.
    # Here we test the resolve logic warning for a non-existent category.
    tm.patterns = [{
        "pattern": "Test",
        "clean_name": "Test Name",
        "category": "Unknown Category",
    }]

    tx = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=100.0,
        currency="GBP",
        counterparty="Test",
        remittance="ref",
        unmapped="{}",
    )

    with caplog.at_level(logging.WARNING):
        tm.resolve_transaction(tx)

    assert "resolved to unknown category 'Unknown Category'" in caplog.text


def test_load_data_grouped_format(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    patterns_file = d / "patterns.json"
    
    grouped_data = {
        "Food & Drink > Restaurants": [
            {"pattern": "Resto", "clean_name": "Restaurant"}
        ],
        "Bills > Utilities": [
            {"pattern": "Gas", "clean_name": "Gas Co"}
        ]
    }
    import json
    with open(patterns_file, "w") as f:
        json.dump(grouped_data, f)
        
    tm = TransactionManager(data_dir=str(d))
    
    assert len(tm.patterns) == 2
    assert "Food & Drink > Restaurants" in tm.categories
    assert "Bills > Utilities" in tm.categories
    # Verify flattening and category assignment
    p1 = next(p for p in tm.patterns if p["clean_name"] == "Restaurant")
    assert p1["category"] == "Food & Drink > Restaurants"
    p2 = next(p for p in tm.patterns if p["clean_name"] == "Gas Co")
    assert p2["category"] == "Bills > Utilities"


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
    tm.patterns.append({
        "pattern": "part1\npart2",
        "clean_name": "Clean Name",
        "category": "Test Category",
        "field": "remittance"
    })

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
    tm.manual_assignments["tx1"] = {
        "clean_name": "Manual Name",
        "category": "Manual Cat",
    }

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
    tm.manual_assignments[tx_id] = {
        "clean_name": "Manual Name",
        "category": "Manual Category",
    }

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


def test_transfer_detection(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)

    # Valid Transfer Pair
    tx1 = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2025, 4, 18),
        time_of_day=time(0, 0),
        amount=-1000.0,
        currency="GBP",
        counterparty="GEN SMITH TO REVOLUT",
        remittance="Transfer",
        unmapped="{}",
    )
    tx2 = Transaction(
        id="tx2",
        account_id="acc2",
        booking_date=date(2025, 4, 18),
        time_of_day=time(0, 0),
        amount=1000.0,
        currency="GBP",
        counterparty="FROM GEN SMITH",
        remittance="Topup",
        unmapped="{}",
    )

    # Invalid Transfer (No Name)
    tx3 = Transaction(
        id="tx3",
        account_id="acc1",
        booking_date=date(2025, 4, 20),
        time_of_day=time(0, 0),
        amount=-50.0,
        currency="GBP",
        counterparty="Netflix",
        remittance="Sub",
        unmapped="{}",
    )
    tx4 = Transaction(
        id="tx4",
        account_id="acc2",
        booking_date=date(2025, 4, 20),
        time_of_day=time(0, 0),
        amount=50.0,
        currency="GBP",
        counterparty="Netflix",
        remittance="Sub",
        unmapped="{}",
    )

    # Invalid Transfer (Same Account)
    tx5 = Transaction(
        id="tx5",
        account_id="acc1",
        booking_date=date(2025, 4, 25),
        time_of_day=time(0, 0),
        amount=-200.0,
        currency="GBP",
        counterparty="GEN SMITH",
        remittance="Self",
        unmapped="{}",
    )
    tx6 = Transaction(
        id="tx6",
        account_id="acc1",
        booking_date=date(2025, 4, 25),
        time_of_day=time(0, 0),
        amount=200.0,
        currency="GBP",
        counterparty="GEN SMITH",
        remittance="Self",
        unmapped="{}",
    )

    transactions = [tx1, tx2, tx3, tx4, tx5, tx6]

    # Process
    df = tm.enrich_transactions(transactions)

    # Check results
    res1 = (
        df.filter(C.id == "tx1")
        .select("source", "category", "clean_name")
        .to_dicts()[0]
    )
    res2 = (
        df.filter(C.id == "tx2")
        .select("source", "category", "clean_name")
        .to_dicts()[0]
    )
    res3 = df.filter(C.id == "tx3").select("source").to_dicts()[0]
    res4 = df.filter(C.id == "tx4").select("source").to_dicts()[0]
    res5 = df.filter(C.id == "tx5").select("source").to_dicts()[0]

    assert res1["source"] == "TRANSFER_MATCH"
    assert res1["category"] == "Transfers > Matched"
    assert res1["clean_name"] == "Internal Transfer"

    assert res2["source"] == "TRANSFER_MATCH"
    assert res2["category"] == "Transfers > Matched"
    assert res2["clean_name"] == "Internal Transfer"

    # Should not be transfer
    assert res3["source"] is None or res3["source"] != "TRANSFER_MATCH"
    assert res4["source"] is None or res4["source"] != "TRANSFER_MATCH"

    # Same account should not match
    assert res5["source"] is None or res5["source"] != "TRANSFER_MATCH"


def test_pattern_matching_with_filters(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    
    # Define a pattern with amount and day filters
    tm.patterns.append({
        "pattern": "Alimony",
        "clean_name": "Alimony Payment",
        "category": "Transfers > Alimony",
        "min_amount": 3000,
        "min_day": 25
    })

    # tx1 matches all criteria
    tx1 = Transaction(
        id="tx1", account_id="acc1", booking_date=date(2023, 1, 27),
        time_of_day=time(0, 0), amount=-3500.0, currency="GBP",
        counterparty="Alimony Test", remittance="ref", unmapped="{}"
    )
    
    # tx2 matches regex but too small amount
    tx2 = Transaction(
        id="tx2", account_id="acc1", booking_date=date(2023, 1, 27),
        time_of_day=time(0, 0), amount=-500.0, currency="GBP",
        counterparty="Alimony Test", remittance="ref", unmapped="{}"
    )
    
    # tx3 matches regex but too early in month
    tx3 = Transaction(
        id="tx3", account_id="acc1", booking_date=date(2023, 1, 10),
        time_of_day=time(0, 0), amount=-3500.0, currency="GBP",
        counterparty="Alimony Test", remittance="ref", unmapped="{}"
    )

    assert tm.resolve_transaction(tx1)["clean_name"] == "Alimony Payment"
    assert tm.resolve_transaction(tx2)["clean_name"] is None
    assert tm.resolve_transaction(tx3)["clean_name"] is None

    # Test max filters too
    tm.patterns = [{
        "pattern": "Expenses",
        "clean_name": "Reimbursement",
        "category": "Income > Expenses",
        "max_amount": 500,
        "max_day": 15
    }]
    
    # tx4 matches max filters
    tx4 = Transaction(
        id="tx4", account_id="acc1", booking_date=date(2023, 1, 10),
        time_of_day=time(0, 0), amount=100.0, currency="GBP",
        counterparty="Expenses Test", remittance="ref", unmapped="{}"
    )
    
    # tx5 fails max_amount
    tx5 = Transaction(
        id="tx5", account_id="acc1", booking_date=date(2023, 1, 10),
        time_of_day=time(0, 0), amount=600.0, currency="GBP",
        counterparty="Expenses Test", remittance="ref", unmapped="{}"
    )
    
    # tx6 fails max_day
    tx6 = Transaction(
        id="tx6", account_id="acc1", booking_date=date(2023, 1, 20),
        time_of_day=time(0, 0), amount=100.0, currency="GBP",
        counterparty="Expenses Test", remittance="ref", unmapped="{}"
    )

    assert tm.resolve_transaction(tx4)["clean_name"] == "Reimbursement"
    assert tm.resolve_transaction(tx5)["clean_name"] is None
    assert tm.resolve_transaction(tx6)["clean_name"] is None
