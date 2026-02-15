---
name: ops
description: Personal finance operations for Pacioli. Use this skill to sync transactions from bank APIs, manage the categorization cache, and ground decisions in established rules.
---

# Ops

## Overview
This skill provides a set of operational workflows for managing Pacioli's financial data pipeline. It focuses on maintaining data integrity, syncing with bank APIs, and managing the lifecycle of transaction categorization from "AI Guest" to "Gold Standard."

## Core Tasks

### 1. Sync Transactions
Syncs the local transaction store with the bank via the GoCardless API.
- Command: `uv run update_transactions.py`

### 2. Enrich Transactions
Loads raw transactions and applies the hierarchy: Manual > Transfer > Zero > Pattern > AI/Agent.
- Command: `uv run enrich_transactions.py`
- **Output:** `enriched_transactions.csv`.

### 3. Agent-Led Categorization
The primary workflow for resolving "Uncategorized" transactions.
1. **Find**: `uv run find_uncategorized.py --limit 100`
   - **Batching**: Aim for 50-100 transactions per batch. This is large enough to see cross-transaction patterns (e.g., a trip) but small enough to maintain high reasoning performance.
   - Use `--force` to include transactions already in the AI cache for recategorization.
2. **Grounding**:
   - **Read Gold Standard**: Directly read `data/patterns.json` and `data/manual_assignments.json` at the start of the session. These provide the "source of truth" for your style and existing rules.
   - **Instructions**: Always follow `data/ai_instructions.md`.
3. **Context Check (Forensics)**:
   - **Calendar**: Use `calendar.listEvents` to check the transaction date for travel/location context (e.g., "Paris Trip").
   - **Gmail**: Use `gmail.search` to find receipts for ambiguous amounts/merchants (Query: "Merchant" or "Amount").
4. **Research**: Use web search if the merchant is entirely unknown.
5. **Batch Persist**: Use `update_llm_cache.py --batch <file>` to save your decisions efficiently.

### 4. Promotion to Gold Standard
When the user requests to "automate" a merchant or "fix" a recurring classification:
1. **Manual Assignment**: For unique outliers. Edit `data/manual_assignments.json`.
2. **Pattern Creation**: For recurring merchants.
    - Test: `uv run test_pattern.py "regex"`
    - Apply: Add to `data/patterns.json` under the correct category.
3. **Cleanup**: Run `uv run cleanup_cache.py` to remove now-redundant cache entries.

### 5. Category Management
The system only accepts categories existing as keys in `data/patterns.json`.
- **Add Category**: Manually add a new key with an empty list `[]` to `data/patterns.json`.
- **List Categories**: `uv run list_categories.py`

### 6. Cache Maintenance
- **Prune**: `uv run prune_cache.py <tx_id>` (Targeted removal)
- **Auto-Cleanup**: `uv run cleanup_cache.py` (Removes cache entries shadowed by new patterns/manual assignments)

### 7. Diagnostics & Quality
- **Explain**: `uv run python -c "from transaction_manager import TransactionManager, load_transactions; tm=TransactionManager(); txs=load_transactions(); print(tm.explain_transaction(txs[0]))"` (Replace index with target)
- **Lint**: `uv run lint_patterns.py` (Find dead/overlapping patterns)
- **PII Check**: `uv run python check_pii.py`

## Combined Workflows (Chains)

### A. The "Daily Pass"
`Sync -> Enrich -> Categorize -> Enrich -> Visualize`
1. `uv run update_transactions.py`
2. `uv run enrich_transactions.py`
3. (If gaps exist) Run **Agent-Led Categorization** (Task 3).
4. `uv run enrich_transactions.py`
5. `uv run generate_spending_viz.py`

### B. The "Pattern Hardening" Loop
`Identify Candidates -> Create Pattern -> Cleanup -> Lint`
1. `uv run identify_candidates.py` (Finds recurring merchants in the cache).
2. Ask User: "Would you like me to create a pattern for [Merchant]?"
3. Create pattern in `data/patterns.json` (Task 4).
4. `uv run cleanup_cache.py; uv run lint_patterns.py; uv run enrich_transactions.py`
