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
The primary workflow for resolving "Uncategorized" transactions. Favor the **AI Cache** for new or infrequent merchants.
1. **Find**: `uv run find_uncategorized.py --limit 50`
   - **Chronological Order**: Always process transactions chronologically. This is vital for "Forensics"—recognizing that a series of small spends in a specific city (e.g., Bled, Paris) indicates a trip.
   - **Batching**: 50 transactions is the sweet spot. It provides enough context for trip grouping without overloading reasoning.
2. **Grounding**:
   - **Read Gold Standard**: Directly read `data/patterns.json` and `data/manual_assignments.json` at the start of the session.
   - **Instructions**: Always follow `data/ai_instructions.md`.
3. **Context Check (Forensics)**:
   - **Trip Grouping**: Look at surrounding transactions. A "St Pancras" spend followed by "Eurostar" and "RATP" confirms a France trip.
   - **Calendar/Gmail**: Use `calendar.listEvents` and `gmail.search` for high-value or ambiguous items.
4. **Research**: Use web search if the merchant is entirely unknown.
5. **Batch Persist**: 
   - Use `update_llm_cache.py --batch <file>`.
   - **Safety**: Ensure batch JSON files are saved and read using **UTF-8** encoding to support special characters in merchant names (e.g., "Brasserie Zédel").
   - **Tidy Up**: Delete the temporary batch JSON file immediately after a successful `update_llm_cache.py` run to keep the workspace clean.

### 4. Promotion to Gold Standard
Move high-frequency "AI Agent" classifications to "Gold Standard" (Patterns). **Promotion to patterns should be conservative and only happen after several repeat occurrences.**
1. **Identify**: Only propose a **Regex Pattern** if a merchant has appeared **at least 5 times** in the dataset or is clearly a high-frequency monthly subscription. For everything else, use the AI Cache.
2. **Manual Assignment**: For unique one-off outliers (e.g., a specific property fee). Edit `data/manual_assignments.json`.
3. **Pattern Creation**: 
    - Test: `uv run test_pattern.py "regex"`
    - Apply: Add to `data/patterns.json`.
4. **Cleanup**: Run `uv run cleanup_cache.py` to remove now-redundant cache entries.

### 5. Category Management
The system only accepts categories existing as keys in `data/patterns.json`.
- **List Categories**: `uv run list_categories.py`

### 6. Cache Maintenance
- **Prune**: `uv run prune_cache.py <tx_id>`
- **Auto-Cleanup**: `uv run cleanup_cache.py` (Shadowed entries).

### 7. Diagnostics & Quality
- **Lint**: `uv run lint_patterns.py` (Dead/overlapping patterns).
- **PII Check**: `uv run python check_pii.py`.

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
1. `uv run identify_candidates.py`
2. Ask User: "Would you like me to create a pattern for [Merchant]?"
3. Create pattern in `data/patterns.json`.
4. `uv run cleanup_cache.py; uv run lint_patterns.py; uv run enrich_transactions.py`
