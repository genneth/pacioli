import argparse
import logging

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(
        description="Test a regex pattern against transactions."
    )
    parser.add_argument("pattern", help="Regex pattern to test")
    parser.add_argument(
        "--field",
        choices=["counterparty", "remittance", "any"],
        default="counterparty",
        help="Field to match against",
    )
    parser.add_argument("--min-amount", type=float, help="Minimum absolute amount")
    parser.add_argument("--max-amount", type=float, help="Maximum absolute amount")
    parser.add_argument("--min-day", type=int, help="Minimum day of month (1-31)")
    args = parser.parse_args()

    # Keep logging quiet to focus on output
    logging.basicConfig(level=logging.WARNING) 
    rows = load_transactions()
    tm = TransactionManager()
    
    # Ensure transfers are detected for correct source attribution
    tm.detect_transfers(rows)
    
    matches = tm.test_pattern(
        rows,
        args.pattern,
        field=args.field,
        min_amount=args.min_amount,
        max_amount=args.max_amount,
        min_day=args.min_day,
    )
    
    print(f"\nPattern: '{args.pattern}' (field: {args.field})")
    print(f"Found {len(matches)} matches.")
    
    if matches:
        print("\nMatches (sorted by newest):")
        # Sort by date for better readability
        sorted_matches = sorted(matches, key=lambda x: x.booking_date, reverse=True)
        for m in sorted_matches:
            res = tm.resolve_transaction(m)
            category = res.get("category") or "Uncategorized"
            source = res.get("source") or "NONE"
            reason = res.get("category_reason") or ""
            suggested = res.get("suggested_category")
            suggested_reason = res.get("suggestion_reason") or ""

            # Use a wide horizontal format
            line = (
                f"{m.booking_date} | {m.amount:>9.2f} {m.currency} | "
                f"{m.counterparty[:40]:<40} | "
                f"{category[:30]:<30} ({source:<9})"
            )
            if reason:
                line += f" | {reason}"
            
            print(line)
            if suggested:
                print(f"      └─ SUGGESTION: {suggested} | WHY: {suggested_reason}")

if __name__ == "__main__":
    main()