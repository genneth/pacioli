import argparse
import json
import logging
import os

from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(description="Update LLM cache with agent decisions.")
    parser.add_argument("--batch", help="Path to a JSON file containing a list of decisions.")
    parser.add_argument("--id", help="Transaction ID")
    parser.add_argument("--name", help="Clean Name")
    parser.add_argument("--category", help="Category")
    parser.add_argument("--reason", help="Reason for categorization")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    tm = TransactionManager()

    decisions = []
    if args.batch:
        if not os.path.exists(args.batch):
            logging.error(f"Batch file {args.batch} not found.")
            return
        with open(args.batch, encoding="utf-8") as f:
            decisions = json.load(f)
    elif args.id and args.name and args.category and args.reason:
        decisions = [{
            "id": args.id,
            "name": args.name,
            "category": args.category,
            "reason": args.reason
        }]
    else:
        logging.error("Must provide either --batch or all individual fields (--id, --name, --category, --reason).")
        return

    for item in decisions:
        tx_id = item.get("id")
        name = item.get("name")
        category = item.get("category")
        reason = item.get("reason")

        if not all([tx_id, name, category, reason]):
            logging.warning(f"Skipping invalid decision item: {item}")
            continue

        # Validate category
        if category not in tm.categories:
            logging.warning(
                f"Category '{category}' not in master list for {tx_id}. "
                f"Available: {tm.categories}"
            )

        # Update cache
        tm.llm_cache[tx_id] = {
            "clean_name": name,
            "category": category,
            "category_reason": reason,
            "confidence": 1.0,
            "source": "AI_AGENT"
        }

    tm.save_data()
    print(f"Successfully updated cache with {len(decisions)} decisions.")


if __name__ == "__main__":
    main()
