# Pacioli

![Luca Pacioli](https://commons.wikimedia.org/wiki/File:Luca_Pacioli_in_the_Summa.jpg#/media/File:Luca_Pacioli_in_the_Summa.jpg)

Personal finance tracker using Open Banking (GoCardless) and agentic classification.

## Setup

Ask the agent to run the **onboarding** skill. It will walk you through:

1. Installing dependencies (`uv sync`)
2. Creating `.env` with GoCardless API credentials and your transfer name
3. Linking your bank accounts via GoCardless Open Banking
4. Fetching your first batch of transactions
5. Discovering spending categories from your real data
6. Building personal labelling heuristics (`data/ai_instructions.md`)

The onboarding skill is idempotent — safe to restart if interrupted.

## User Guide

The project is managed via an AI agent (Gemini CLI or Claude Code) using the `ops` skill.

### The "Daily Pass" (Primary Workflow)
Ask for a **"Daily Pass"** to run the full pipeline:
- **Sync**: Fetches latest data from the bank.
- **Enrich**: Applies existing patterns and rules.
- **Resolve Gaps**: I (the agent) research and label unknown merchants.
- **Visualize**: Generates updated spending reports.

### Other Commands
- **"What's uncategorized?"**: Lists transactions missing a label.
- **"Automate [Merchant Name]"**: I will suggest a regex pattern for a recurring merchant.
- **"Audit my patterns"**: Finds overlaps or dead rules.
- **"Cleanup the cache"**: Removes redundant labels.
- **"Search the gold standard"**: I will check existing patterns and manual assignments for keywords.
