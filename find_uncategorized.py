import argparse
import logging

import polars as pl
from polars import col as C

from cli_common import load_enriched, setup_logging


def main():
    parser = argparse.ArgumentParser(description="Find transactions that need categorization.")
    parser.add_argument("--limit", type=int, default=20, help="Max transactions to show in detail.")
    parser.add_argument("--summary", action="store_true", help="Show grouped summary of merchants.")
    parser.add_argument("--force", action="store_true", help="Include transactions already in the AI cache.")
    args = parser.parse_args()

    setup_logging(logging.WARNING)
    _, _, df_enriched = load_enriched()

    if args.force:
        # Include things that are null OR were categorized by AI/Agent
        df_missing = df_enriched.filter(
            C.source.is_null() | (C.source == "AI_AGENT")
        )
    else:
        df_missing = df_enriched.filter(C.source.is_null())

    if df_missing.is_empty():
        print("All transactions are already categorized.")
        return

    # Sort chronologically
    df_missing = df_missing.sort("booking_date")

    def fmt_meta(row: dict) -> str:
        parts = []
        if row.get("card_last4"):
            parts.append(f"card={row['card_last4']}")
        if row.get("tx_type"):
            parts.append(f"type={row['tx_type']}")
        if row.get("foreign_currency"):
            parts.append(f"fx={row['foreign_currency']}")
        return " ".join(parts)

    df_missing = df_missing.with_columns(
        pl.struct(["card_last4", "tx_type", "foreign_currency"])
        .map_elements(fmt_meta, return_dtype=pl.Utf8)
        .alias("meta")
    )

    if args.summary:
        # Group by counterparty/remittance/card to show the agent the 'big wins'.
        # Card is included so a merchant used on different cards (e.g. personal vs joint)
        # doesn't collapse if it would categorize differently.
        summary = (
            df_missing.group_by(["counterparty", "remittance", "card_last4", "tx_type"])
            .agg([
                pl.len().alias("n"),
                pl.col("amount").abs().mean().round(2).alias("avg"),
                pl.col("id").first().alias("sample_id"),
                pl.col("meta").first().alias("meta"),
            ])
            .sort("n", descending=True)
        )
        print("N | AVG | SAMPLE_ID | PARTY | REMIT | META")
        for row in summary.to_dicts():
            print(
                f"{row['n']} | {row['avg']} | {row['sample_id']} | "
                f"{row['counterparty']} | {row['remittance']} | {row['meta']}"
            )
    else:
        # Concise pipe-delimited list for the agent
        # We format times to save tokens but keep full IDs for cache updates
        print("ID | DATE | TIME | AMT | PARTY | REMIT | META")
        output_df = df_missing.select(
            [
                pl.col("id"),
                pl.col("booking_date"),
                pl.col("time_of_day").dt.to_string("%H:%M"),
                pl.col("amount"),
                pl.col("counterparty").str.replace_all("\n", " "),
                pl.col("remittance").str.replace_all("\n", " "),
                pl.col("meta"),
            ]
        ).head(args.limit)

        for values in output_df.iter_rows():
            print(" | ".join(str(x) for x in values))

    print(f"\nTotal Gaps: {df_missing.height}")

if __name__ == "__main__":
    main()
