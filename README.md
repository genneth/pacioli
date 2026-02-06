# Pacioli

![Luca Pacioli](https://commons.wikimedia.org/wiki/File:Luca_Pacioli_in_the_Summa.jpg#/media/File:Luca_Pacioli_in_the_Summa.jpg)

[Luca Pacioli](https://en.wikipedia.org/wiki/Luca_Pacioli) is widely regarded as the father of
accounting.

This project is bare-bones spending tracker, using Open Banking APIs, and semi-automated classification via LLMs.
Primary UX are through command lines that need manual set up for cron/repetition, and janky UI
through Jupyter notebooks. 🧑‍🍳😘

Open Banking API is accessed through GoCardless (https://gocardless.com/) so you have to set up
an account there (dev + personal use is free), and sort out an API key. There is a python client
(https://github.com/gocardless/gocardless-pro-python) but it's a bit complex so this implements
a bare-bones API through `requests`.

In order to maintain history of transactions and update them, there is a need to maintain state.
This is effectively kept between GoCardless (through its requisitions and accounts API), and raw
dumps of the bank-provided json (in json files within the `raw` directory) -- with the inner
directory name mapping to the GoCardless account id and therefore linking everything together.

### Environment Variables (`.env`)
```toml
GOCARDLESS_SECRET_ID = "..."
GOCARDLESS_SECRET_KEY = "..."
GOOGLE_API_KEY = "..."
```

## Operational Workflows (Gemini CLI)

The project is designed to be managed via the **Gemini CLI** using the `ops` skill. This provides a streamlined interface for the data pipeline and categorization maintenance.

### Key Workflows
- **Sync & Categorize**: `update transactions` -> Fetches new data and runs enrichment.
- **Pattern Maintenance**:
    - `uv run lint_patterns.py`: Find dead or overlapping rules.
    - `uv run cleanup_cache.py`: Remove AI cache entries covered by new patterns.
    - `uv run enrich_transactions.py`: Re-run the categorization pipeline.
- **AI Labeling**: `uv run process_llm.py` -> Uses Gemini to label uncategorized transactions.

### Categorization Hierarchy
1. **Manual Overrides** (`data/manual_assignments.json`)
2. **Internal Transfers** (Auto-detected)
3. **Regex Patterns** (`data/patterns.json`)
4. **AI Cache** (`data/llm_cache.json`)