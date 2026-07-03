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
        "source": "AI_AGENT",
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


def test_transfer_detection(temp_data_dir, monkeypatch):
    monkeypatch.setenv("TRANSFER_NAME", "TEST USER")
    tm = TransactionManager(data_dir=temp_data_dir)

    # Valid Transfer Pair
    tx1 = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2025, 4, 18),
        time_of_day=time(0, 0),
        amount=-1000.0,
        currency="GBP",
        counterparty="TEST USER TO REVOLUT",
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
        counterparty="FROM TEST USER",
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
        counterparty="TEST USER",
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
        counterparty="TEST USER",
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

    assert res1["source"] == "TRANSFER"
    assert res1["category"] == "Transfers > Matched"
    assert res1["clean_name"] == "Internal Transfer"

    assert res2["source"] == "TRANSFER"
    assert res2["category"] == "Transfers > Matched"
    assert res2["clean_name"] == "Internal Transfer"

    # Should not be transfer
    assert res3["source"] is None or res3["source"] != "TRANSFER"
    assert res4["source"] is None or res4["source"] != "TRANSFER"

    # Same account should not match
    assert res5["source"] is None or res5["source"] != "TRANSFER"


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


def test_pattern_matching_with_time_filters(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    
    # Lunch: 11:30 - 15:00
    tm.patterns.append({
        "pattern": "McDonalds",
        "clean_name": "McDonalds Lunch",
        "category": "Food & Drink > Lunch",
        "min_time": "11:30",
        "max_time": "15:00"
    })
    
    # Dinner: 18:00 - 22:00
    tm.patterns.append({
        "pattern": "McDonalds",
        "clean_name": "McDonalds Dinner",
        "category": "Food & Drink > Dinner",
        "min_time": "18:00",
        "max_time": "22:00"
    })

    # Lunch Match
    tx_lunch = Transaction(
        id="tx_l", account_id="acc1", booking_date=date(2023, 1, 1),
        time_of_day=time(13, 30), amount=-10.0, currency="GBP",
        counterparty="MCDONALDS", remittance="ref", unmapped="{}"
    )
    
    # Dinner Match
    tx_dinner = Transaction(
        id="tx_d", account_id="acc1", booking_date=date(2023, 1, 1),
        time_of_day=time(19, 0), amount=-15.0, currency="GBP",
        counterparty="MCDONALDS", remittance="ref", unmapped="{}"
    )
    
    # No Match (Night snack)
    tx_night = Transaction(
        id="tx_n", account_id="acc1", booking_date=date(2023, 1, 1),
        time_of_day=time(23, 30), amount=-5.0, currency="GBP",
        counterparty="MCDONALDS", remittance="ref", unmapped="{}"
    )

    res_l = tm.resolve_transaction(tx_lunch)
    res_d = tm.resolve_transaction(tx_dinner)
    res_n = tm.resolve_transaction(tx_night)

    assert res_l["clean_name"] == "McDonalds Lunch"
    assert res_l["category"] == "Food & Drink > Lunch"
    
    assert res_d["clean_name"] == "McDonalds Dinner"
    assert res_d["category"] == "Food & Drink > Dinner"
    
    assert res_n["clean_name"] is None


# --- patterns.json validation on load ---


def _write_patterns(tmp_path, grouped_data):
    import json

    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    with open(d / "patterns.json", "w") as f:
        json.dump(grouped_data, f)
    return str(d)


def test_load_rejects_pattern_missing_pattern_key(tmp_path):
    d = _write_patterns(
        tmp_path, {"Bills > Utilities": [{"regex": "Gas", "clean_name": "Gas Co"}]}
    )
    with pytest.raises(ValueError, match="Bills > Utilities"):
        TransactionManager(data_dir=d)


def test_load_rejects_empty_pattern(tmp_path):
    d = _write_patterns(
        tmp_path, {"Bills > Utilities": [{"pattern": "", "clean_name": "Gas Co"}]}
    )
    with pytest.raises(ValueError, match="Bills > Utilities"):
        TransactionManager(data_dir=d)


def test_load_rejects_invalid_regex(tmp_path):
    d = _write_patterns(
        tmp_path, {"Bills > Utilities": [{"pattern": "(gas", "clean_name": "Gas Co"}]}
    )
    with pytest.raises(ValueError, match="Bills > Utilities"):
        TransactionManager(data_dir=d)


def test_load_rejects_unknown_field_value(tmp_path):
    d = _write_patterns(
        tmp_path,
        {"Bills > Utilities": [{"pattern": "gas", "field": "Remittance"}]},
    )
    with pytest.raises(ValueError, match="Bills > Utilities"):
        TransactionManager(data_dir=d)


def test_load_rejects_non_numeric_amount_bound(tmp_path):
    d = _write_patterns(
        tmp_path,
        {"Bills > Utilities": [{"pattern": "gas", "min_amount": "cheap"}]},
    )
    with pytest.raises(ValueError, match="Bills > Utilities"):
        TransactionManager(data_dir=d)


def test_load_rejects_unparseable_time_bound(tmp_path):
    d = _write_patterns(
        tmp_path,
        {"Bills > Utilities": [{"pattern": "gas", "min_time": "6pm"}]},
    )
    with pytest.raises(ValueError, match="Bills > Utilities"):
        TransactionManager(data_dir=d)


def test_load_accepts_valid_patterns_with_numeric_string_bounds(tmp_path):
    d = _write_patterns(
        tmp_path,
        {
            "Bills > Utilities": [
                {
                    "pattern": "gas",
                    "clean_name": "Gas Co",
                    "field": "any",
                    "min_amount": "5",
                    "max_time": "23:00",
                }
            ]
        },
    )
    tm = TransactionManager(data_dir=d)
    assert len(tm.patterns) == 1


def test_load_rejects_non_dict_llm_cache_entry(tmp_path):
    import json

    d = tmp_path / "data"
    d.mkdir()
    with open(d / "llm_cache.json", "w") as f:
        json.dump({"tx_abc": "just a string"}, f)
    with pytest.raises(ValueError, match="tx_abc"):
        TransactionManager(data_dir=str(d))


# --- save_data atomicity ---


def test_failed_save_leaves_existing_files_intact(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.categories = ["Bills > Utilities"]
    tm.patterns = [
        {"pattern": "gas", "clean_name": "Gas Co", "category": "Bills > Utilities"}
    ]
    tm.llm_cache = {"tx1": {"clean_name": "Gas Co", "category": "Bills > Utilities"}}
    tm.save_data()

    # Sabotage: an unserializable object makes json.dump raise mid-write
    tm.llm_cache = {"tx1": object()}  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        tm.save_data()

    # The previously saved state must survive the failed save
    tm2 = TransactionManager(data_dir=temp_data_dir)
    assert tm2.llm_cache == {
        "tx1": {"clean_name": "Gas Co", "category": "Bills > Utilities"}
    }
    assert len(tm2.patterns) == 1


def test_save_load_round_trip_preserves_patterns_and_empty_categories(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.categories = ["Bills > Utilities", "Food & Drink > Groceries"]
    tm.patterns = [
        {"pattern": "gas", "clean_name": "Gas Co", "category": "Bills > Utilities"}
    ]
    tm.save_data()

    tm2 = TransactionManager(data_dir=temp_data_dir)
    assert tm2.patterns == tm.patterns
    # Empty categories must survive the round-trip (they define the master list)
    assert tm2.categories == ["Bills > Utilities", "Food & Drink > Groceries"]


# --- transfer-detection state + priority competition ---


def _tx(id="tx1", account="acc1", amount=100.0, counterparty="Test Shop"):
    return Transaction(
        id=id,
        account_id=account,
        booking_date=date(2023, 1, 1),
        time_of_day=time(12, 0),
        amount=amount,
        currency="GBP",
        counterparty=counterparty,
        remittance=None,
        unmapped="{}",
    )


def test_warns_when_resolving_without_transfer_detection(temp_data_dir, caplog):
    tm = TransactionManager(data_dir=temp_data_dir)
    with caplog.at_level(logging.WARNING):
        tm.resolve_transaction(_tx())
    assert "detect_transfers" in caplog.text


def test_no_warning_once_transfers_detected(temp_data_dir, caplog):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.detect_transfers([])
    with caplog.at_level(logging.WARNING):
        tm.resolve_transaction(_tx())
    assert "detect_transfers" not in caplog.text


def test_manual_beats_pattern_and_cache(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.detect_transfers([])
    tm.categories = ["A", "B", "C"]
    tm.manual_assignments = {"tx1": {"clean_name": "M", "category": "A"}}
    tm.patterns = [{"pattern": "Test", "clean_name": "P", "category": "B"}]
    tm.llm_cache = {"tx1": {"clean_name": "AI", "category": "C"}}

    result = tm.resolve_transaction(_tx())
    assert result["source"] == "MANUAL"
    assert result["category"] == "A"


def test_transfer_beats_pattern_and_cache(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.categories = ["B", "C", "Transfers > Matched"]
    tm.patterns = [{"pattern": "BLOGGS", "clean_name": "P", "category": "B"}]
    tm.llm_cache = {"out": {"clean_name": "AI", "category": "C"}}
    legs = [
        _tx(id="out", account="acc1", amount=-50.0, counterparty="J BLOGGS"),
        _tx(id="in", account="acc2", amount=50.0, counterparty="J BLOGGS"),
    ]
    import os

    os.environ["TRANSFER_NAME"] = "BLOGGS"
    tm.detect_transfers(legs)

    result = tm.resolve_transaction(legs[0])
    assert result["source"] == "TRANSFER"


def test_zero_amount_beats_pattern_and_cache(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.detect_transfers([])
    tm.categories = ["B", "C", "Excluded"]
    tm.patterns = [{"pattern": "Test", "clean_name": "P", "category": "B"}]
    tm.llm_cache = {"tx1": {"clean_name": "AI", "category": "C"}}

    result = tm.resolve_transaction(_tx(amount=0.0))
    assert result["source"] == "ZERO_AMOUNT"
    assert result["category"] == "Excluded"


def test_pattern_beats_cache(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.detect_transfers([])
    tm.categories = ["B", "C"]
    tm.patterns = [{"pattern": "Test", "clean_name": "P", "category": "B"}]
    tm.llm_cache = {"tx1": {"clean_name": "AI", "category": "C"}}

    result = tm.resolve_transaction(_tx())
    assert result["source"] == "PATTERN"
    assert result["category"] == "B"


def test_cache_used_when_nothing_else_matches(temp_data_dir):
    tm = TransactionManager(data_dir=temp_data_dir)
    tm.detect_transfers([])
    tm.categories = ["C"]
    tm.llm_cache = {"tx1": {"clean_name": "AI", "category": "C"}}

    result = tm.resolve_transaction(_tx())
    assert result["source"] == "AI_AGENT"
    assert result["category"] == "C"
