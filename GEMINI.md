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
        4.  **LLM Classification** (`data/llm_cache.json` via Gemini)
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

## Transaction Manager Actions
The `TransactionManager` class in `transaction_manager.py` provides the following core actions:

*   **`enrich_transactions(transactions)`**: The primary pipeline. Takes a list of raw transactions and returns a categorized Polars DataFrame, applying the hierarchy (Manual > Transfer > Zero > Pattern > AI).
*   **`batch_process_llm(transactions)`**: Identifies transactions that haven't been categorized by other means and sends them to Gemini for AI classification. Updates the local `llm_cache.json`.
*   **`detect_transfers(transactions)`**: Scans for matching transaction pairs (opposite amounts, nearby dates, user name in description) and marks them as "Internal Transfers".
*   **`test_pattern(transactions, pattern, field)`**: Dry-run a regex pattern against a set of transactions to see what it would match before saving it.
*   **`purge_override_cache(transactions)`**: Optimizes storage by removing LLM cache entries for transactions that are now covered by more deterministic rules (Manual, Pattern, etc.).
*   **`explain_transaction(tx)`**: Provides a detailed diagnostic trace of how a specific transaction would be resolved, showing all matching rules and the final selection.

## Setup & Usage

### Prerequisites
*   Python 3.13+
*   `uv` (Universal Python Package Installer)
*   GoCardless Account (Bank Account Data API)
*   Google API Key (Gemini)

### Environment Variables (`.env`)
```toml
GOCARDLESS_SECRET_ID = "..."
GOCARDLESS_SECRET_KEY = "..."
GOOGLE_API_KEY = "..."
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
*   **Testing:** `pytest` is used for unit tests. Tests are located in `tests/`. Best to use `uv run python -m pytest` instead of just `uv run pytest` to make all the paths Just Work.
*   **Comments:** do not add comments which are just restating what the code is doing. Only add comments that explain _why_, and document assumptions and why the assumptions are justified.

## Ops Skill
The project includes a specialized `ops` skill for managing the transaction pipeline.

**Location:** `.gemini/skills/ops/SKILL.md`

**Core Workflows:**
1.  **Sync Transactions:** `uv run update_transactions.py` - Fetches new data from GoCardless.
2.  **Enrich Transactions:** `uv run enrich_transactions.py` - Loads, deduplicates, and categorizes transactions.
    - Uses `tqdm` for progress monitoring.
    - Outputs a summary of categorization sources (`PATTERN`, `AI_CACHED`, `TRANSFER_MATCH`, etc.).
    - Highlights uncategorized transactions for review.
3.  **Prune LLM Cache:** `uv run prune_cache.py <tx_id> ...` - Removes specific transactions from `llm_cache.json` to force re-evaluation.

**Key Categories:**
- `Transfers > Matched`: Internal transfers identified by matching amounts, dates, and names.
- `Transfers > Internal`: (Legacy/Alternative)