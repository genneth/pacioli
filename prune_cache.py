import json
import os
import sys


def prune_cache(tx_ids: list[str], cache_file: str = "data/llm_cache.json"):
    if not os.path.exists(cache_file):
        print(f"Cache file {cache_file} not found.")
        return

    with open(cache_file) as f:
        cache = json.load(f)

    initial_count = len(cache)
    removed = []

    for tx_id in tx_ids:
        if tx_id in cache:
            del cache[tx_id]
            removed.append(tx_id)

    if removed:
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"Successfully pruned {len(removed)} entries from cache.")
        print(f"Remaining entries: {len(cache)} (was {initial_count})")
    else:
        print("No matching transaction IDs found in cache.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run prune_cache.py <tx_id1> <tx_id2> ...")
        sys.exit(1)

    prune_cache(sys.argv[1:])
