import logging
import polars as pl
from polars import col as C
import re

from transaction_loader import load_transactions
from transaction_manager import TransactionManager

def main():
    logging.basicConfig(level=logging.WARNING)
    
    rows = load_transactions()
    tm = TransactionManager()
    
    print("\n--- Pattern Linting Report ---\n")
    
    # 1. Check for unused patterns or patterns with very few matches
    # We iterate through all patterns and count matches manually to be precise
    
    results = []
    for p in tm.patterns:
        pattern_str = p.get("pattern", "")
        p_field = p.get("field", "counterparty")
        clean_name = p.get("clean_name", "Unknown")
        category = p.get("category", "Uncategorized")
        
        matches = tm.test_pattern(
            rows, 
            pattern_str, 
            field=p_field,
            min_amount=p.get("min_amount"),
            max_amount=p.get("max_amount"),
            min_day=p.get("min_day")
        )
        
        results.append({
            "pattern": pattern_str,
            "clean_name": clean_name,
            "category": category,
            "hits": len(matches),
            "sample_id": matches[0].id if matches else None
        })
    
    df = pl.DataFrame(results)
    
    # Check for dead patterns
    dead = df.filter(C.hits == 0)
    if not dead.is_empty():
        print(f"[FAIL] Found {len(dead)} patterns that match ZERO transactions:")
        for row in dead.to_dicts():
            print(f"  - {row['category']} | {row['pattern']} ({row['clean_name']})")
        print()
    else:
        print("[PASS] No dead patterns found.")

    # Check for inefficient patterns (1 match)
    lonely = df.filter(C.hits == 1)
    if not lonely.is_empty():
        print(f"[HINT] Found {len(lonely)} patterns matching only ONE transaction.")
        print("Consider moving these to 'data/manual_assignments.json' for better performance:")
        for row in lonely.to_dicts():
            print(f"  - {row['category']} | {row['pattern']} (ID: {row['sample_id']})")
        print()
    
    # 2. Check for Overlaps (Transactions matching multiple patterns)
    # We use the existing resolve logic which already checks for this
    
    tm.detect_transfers(rows)
    overlap_count = 0
    for tx in rows:
        matches = tm._find_matches(tx)
        if "_ALL_PATTERNS" in matches and len(matches["_ALL_PATTERNS"]) > 1:
            overlap_count += 1
            if overlap_count <= 5: # Limit output
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