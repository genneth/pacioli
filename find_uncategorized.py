import argparse

import polars as pl
from polars import col as C

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(description="Find transactions that need categorization.")
    parser.add_argument("--limit", type=int, default=20, help="Max transactions to show in detail.")
    parser.add_argument("--summary", action="store_true", help="Show grouped summary of merchants.")
    parser.add_argument("--force", action="store_true", help="Include transactions already in the AI cache.")
    args = parser.parse_args()

    tm = TransactionManager()
    rows = load_transactions()
    df_enriched = tm.enrich_transactions(rows)
    
    if args.force:
        # Include things that are null OR were categorized by AI/Agent
        df_missing = df_enriched.filter(
            C.source.is_null() | C.source.is_in(["AI_CACHED", "AI_AGENT"])
        )
    else:
        df_missing = df_enriched.filter(C.source.is_null())

    if df_missing.is_empty():
        print("All transactions are already categorized.")
        return

    # Sort chronologically
    df_missing = df_missing.sort("booking_date")

    if args.summary:
        # Group by counterparty/remittance to show the agent the 'big wins'
        summary = (
            df_missing.group_by(["counterparty", "remittance"])
            .agg([
                pl.len().alias("n"),
                pl.col("amount").abs().mean().round(2).alias("avg"),
                pl.col("id").first().alias("sample_id")
            ])
            .sort("n", descending=True)
        )
        print("N | AVG | SAMPLE_ID | PARTY | REMIT")
        for row in summary.to_dicts():
            print(f"{row['n']} | {row['avg']} | {row['sample_id']} | {row['counterparty']} | {row['remittance']}")
    else:
        # Concise pipe-delimited list for the agent
        # We format times to save tokens but keep full IDs for cache updates
        print("ID | DATE | TIME | AMT | PARTY | REMIT")
        output_df = df_missing.select(
            [
                pl.col("id"),
                pl.col("booking_date"),
                pl.col("time_of_day").dt.to_string("%H:%M"),
                pl.col("amount"),
                pl.col("counterparty").str.replace_all("\n", " "),
                pl.col("remittance").str.replace_all("\n", " ")
            ]
        ).head(args.limit)
        
        for row in output_df.iter_rows():
            print(" | ".join(str(x) for x in row))

    print(f"\nTotal Gaps: {df_missing.height}")

if __name__ == "__main__":
    main()
