---
name: onboarding
description: >
  Guides a new user through setting up Pacioli from scratch: installing
  dependencies, connecting bank accounts via GoCardless, discovering spending
  categories from real data, and generating personal labelling heuristics.
  Use this skill when the user mentions setup, onboarding, getting started,
  connecting a bank, linking accounts, or first-time configuration.
---

# Onboarding

## Purpose

Walk a new user from "I just cloned this repo" to "I have categorized
transactions and a working daily pipeline." The agent drives the entire process:
making API calls, writing config files, proposing categories from real data, and
interviewing the user to build personal heuristics.

## Resume Detection

Before starting, check what already exists and skip completed phases:

| Check | If present, skip to |
|-------|---------------------|
| `.env` with all 3 keys | Phase 3 |
| `token.json` + authorized requisitions | Phase 4 |
| `raw/` with JSON files | Phase 5 |
| `data/patterns.json` with category keys | Phase 6 |
| `data/ai_instructions.md` | Phase 7 |

Run these checks at the start of every onboarding session.

---

## Phase 1: Prerequisites

Confirm the environment can run the project.

1. Verify `uv` is installed. If not: `winget install astral-sh.uv` (Windows) or
   see https://docs.astral.sh/uv/getting-started/installation/
2. Run `uv sync` to install dependencies from `pyproject.toml`
3. Verify: `uv run python -c "import polars; import requests; print('OK')"`
4. Create `raw/` and `data/` directories if they don't exist

---

## Phase 2: Environment (.env)

Create the credentials file. Check if `.env` already exists and has all required
keys before prompting.

**Required keys:**

| Key | What it is | Where to get it |
|-----|-----------|-----------------|
| `GOCARDLESS_SECRET_ID` | API client ID | GoCardless dashboard (bankaccountdata.gocardless.com) |
| `GOCARDLESS_SECRET_KEY` | API client secret | Same dashboard, under "User secrets" |
| `TRANSFER_NAME` | User's name as it appears in bank transfers | Ask the user (e.g. their surname in caps) |

Explain that GoCardless Bank Account Data is a free Open Banking aggregator — the
user needs to register and create API credentials. The `.env` file is gitignored
and will never be committed.

**Validate** by instantiating the client:
```bash
uv run python -c "from go_cardless_client import Client; Client()"
```
If this succeeds (prints "Successfully authenticated and fetched institutions"),
credentials are good. If it fails, report the error and iterate.

---

## Phase 3: Bank Linking

This replaces the old `one-time.ipynb`. The agent drives the GoCardless API to
connect the user's bank accounts.

### 3a. Discover institutions

The `Client` class hardcodes `country=GB`. For other countries, call the API
directly:
```python
client.get("institutions/", {"country": "XX"})  # ISO 3166-1 alpha-2
```
Present available banks to the user. Let them pick which to connect.

### 3b. Check existing state

```python
client.get("agreements/enduser/")
client.get("requisitions/")
```
If valid agreements and linked requisitions (status `LN`) already exist with
populated `accounts`, skip to Phase 4.

### 3c. Create agreements

For each selected bank:
```python
client.post("agreements/enduser/", {
    "institution_id": "<INSTITUTION_ID>",
    "max_historical_days": 730,       # or institution's max
    "access_valid_for_days": 180,
    "access_scope": ["balances", "details", "transactions"]
})
```
Explain what `max_historical_days` means and let the user choose.

### 3d. Create requisitions

For each agreement:
```python
client.post("requisitions/", {
    "institution_id": "<INSTITUTION_ID>",
    "agreement": "<AGREEMENT_ID>",
    "redirect": "https://google.com",
    "reference": "<USER_LABEL>"       # e.g. "BarclaysMain"
})
```
Ask the user for a friendly label for each connection.

### 3e. Present authorization links

Each requisition has a `link` field — the URL the user must visit to authorize
with their bank.

**Present both the URL and a terminal QR code** (for mobile bank auth):
```python
import qrcode
qr = qrcode.QRCode(box_size=1, border=1)
qr.add_data(link_url)
qr.make(fit=True)
qr.print_ascii(invert=True)
```

Tell the user: "Open this link (or scan the QR) to log into your bank and
authorize the connection. Come back here when you're done."

### 3f. Wait and verify

**This is a hard pause.** The agent cannot proceed until the user confirms they
have authorized.

After confirmation, poll the requisitions:
```python
client.get("requisitions/")
```
Check that status is `LN` (Linked) and `accounts` is non-empty. If still `CR`
(Created), the authorization may not have completed — ask the user to retry.

---

## Phase 4: First Sync

`update_transactions.py` only fetches new data for accounts that **already have
history** in `raw/`. Brand-new accounts (just linked in Phase 3) are invisible to
it. You must bootstrap them first.

### 4a. Bootstrap new accounts

For each account ID discovered from the requisitions in Phase 3:

1. Create the directory: `raw/<account_id>/`
2. Fetch the initial history directly via the client:
   ```python
   from datetime import date, timedelta
   yesterday = (date.today() - timedelta(days=1)).isoformat()
   # Go back as far as the agreement allows (e.g. 730 days)
   start = (date.today() - timedelta(days=730)).isoformat()
   dump = client.get(f"accounts/{account_id}/transactions/",
                     {"date_from": start, "date_to": yesterday})
   ```
3. Write the response to `raw/<account_id>/<yesterday>.json`
4. Report the transaction count and date range

This is a one-time step. Once the account has at least one file in `raw/`,
`update_transactions.py` takes over for all future syncs.

### 4b. Verify and enrich

```bash
uv run update_transactions.py
uv run enrich_transactions.py
```

The first command confirms the normal sync path now works (it should be a no-op
if the bootstrap already fetched up to yesterday). The second produces a baseline
CSV — everything will be uncategorized at this point, which is expected.

**Error handling**: If the sync fails (503, token error, etc.), report it clearly.
If one account succeeds and another fails, continue with available data but tell
the user which account is stale and why.

---

## Phase 5: Category Discovery

Categories are NOT pre-seeded. They emerge from the user's actual data.

### 5a. Survey the landscape

```bash
uv run find_uncategorized.py --summary
uv run find_uncategorized.py --limit 200
```

Cluster transactions by counterparty and amount. Web-search any opaque merchant
names to identify what kind of business they are.

### 5b. Propose a taxonomy

Based on observed patterns, propose a category structure. Use the `Category > Subcategory`
naming convention. Ask the user:

- "What kinds of spending are you most interested in tracking?"
- "Here's what I see in your data: [groupings]. Does this structure work?"
- "Anything you'd add, remove, or break down further?"

Iterate until the user is satisfied.

### 5c. Scaffold data files

Create `data/patterns.json` with the agreed categories as keys, each mapping to
an empty list. This establishes the master category set. Also create empty
`data/manual_assignments.json` (`{}`) and `data/llm_cache.json` (`{}`).

### 5d. First-pass labelling

Now that categories exist, do an initial pass. Focus on the **Pareto wins**:

1. **High-frequency merchants** — identify the top 20-30 by occurrence. For each,
   create a regex pattern directly in `data/patterns.json` (these are the "big
   wins" that might cover 70-80% of transactions). Validate each with
   `uv run test_pattern.py "REGEX"` before adding.
2. **Long tail** — for less frequent merchants, batch-label into the AI cache
   using `uv run update_llm_cache.py --batch FILE`. Follow the ops skill's batch
   format and UTF-8 encoding conventions.
3. **Don't try to cover everything** — explicitly tell the user that remaining
   gaps will be handled through daily passes with the ops skill.

After labelling: `uv run enrich_transactions.py` to verify progress.

---

## Phase 6: Personal Heuristics Interview

This comes AFTER labelling — by now the agent has seen the user's real spending
patterns and can ask informed, specific questions rather than abstract ones.

Write `data/ai_instructions.md` based on the user's answers. Cover these topics:

1. **Work schedule & location** — standard hours? office location? (Helps
   distinguish work-area lunches from weekend dining.)
2. **Recurring patterns** — the agent should mine the data for day-of-week
   regularities and ask about them. ("I notice you go to [X] most Wednesdays —
   what's that about?")
3. **Meal timing boundaries** — what times mark breakfast/lunch/dinner transitions?
   Propose reasonable defaults, let user adjust.
4. **Clean name philosophy** — confirm entity-first naming (specific merchant
   names, not category groupings).
5. **Travel habits** — frequent traveler? Regular international transactions?
6. **Refund handling** — explain the mirror-spending rule (refunds categorized
   same as original spend). Any exceptions?
7. **Expense reimbursements** — does the user receive work expense reimbursements?
   From which entity?
8. **Special rules** — any merchants that should always go to a specific category
   regardless of amount or time?

---

## Phase 7: Verification & Handoff

1. Full pipeline: `uv run enrich_transactions.py`
2. Quality: `uv run lint_patterns.py`
3. Security: `uv run python check_pii.py`
4. Visualization: `uv run generate_spending_viz.py`
5. Report final stats: total transactions, % categorized, category breakdown
6. Explain the `ops` skill and the "daily pass" workflow for ongoing use

---

## Standing Rules

- **Never silently swallow errors.** Report every failure with what happened and
  what the user can do about it.
- **Privacy** — transaction data is personal. Don't echo back unnecessary detail.
  `data/`, `raw/`, and `*.csv` are gitignored. Never commit them.
- **Idempotent** — every phase checks existing state first. Safe to restart
  mid-onboarding.
