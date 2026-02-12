import logging

import polars as pl
from polars import col as C

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    logging.basicConfig(level=logging.WARNING)

    rows = load_transactions()
    tm = TransactionManager()

    print("\n--- Pattern Linting Report ---\n")

    # 1. Calculate effective hits for each pattern
    # A hit only counts if the transaction isn't already handled by a higher priority source
    tm.detect_transfers(rows)

    # Pre-calculate priority status for all transactions
    tx_status = {tx.id: tm.get_priority_source(tx) for tx in rows}

    results = []
    for p in tm.patterns:
        pattern_str = p.get("pattern", "")
        p_field = p.get("field", "counterparty")
        clean_name = p.get("clean_name", "Unknown")
        category = p.get("category", "Uncategorized")

        all_matches = tm.test_pattern(
            rows,
            pattern_str,
            field=p_field,
            min_amount=p.get("min_amount"),
            max_amount=p.get("max_amount"),
            min_day=p.get("min_day"),
            max_day=p.get("max_day"),
            min_time=p.get("min_time"),
            max_time=p.get("max_time"),
        )

        # Only count hits that aren't overridden by higher priority sources
        effective_matches = [m for m in all_matches if tx_status[m.id] is None]

        sample_id = effective_matches[0].id if effective_matches else (all_matches[0].id if all_matches else None)
        results.append({
            "pattern": pattern_str,
            "clean_name": clean_name,
            "category": category,
            "hits": len(effective_matches),
            "sample_id": sample_id,
        })

    df = pl.DataFrame(results)

    # Check for dead patterns
    dead = df.filter(C.hits == 0)
    if not dead.is_empty():
        print(f"[FAIL] Found {len(dead)} patterns that match ZERO available transactions:")
        for row in dead.sort("category").to_dicts():
            print(f"  - {row['category']:<30} | {row['pattern']} ({row['clean_name']})")
        print()
    else:
        print("[PASS] No dead patterns found.")

    # Check for low-utility patterns (1-3 matches)
    low_utility = df.filter((C.hits > 0) & (C.hits <= 3))
    if not low_utility.is_empty():
        print(f"[HINT] Found {len(low_utility)} patterns matching 3 or fewer transactions.")
        print("Consider moving these to 'data/manual_assignments.json' if they are unlikely to recur:")
        for row in low_utility.sort("hits", "category").to_dicts():
            print(f"  - ({row['hits']} hits) {row['category']:<25} | {row['pattern']} (ID: {row['sample_id']})")
        print()

    # 2. Check for Overlaps (Transactions matching multiple patterns)
    overlap_count = 0
    for tx in rows:
        matches = tm._find_matches(tx)
        if "_ALL_PATTERNS" in matches and len(matches["_ALL_PATTERNS"]) > 1:
            overlap_count += 1
            if overlap_count <= 5:
                pats = [m["pattern_matched"] for m in matches["_ALL_PATTERNS"]]
                print(f"[WARN] Transaction {tx.id} matched multiple patterns: {pats}")

    if overlap_count > 5:
        print(f"... and {overlap_count - 5} more overlaps.")

    if overlap_count == 0:
        print("[PASS] No pattern overlaps detected.")
    else:
        print(f"\n[SUMMARY] Found {overlap_count} overlapping transactions.")

    print("\nReport complete.")


if __name__ == "__main__":
    main()
