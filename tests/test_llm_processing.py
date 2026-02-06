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
def mock_genai():
    mock = MagicMock()
    # Mock the chain: client.models.generate_content().parsed
    response_mock = MagicMock()
    response_mock.parsed = CategorizationResponse(
        transactions=[
            TransactionResult(
                id="tx1",
                clean_name="Clean TX1",
                category="Groceries",
                category_reason="Known grocery store",
            )
        ]
    )
    mock.models.generate_content.return_value = response_mock
    return mock


def test_batch_process_llm_flow(temp_data_dir, mock_genai):
    tm = TransactionManager(genai_client=mock_genai, data_dir=temp_data_dir)
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
    mock_genai.models.generate_content.assert_called_once()

    # Verify the prompt contains tx1 but NOT tx2
    call_args = mock_genai.models.generate_content.call_args
    kwargs = call_args.kwargs
    prompt = kwargs["contents"]

    assert "ID: tx1" in prompt
    assert "Store A" in prompt
    assert "ID: tx2" not in prompt

    # Check if cache was updated
    assert "tx1" in tm.llm_cache
    assert tm.llm_cache["tx1"]["clean_name"] == "Clean TX1"
    assert tm.llm_cache["tx1"]["category"] == "Groceries"


def test_batch_process_llm_force_update(temp_data_dir, mock_genai):
    tm = TransactionManager(genai_client=mock_genai, data_dir=temp_data_dir)
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
    mock_genai.models.generate_content.assert_not_called()

    # Call WITH force_update -> SHOULD call LLM
    tm.batch_process_llm([tx1], force_update=True)
    mock_genai.models.generate_content.assert_called_once()
