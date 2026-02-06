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

### 4. Cleanup LLM Cache
Automatically removes AI cache entries that are now covered by more deterministic rules (Manual, Patterns, Transfers, or Zero Amount). This keeps the cache lean and ensures deterministic rules always win.

**Workflow:**
- Command: `uv run cleanup_cache.py`
- **Verification:** Run `uv run enrich_transactions.py`. You should no longer see "Pattern match overrides AI Cache" info messages for those transactions.

### 5. Process LLM Labels
Sends uncategorized transactions to Gemini for AI labeling.

**Workflow:**
- **Standard Run:** `uv run process_llm.py` (processes only new/uncategorized transactions).
- **Force Relabel:** `uv run process_llm.py --force` (re-processes everything currently labeled as `AI_CACHED`).
- **Verification:** Run `uv run enrich_transactions.py` to see the updated categorization summary.

### 6. Test Regex Pattern
Dry-run a regex pattern against the transaction history to see what it would match before saving it to `patterns.json`.

**Workflow:**
- **Basic Test:** `uv run test_pattern.py "my regex"` (searches `counterparty` field).
- **Specific Field:** `uv run test_pattern.py "my regex" --field remittance`
- **Any Field:** `uv run test_pattern.py "my regex" --field any`
- **Amount Filter:** `uv run test_pattern.py "regex" --min-amount 100 --max-amount 500`
- **Timing Filter:** `uv run test_pattern.py "regex" --min-day 25` (checks day of month)
- **Verification:** Review the printed list of matches to ensure no false positives.

### 7. Identify Pattern Candidates
Analyzes AI-categorized transactions to find high-frequency merchants. This helps you decide which regex patterns are most worth creating to automate future categorization.

**Workflow:**
- **Standard Run:** `uv run identify_candidates.py` (groups by AI-generated "Clean Name").
- **Deep Scan (Raw Mode):** `uv run identify_candidates.py --mode raw` (groups by raw bank strings). This is highly effective at finding repeats that the AI labelled inconsistently.
- **Filter by Category:** `uv run identify_candidates.py --category "Food & Drink"` (matches any category starting with the string).
- **Output:** A table of candidates with hit counts and raw text samples.
- **Next Steps:** Use the samples to draft a regex, test it with Task 6, add it to `data/patterns.json`, and run Task 4 to cleanup the cache.
    - **Rule:** Always follow the **Entity-First Philosophy** for `clean_name`. Use the specific merchant name (e.g. "Waitrose") rather than a category name (e.g. "Groceries").

### 8. List Categories
Displays the current master list of categories defined in the system. Since categories are now managed as keys in the patterns configuration, this is the definitive list used by the LLM and validation logic.

**Workflow:**
- Command: `uv run list_categories.py`
- **Output:** A sorted list of all valid categories.
- **Next Steps:** If a category is missing, add it as a new key in `data/patterns.json` with an empty list `[]`.

### 9. Manually Assign Transaction
Manually overrides the categorization for a specific transaction ID. Use this for "one-off" outliers that don't warrant a recurring regex pattern.

**Workflow:**
1. Identify the transaction ID (e.g. from `enriched_transactions.csv` or `test_pattern.py`).
2. Add an entry to `data/manual_assignments.json`:
   ```json
   {
     "tx_id": {
       "clean_name": "Merchant Name",
       "category": "Category > Subcategory"
     }
   }
   ```
3. **Verification:** Run `uv run enrich_transactions.py` and look for the `MANUAL` source in the summary.

### 10. Lint Regex Patterns
Analyzes all patterns in `data/patterns.json` to identify dead, inefficient, or overlapping rules. This helps maintain a lean and deterministic categorization engine.

**Workflow:**
- Command: `uv run lint_patterns.py`
- **Output Types:**
    - `[FAIL]`: Dead patterns that match ZERO transactions.
    - `[HINT]`: Inefficient patterns that match only ONE transaction (consider moving to Manual Assignments).
    - `[WARN]`: Transactions matching multiple patterns (ambiguous rules).
- **Next Steps:** Refine the regex in `data/patterns.json` or move specific outliers to manual assignments.