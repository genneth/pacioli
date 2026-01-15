from datetime import date, time
from unittest.mock import MagicMock

import pytest

from transaction_loader import Transaction
from transaction_manager import (
    CategorizationResponse,
    TransactionManager,
    TransactionResult,
)


@pytest.fixture
def mock_oai():
    mock = MagicMock()
    # Mock the chain: client.chat.completions.parse
    # We need to simulate the response structure structure
    response_mock = MagicMock()
    response_mock.choices = [MagicMock()]
    response_mock.choices[0].message.parsed = CategorizationResponse(
        transactions=[
            TransactionResult(
                id="tx1",
                clean_name="Clean TX1",
                category="Groceries",
                category_reason="Known grocery store",
            )
        ]
    )
    mock.chat.completions.parse.return_value = response_mock
    return mock


@pytest.fixture
def temp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


def test_batch_process_llm_flow(temp_data_dir, mock_oai):
    tm = TransactionManager(oai_client=mock_oai, data_dir=temp_data_dir)
    tm.categories = ["Groceries", "Rent"]

    # tx1: Needs LLM (no match)
    tx1 = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=10.0,
        currency="USD",
        counterparty="Store A",
        remittance="Store A",
        unmapped="{}",
    )

    # tx2: Already manual (should be skipped)
    tm.manual_assignments["tx2"] = {"clean_name": "Manual", "category": "Rent"}
    tx2 = Transaction(
        id="tx2",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=1000.0,
        currency="USD",
        counterparty="Landlord",
        remittance="Rent",
        unmapped="{}",
    )

    tm.batch_process_llm([tx1, tx2])

    # Check if LLM was called
    mock_oai.chat.completions.parse.assert_called_once()

    # Verify the prompt contains tx1 but NOT tx2
    call_args = mock_oai.chat.completions.parse.call_args
    kwargs = call_args.kwargs
    messages = kwargs["messages"]
    user_content = messages[1]["content"]

    assert "ID: tx1" in user_content
    assert "Store A" in user_content
    assert "ID: tx2" not in user_content

    # Check if cache was updated
    assert "tx1" in tm.llm_cache
    assert tm.llm_cache["tx1"]["clean_name"] == "Clean TX1"
    assert tm.llm_cache["tx1"]["category"] == "Groceries"


def test_batch_process_llm_force_update(temp_data_dir, mock_oai):
    tm = TransactionManager(oai_client=mock_oai, data_dir=temp_data_dir)
    tm.categories = ["Groceries"]

    # tx1: Already cached
    tm.llm_cache["tx1"] = {"clean_name": "Old Name", "category": "Groceries"}

    tx1 = Transaction(
        id="tx1",
        account_id="acc1",
        booking_date=date(2023, 1, 1),
        time_of_day=time(0, 0),
        amount=10.0,
        currency="USD",
        counterparty="Store A",
        remittance="Store A",
        unmapped="{}",
    )

    # Call without force_update -> should NOT call LLM
    tm.batch_process_llm([tx1], force_update=False)
    mock_oai.chat.completions.parse.assert_not_called()

    # Call WITH force_update -> SHOULD call LLM
    tm.batch_process_llm([tx1], force_update=True)
    mock_oai.chat.completions.parse.assert_called_once()
