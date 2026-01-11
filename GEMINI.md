# Pacioli Project Context

## Overview
**Pacioli** is a personal finance tracking application named after Luca Pacioli, the father of accounting. It leverages Open Banking APIs (via GoCardless) to fetch transaction data and uses a hybrid approach (Regex + LLM) to categorize spending.

The core philosophy is **immutable raw data** combined with **derived state**. The raw JSON responses from the bank are stored permanently, and all categorization and analysis are computed on top of this ground truth.

## Architecture

### Data Pipeline
1.  **Ingestion (`update_transactions.py`):**
    *   Fetches data from GoCardless API.
    *   Writes **immutable** JSON files to `raw/<account_id>/<date>.json`.
    *   Uses an **overlapping fetch window** to ensure late-settling transactions are captured.
    *   **Idempotent:** Uses exclusive file creation (`x` mode) to prevent overwriting existing data.

2.  **Loading (`read_existing_transactions.py`):**
    *   Reads all JSON files from `raw/`.
    *   **Deduplicates** transactions based on `internalTransactionId`.
    *   Returns a dictionary of unique transactions per account.

3.  **Enrichment (`transaction_manager.py`):**
    *   Resolves categories using a priority hierarchy:
        1.  **Manual Overrides** (`data/manual_assignments.json`)
        2.  **Zero Amount Checks** (Ignored/Excluded)
        3.  **Regex Patterns** (`data/patterns.json`)
        4.  **LLM Classification** (`data/llm_cache.json` via OpenAI)
    *   Outputs a flat **Polars DataFrame**.

### Configuration
*   **Environment:** managed via `.env`.
*   **Data Storage:**
    *   `raw/`: Raw bank API dumps. **Do not modify manually.**
    *   `data/`: Configuration and cache files (patterns, categories, LLM cache).

## Key Files
*   **`update_transactions.py`**: The primary script to sync with the bank. Safe to run repeatedly.
*   **`transaction_manager.py`**: Contains the `TransactionManager` class which handles the business logic for categorization and LLM interaction.
*   **`go_cardless_client.py`**: A custom wrapper around the GoCardless Bank Account Data API (formerly Nordigen). Handles token management (`token.json`).
*   **`read_existing_transactions.py`**: Helper module to load and deduplicate raw data.

## Setup & Usage

### Prerequisites
*   Python 3.13+
*   `uv` (Universal Python Package Installer)
*   GoCardless Account (Bank Account Data API)
*   OpenAI API Key

### Environment Variables (`.env`)
```toml
GOCARDLESS_SECRET_ID = "..."
GOCARDLESS_SECRET_KEY = "..."
OPENAI_API_KEY = "..."
```

### Common Commands
All commands should be run using `uv` to ensure the correct environment and dependencies are used.

*   **Sync Data:**
    ```bash
    uv run update_transactions.py
    ```
*   **Run Tests:**
    ```bash
    uv run pytest
    ```
*   **Linting & Formatting:**
    ```bash
    uv run ruff check .
    ```
*   **Type Checking:**
    ```bash
    uv run mypy .
    ```

## Development Conventions
*   **Data Integrity:** Never modify files in `raw/` manually. If data needs to be fixed, use the `TransactionManager` to create a manual assignment or pattern override.
*   **Type Safety:** Uses `pydantic` for data validation and `mypy` for static analysis.
*   **Data Frames (Polars):**
    *   Import convention: `from polars import col as C`
    *   Column selection: Use property access `C.column_name` instead of function call `C("column_name")` whenever possible.
*   **Testing:** `pytest` is used for unit tests. Tests are located in `tests/`.