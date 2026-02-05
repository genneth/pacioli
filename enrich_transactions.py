import logging
from dataclasses import asdict

import polars as pl
from polars import col as C

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)8s %(message)s"
    )

    # 1. Load Transactions
    logging.info("Loading transactions from raw files...")
    rows = load_transactions()

    # Stash a copy of raw transactions
    df_raw = pl.DataFrame([asdict(r) for r in rows])
    df_raw.write_csv("all_transactions.csv")
    logging.info(f"Saved {len(rows)} raw transactions to all_transactions.csv")

    # 2. Enrich Transactions
    logging.info("Enriching transactions...")
    tm = TransactionManager()  # No genai_client needed for existing data enrichment
    df_enriched = tm.enrich_transactions(rows)

    # 3. Save Enriched Data
    df_enriched.write_csv("enriched_transactions.csv")
    logging.info("Saved enriched transactions to enriched_transactions.csv")

    # 4. Summarize
    summary = df_enriched.group_by(C.source).len().sort("len", descending=True)
    print("\nEnrichment Summary:")
    print(summary)

    # Identify transactions that still need categorization
    df_missing = df_enriched.filter(C.source.is_null())
    missing_count = df_missing.height
    if missing_count > 0:
        print(
            f"\n[ALERT] {missing_count} transactions are still "
            "uncategorized (source is null)."
        )
        print("Sample of uncategorized transactions:")
        # Show a few columns for context
        print(
            df_missing.select(
                ["booking_date", "amount", "counterparty", "remittance"]
            ).head(5)
        )
        print(
            "\nRun the LLM processing cell in interactive.ipynb or a "
            "dedicated LLM script to categorize them."
        )
    else:
        print("\n[SUCCESS] All transactions are categorized.")


if __name__ == "__main__":
    main()
