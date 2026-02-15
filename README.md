# Pacioli

![Luca Pacioli](https://commons.wikimedia.org/wiki/File:Luca_Pacioli_in_the_Summa.jpg#/media/File:Luca_Pacioli_in_the_Summa.jpg)

Personal finance tracker using Open Banking (GoCardless) and agentic classification.

## Setup

1. **Environment Variables (`.env`)**:
   ```toml
   GOCARDLESS_SECRET_ID = "..."
   GOCARDLESS_SECRET_KEY = "..."
   TRANSFER_NAME = "..." # Your name as it appears in bank transfers (e.g. "SMITH")
   ```

2. **TODO**: Ask me (the agent) for help setting up the **GoCardless authorization** and **Open Banking links**. This is a one-off act required before the sync will work.

## User Guide (Gemini CLI)

The project is managed via the **Gemini CLI** using the `ops` skill.

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
