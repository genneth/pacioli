---
name: ops
description: Personal finance operations for Pacioli. Use this skill to sync transactions from bank APIs, audit AI categorizations against regex patterns, and manage the LLM-to-Regex pipeline.
---

# Ops

## Overview
This skill provides a set of operational workflows for managing Pacioli's financial data pipeline. It focuses on maintaining data integrity, syncing with bank APIs, and optimizing the transaction categorization process.

## Core Tasks

### 1. Sync Transactions
Syncs the local transaction store with the bank via the GoCardless API.

**Safety & Integrity Warnings:**
- **Finite History:** Most Open Banking APIs only provide 90 days of transaction history. If you have a gap larger than 90 days between your `max_date` and today, **data will be lost**. 
- **Immutable Raw Data:** The script writes to `raw/<account_id>/<date>.json`. It uses exclusive creation (`x` mode) to prevent overwriting.
- **Do Not Mindlessly Retry:** If the script fails, do not simply run it again. Analyze the error first.

**Error Handling & Decision Tree:**
- **Authentication Error (401/403):** The token in `token.json` has likely expired or been revoked. **STOP.** Do not retry. Ask the user to re-authenticate (likely via a manual process or a different script).
- **FileExistsError:** This means a sync for "yesterday" has already been attempted. Check `raw/` to see if the file is valid.
- **Empty API Response:** The script will fail with `ValueError("No data returned from API")`. This often indicates a connectivity issue or an API-side glitch. **Wait and check bank status** before retrying.
- **Partial/Zero Transactions:** If the sync completes but 0 transactions are downloaded, check if this matches reality (e.g. no spending yesterday). If spending *did* occur, the API may be delayed.

**Workflow:**
- Command: `uv run update_transactions.py`
- Observe the output for: "Downloaded X transaction(s)" or "Account is up to date."
- **Verification:** After a successful sync, you can run a script to check the new `max_date` to ensure the window has moved forward.

### 2. Enrich Transactions
Loads all raw transactions, deduplicates them, and applies existing categorization rules (Manual, Regex Patterns, and AI Cache).

**Workflow:**
- Command: `uv run enrich_transactions.py`
- **Output:**
    - `all_transactions.csv`: Flattened raw data.
    - `enriched_transactions.csv`: Data with `category`, `source`, and `confidence` fields.
- **Verification:** Check the "Enrichment Summary" table in the output. It shows how many transactions were categorized by each source (e.g., `PATTERN`, `AI_CACHED`, `MANUAL`).

### 3. Prune LLM Cache
Removes specific transaction IDs from the LLM cache. This is useful when the AI has provided an incorrect or "unknown" category and you want to force it to re-evaluate (or let a new Pattern take over).

**Workflow:**
- Command: `uv run prune_cache.py <tx_id1> <tx_id2> ...`
- **Verification:** Run `uv run enrich_transactions.py` afterwards to ensure the pruned transactions now show up as `null` source (ready for re-processing).
