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
- **Finite History:** Most Open Banking APIs only provide 90 days of transaction history.
- **Immutable Raw Data:** Script writes to `raw/<account_id>/<date>.json` using exclusive creation (`x` mode).

**Workflow:**
- Command: `uv run update_transactions.py`
- Observe the output for: "Downloaded X transaction(s)" or "Account is up to date."

### 2. Enrich Transactions
Loads all raw transactions, deduplicates them, and applies existing categorization rules (Manual, Regex Patterns, and AI Cache).

**Workflow:**
- Command: `uv run enrich_transactions.py`
- **Output:** `all_transactions.csv` (raw flattened) and `enriched_transactions.csv` (categorized).
- **Verification:** Check the "Enrichment Summary" table for categorization sources.

### 3. Prune LLM Cache
Removes specific transaction IDs or entire categories from the LLM cache to force re-evaluation.

**Workflow:**
- Command: `uv run prune_cache.py <tx_id1> <tx_id2> ...`
- **By Category:** `uv run prune_cache.py --category "Food & Drink"` (Prefix match)
- **Verification:** Follow with `uv run enrich_transactions.py`.

### 4. Cleanup LLM Cache
Automatically removes AI cache entries that are now covered by more deterministic rules.

**Workflow:**
- Command: `uv run cleanup_cache.py`
- **Verification:** Follow with `uv run enrich_transactions.py`.

### 5. Process LLM Labels
Sends uncategorized transactions to Gemini for AI labeling. **Note:** Incurs API costs; prefer manual labeling or patterns where possible.

**Workflow:**
- **Standard Run:** `uv run process_llm.py`
- **Force Relabel:** `uv run process_llm.py --force`
- **Verification:** Follow with `uv run enrich_transactions.py`.

### 6. Test Regex Pattern
Dry-run a regex pattern against the transaction history.

**Workflow:**
- **Basic Test:** `uv run test_pattern.py "my regex"`
- **Filters:** `--field remittance`, `--min-amount 100`, `--max-amount 500`, `--min-day 25`, `--max-day 31`, `--min-time 11:30`, `--max-time 14:00`.

### 7. Identify Pattern Candidates
Analyzes AI-categorized transactions to find high-frequency merchants for automation.

**Workflow:**
- **Standard Run:** `uv run identify_candidates.py`
- **Deep Scan:** `uv run identify_candidates.py --mode raw`
- **Rule:** Always follow the **Entity-First Philosophy** for `clean_name`.

### 8. List Categories
Displays the current master list of categories defined in the system.

**Workflow:**
- Command: `uv run list_categories.py`

### 9. Manually Assign Transaction
Manually overrides the categorization for a specific transaction ID. Use for "one-off" outliers.

**Workflow:**
1. Identify the transaction ID.
2. Add an entry to `data/manual_assignments.json`:
   ```json
   {
     "tx_id": { "clean_name": "Merchant Name", "category": "Category > Subcategory" }
   }
   ```

### 10. Lint Regex Patterns
Analyzes all patterns to identify dead, inefficient, or overlapping rules.

**Workflow:**
- Command: `uv run lint_patterns.py`
- **Output Types:**
    - `[FAIL]`: Dead patterns (ZERO transactions). **Must be resolved.**
    - `[WARN]`: Pattern overlaps. **Must be resolved.**
    - `[HINT]`: Low-utility patterns (1-3 transactions).
- **Judgment Call:** Keep patterns for recurring services; move one-offs to Manual Assignments.

## Combined Workflows (Chains)

### A. Pattern Creation Chain
Use after adding or modifying a pattern to verify health and apply changes immediately.
- `uv run lint_patterns.py; uv run cleanup_cache.py; uv run enrich_transactions.py`

### B. Sync & Initial Pass
The primary daily workflow. Fetches new data and attempts automatic categorization.
- `uv run update_transactions.py; uv run enrich_transactions.py`

### C. Optimization Loop
Use periodically to keep the AI cache lean.
- `uv run cleanup_cache.py; uv run enrich_transactions.py`

### D. Uncategorized Decision Tree
If transactions remain uncategorized after **Chain B** (source is `null`):
1. **Manual Assignment**: If it's a one-off outlier, use **Task 9**. (Cheapest/Fastest)
2. **Pattern Creation**: If it's recurring, use **Task 6**, then **Task 7**, then **Chain A**. (Best for automation)
3. **LLM Processing**: If merchant is complex or unknown, use **Task 5**. (Most expensive; use sparingly)
