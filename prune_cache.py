import argparse

from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(description="Prune entries from LLM cache.")
    parser.add_argument("ids", nargs="*", help="Transaction IDs to prune")
    parser.add_argument(
        "--category", help="Prune all entries matching this category (prefix match)"
    )
    args = parser.parse_args()

    tm = TransactionManager()
    initial_count = len(tm.llm_cache)

    # 1. Prune by ID
    for tx_id in args.ids:
        if tx_id in tm.llm_cache:
            del tm.llm_cache[tx_id]
            print(f"Pruned ID: {tx_id}")

    # 2. Prune by Category
    if args.category:
        to_delete = [
            tx_id
            for tx_id, cached in tm.llm_cache.items()
            if cached.get("category", "").lower().startswith(args.category.lower())
        ]
        for tx_id in to_delete:
            del tm.llm_cache[tx_id]
        print(f"Pruned {len(to_delete)} entries matching category '{args.category}'")

    if len(tm.llm_cache) != initial_count:
        tm.save_data()
        print(f"Total pruned: {initial_count - len(tm.llm_cache)} entries.")
    else:
        print("No matches found in cache.")


if __name__ == "__main__":
    main()
