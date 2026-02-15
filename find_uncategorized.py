import argparse

import polars as pl
from polars import col as C

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(description="Find transactions that need categorization.")
    parser.add_argument("--limit", type=int, default=20, help="Max transactions to show in detail.")
    parser.add_argument("--summary", action="store_true", help="Show grouped summary of merchants.")
    args = parser.parse_args()

    tm = TransactionManager()
    rows = load_transactions()
    df_enriched = tm.enrich_transactions(rows)
    df_missing = df_enriched.filter(C.source.is_null())

    if df_missing.is_empty():
        print("All transactions are already categorized.")
        return

    if args.summary:
        # Group by counterparty/remittance to show the agent the 'big wins'
        summary = (
            df_missing.group_by(["counterparty", "remittance"])
            .agg([
                pl.len().alias("count"),
                pl.col("amount").abs().mean().round(2).alias("avg_amt"),
                pl.col("time_of_day").first().alias("sample_time"),
                pl.col("id").first().alias("sample_id")
            ])
            .sort("count", descending=True)
        )
        print("--- Uncategorized Summary (Grouped by Merchant) ---")
        print(summary)
        print(f"\nTotal unique merchant patterns: {len(summary)}")
    else:
        # Concise list for the agent
        output_df = df_missing.select(
            ["id", "booking_date", "time_of_day", "amount", "counterparty", "remittance"]
        ).head(args.limit)
        
        print("--- Detailed Candidates ---")
        print(output_df)

    print(f"\nTotal uncategorized transactions: {df_missing.height}")

if __name__ == "__main__":
    main()
