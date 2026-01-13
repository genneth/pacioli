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
    assert res1["category"] == "Transfer"
    assert res1["clean_name"] == "Internal Transfer"

    assert res2["source"] == "TRANSFER_MATCH"
    assert res2["category"] == "Transfer"
    assert res2["clean_name"] == "Internal Transfer"

    # Should not be transfer
    assert res3["source"] is None or res3["source"] != "TRANSFER_MATCH"
    assert res4["source"] is None or res4["source"] != "TRANSFER_MATCH"

    # Same account should not match
    assert res5["source"] is None or res5["source"] != "TRANSFER_MATCH"
