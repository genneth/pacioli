# Pacioli

![Luca Pacioli](https://upload.wikimedia.org/wikipedia/commons/c/c8/Luca_Pacioli_in_the_Summa.jpg)

Personal finance tracker using Open Banking (GoCardless) and agentic
classification.

## Explanation

Raw bank responses are stored immutably in `raw/`; every category, clean name,
and report is derived from them. Nothing is edited in place, so the worst case
of a bad rule is a wrong label rather than lost data.

Categorization resolves through a fixed hierarchy — manual assignment, matched
transfers, zero amounts, regex patterns, then the AI cache. The agent's job is
to fill the bottom of that stack and to promote confident decisions upward as
evidence accumulates.

## Tutorial

Ask the agent to run the **onboarding** skill. It walks through:

1. Installing dependencies (`uv sync`)
2. Creating `.env` with GoCardless credentials and your transfer name
3. Linking bank accounts via GoCardless Open Banking
4. Fetching the first batch of transactions
5. Discovering spending categories from real data
6. Building personal labelling heuristics (`data/ai_instructions.md`)

Onboarding is idempotent — safe to restart if interrupted.

## How-to

### Run a daily pass

Ask for a **daily pass**. The agent syncs from the bank, labels anything new,
refreshes the spending chart, and commits the private `data/` repo. It also
reads the sync output for per-account failures, which do not surface as a
non-zero exit.

### Other things to ask for

| Ask | What happens |
|-----|--------------|
| "What's uncategorized?" | Lists transactions missing a label |
| "Automate [merchant]" | Proposes a regex pattern for a recurring merchant |
| "Audit my patterns" | Finds overlapping or dead rules |
| "Clean up the cache" | Removes labels now shadowed by patterns |
| "Are my connections healthy?" | Reports expired or stale bank connections |
| "Renew my connections" | Issues authorisation links for anything lapsed |

## Reference

| Document | Covers |
|----------|--------|
| [docs/gocardless.md](docs/gocardless.md) | GoCardless objects, endpoints, statuses, and constraints |
| [AGENTS.md](AGENTS.md) | Architecture, data schemas, and project conventions |
| [skills/ops/SKILL.md](skills/ops/SKILL.md) | The transaction pipeline |
| [skills/onboarding/SKILL.md](skills/onboarding/SKILL.md) | First-time setup |
| `data/ai_instructions.md` | Personal labelling heuristics (private, gitignored) |
