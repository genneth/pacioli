---
name: ops
description: >
  Manages the Pacioli personal finance pipeline: syncing bank transactions,
  labelling uncategorized spending, promoting rules, and maintaining data quality.
  Use this skill whenever the user mentions transactions, categorization, spending,
  patterns, the daily pass, syncing, enriching, uncategorized, merchants,
  cache cleanup, or anything related to their financial data workflow.
---

# Ops

## Purpose

Turn raw bank transactions into cleanly labelled spending records. The system
resolves categories through a priority hierarchy — **Manual > Transfer > Zero
Amount > Regex Pattern > AI Cache** — and the agent's primary job is filling gaps
at the bottom of that stack and, over time, promoting confident decisions upward.

## Script Reference

| Script | Purpose | Key args |
|--------|---------|----------|
| `uv run update_transactions.py` | Fetch new data from GoCardless | — |
| `uv run enrich_transactions.py` | Apply hierarchy, output CSV + summary | — |
| `uv run find_uncategorized.py` | List unlabelled transactions | `--limit N`, `--summary`, `--force` |
| `uv run update_llm_cache.py` | Persist AI decisions | `--batch FILE` or `--id/--name/--category/--reason` |
| `uv run identify_candidates.py` | Find merchants ripe for pattern promotion | `--category PREFIX`, `--mode {clean,raw}` |
| `uv run test_pattern.py "REGEX"` | Dry-run a regex against all transactions | `--field`, `--min-amount`, `--max-amount`, `--min-day`, `--max-day`, `--min-time`, `--max-time` |
| `uv run cleanup_cache.py` | Remove cache entries now shadowed by rules | — |
| `uv run prune_cache.py ID…` | Delete specific cache entries | `--category PREFIX` |
| `uv run lint_patterns.py` | Dead / overlapping pattern report | — |
| `uv run list_categories.py` | Print the closed set of valid categories | — |
| `uv run generate_spending_viz.py` | Interactive spending chart (needs enriched CSV) | — |
| `uv run python check_pii.py` | Scan tracked files for secrets / PII | — |

---

## Primary Workflow: Categorize Transactions

This is the core of the skill — everything else supports it.

### 1. Survey the landscape

Start with the summary view to understand what's missing and spot clusters:

```bash
uv run find_uncategorized.py --summary
```

Then pull a working batch (50 is the sweet spot — enough for trip context, small
enough to reason about carefully):

```bash
uv run find_uncategorized.py --limit 50
```

Output is pipe-delimited: `ID | DATE | TIME | AMT | COUNTERPARTY | REMITTANCE`.

Use `--force` to include transactions already labelled by the AI cache (useful for
re-evaluating earlier decisions you're not confident in).

### 2. Ground yourself

Before labelling anything:

1. **Read `data/ai_instructions.md`** — it contains personal context and
   heuristics that override general knowledge. Follow it exactly.
2. **Grep, don't read** — for each merchant, grep `data/patterns.json` and
   `data/llm_cache.json` for similar names. Follow existing precedent. Don't
   bulk-read these files (they're large and contain PII).
3. **Confirm categories** — run `uv run list_categories.py` if unsure. Only use
   categories from this closed set.

### 3. Research and decide

Process transactions **chronologically** — this is essential for recognizing trips
(a cluster of foreign-currency spends over consecutive days is a trip, not
isolated events) and distinguishing lunch from dinner by timestamp.

For each transaction, follow this resolution order:

1. **Existing pattern match?** If the counterparty resembles something already in
   `patterns.json`, it should already be categorized. If it isn't, investigate the
   mismatch rather than adding a duplicate.
2. **Similar cache entry?** Grep `llm_cache.json`. If the same merchant was
   previously labelled, follow that precedent unless there's a good reason to
   differ (e.g., the original was wrong).
3. **Context clues** — use surrounding transactions, time of day, amount, and
   the heuristics from `data/ai_instructions.md` to classify.
4. **Web search** — if the merchant name is opaque (e.g., "SUMUP *XYZ123"),
   search the web to identify the actual business.

### 4. Choose the right destination

Not every decision belongs in the same place:

| Situation | Destination | Why |
|-----------|-------------|-----|
| New/infrequent merchant | **AI Cache** | Default choice. Low commitment, easy to revise. |
| Recurring merchant (5+ hits) or monthly subscription | **Pattern** (regex) | Deterministic, never needs re-evaluation. Use the Pattern Promotion workflow. |
| One-off outlier (same merchant, unusual category) | **Manual Assignment** | Overrides everything. Use sparingly. |

When in doubt, use the AI Cache. It's the cheapest decision to make and to undo.

### 5. Batch persist

Write all decisions to a temp JSON file and persist in one shot:

```bash
uv run update_llm_cache.py --batch /tmp/batch_decisions.json
```

The batch file is a **JSON array of objects** (not a dictionary):
```json
[
  {"id": "tx_hash", "name": "Merchant Name", "category": "Category > Sub", "reason": "Brief justification"}
]
```

- **UTF-8 encoding** — essential for accented merchant names.
- **Entity-first naming** — `name` must be a specific entity, never a category
  grouping. See `data/ai_instructions.md` for the naming philosophy.
- **Delete the temp file** after a successful run.

### 6. Verify

```bash
uv run enrich_transactions.py
```

Check the summary table in stdout. The uncategorized count should match
expectations. If transactions remain unlabelled, investigate — the usual causes
are a typo in the category name or a missing category key.

---

## Supporting Workflows

### Sync

```bash
uv run update_transactions.py
```

Idempotent and append-only. Safe to run anytime. Run before categorization when
the user wants fresh data.

If it fails (503, timeout, expired token), **report the error explicitly**. If
one account succeeds and another fails, continue with available data but clearly
state which account is stale, why, and since when.

### Pattern Promotion

Promote confident, high-frequency AI cache entries to deterministic regex patterns.
This is conservative by design — only promote when the evidence is clear.

1. `uv run identify_candidates.py` — find merchants with enough occurrences
2. Confirm with user: "X has appeared N times as 'Category'. Create a pattern?"
3. `uv run test_pattern.py "REGEX"` — verify it catches the right transactions
   and *only* those transactions (check for overlaps with existing patterns)
4. Add to `data/patterns.json` under the correct category key
5. `uv run cleanup_cache.py` — removes now-redundant cache entries
6. `uv run lint_patterns.py` — confirms no overlaps or dead patterns

### Cache Maintenance

| Command | When to use |
|---------|-------------|
| `uv run cleanup_cache.py` | After adding patterns or manual assignments. Removes shadowed entries. |
| `uv run prune_cache.py ID [ID...]` | To force re-evaluation of specific transactions. |
| `uv run prune_cache.py --category "Prefix"` | To wipe an entire category's cache entries. |

### Visualization

```bash
uv run generate_spending_viz.py
```

Requires a recent `enriched_transactions.csv`. Run `enrich_transactions.py` first
if the CSV is stale.

---

## The Daily Pass

When the user asks for a "daily pass", compose these steps — but skip any that
aren't needed (e.g., skip sync if data is fresh, skip viz if not requested):

1. **Sync**: `uv run update_transactions.py`
2. **Enrich**: `uv run enrich_transactions.py` (baseline to find gaps)
3. **Categorize**: if gaps exist, run the Primary Workflow above
4. **Cleanup**: `uv run cleanup_cache.py`
5. **Re-enrich**: `uv run enrich_transactions.py` (incorporate new labels)
6. **Visualize**: `uv run generate_spending_viz.py`

---

## Standing Rules

- **Never silently swallow errors or warnings** from command output.
- **Categories are closed** — only those in `data/patterns.json` keys are valid.
- **Privacy** — never bulk-read `data/` or `raw/` files. Grep for specific terms.
  Never commit anything from `data/`, `raw/`, or `*.csv`.
- **Disjoint patterns** — all regex patterns must be mutually exclusive. Use
  amount/time/day constraints to disambiguate broad patterns from specific ones.
