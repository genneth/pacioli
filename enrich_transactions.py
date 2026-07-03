import logging
from dataclasses import asdict

import polars as pl
from polars import col as C

from cli_common import ALL_TRANSACTIONS_CSV, ENRICHED_CSV, load_enriched, setup_logging


def main():
    setup_logging()

    # 1. Load and enrich
    logging.info("Loading transactions from raw files...")
    rows, tm, df_enriched = load_enriched()

    # Stash a copy of raw transactions
    df_raw = pl.DataFrame([asdict(r) for r in rows])
    df_raw.write_csv(ALL_TRANSACTIONS_CSV)
    logging.info(f"Saved {len(rows)} raw transactions to {ALL_TRANSACTIONS_CSV}")

    # 2. Save Enriched Data
    df_enriched.write_csv(ENRICHED_CSV)
    logging.info(f"Saved enriched transactions to {ENRICHED_CSV}")

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
    else:
        print("\n[SUCCESS] All transactions are categorized.")


if __name__ == "__main__":
    main()
