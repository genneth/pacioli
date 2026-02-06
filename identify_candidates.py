import logging

import polars as pl
from polars import col as C

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Identify high-frequency AI candidates."
    )
    parser.add_argument(
        "--category", help="Filter by category prefix (e.g. 'Food & Drink')"
    )
    parser.add_argument(
        "--mode",
        choices=["clean", "raw"],
        default="clean",
        help="Grouping mode: 'clean' (by AI name) or 'raw' (by bank counterparty string)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    
    # 1. Load and Enrich
    rows = load_transactions()
    tm = TransactionManager()
    df = tm.enrich_transactions(rows)

    # 2. Filter for AI-categorized only
    df_ai = df.filter(C.source == "AI_CACHED")
    
    if args.category:
        df_ai = df_ai.filter(C.category.str.starts_with(args.category))

    if df_ai.is_empty():
        print(
            f"No AI-categorized transactions found matching category "
            f"'{args.category or 'all'}'."
        )
        return

    # 3. Group and aggregate
    if args.mode == "clean":
        summary = (
            df_ai.group_by(["clean_name", "category"])
            .agg(
                hits=pl.len(),
                raw_samples=C.counterparty.unique().head(3)
            )
            .sort("hits", descending=True)
        )
    else:
        # Raw mode helps find inconsistent AI labelling
        summary = (
            df_ai.group_by(["counterparty"])
            .agg(
                hits=pl.len(),
                categories=C.category.unique(),
                ai_names=C.clean_name.unique()
            )
            .sort("hits", descending=True)
        )

    print(f"\nTop AI-Categorized Merchants (Mode: {args.mode}):")
    with pl.Config(fmt_str_lengths=100, tbl_rows=20):
        print(summary.head(20))
    
    print("\n[TIP] Pick a candidate, test a regex with 'uv run test_pattern.py',")
    print("then add it to data/patterns.json and run 'uv run cleanup_cache.py'.")

if __name__ == "__main__":
    main()