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
            print(
                f" - {m.booking_date}: {m.amount:>10.2f} {m.currency} | "
                f"{m.counterparty}"
            )

if __name__ == "__main__":
    main()