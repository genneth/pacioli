import argparse

from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(description="Search gold-standard data for grounding.")
    parser.add_argument("query", help="Keyword to search for.")
    args = parser.parse_args()

    tm = TransactionManager()
    query = args.query.lower()
    found_any = False

    # 1. Search Manual Assignments
    manual_matches = []
    for _tx_id, data in tm.manual_assignments.items():
        name = data.get("clean_name", "").lower()
        cat = data.get("category", "").lower()
        if query in name or query in cat:
            manual_matches.append(f"MANUAL | {data.get('clean_name')} -> {data.get('category')}")

    # 2. Search Patterns
    pattern_matches = []
    for p in tm.patterns:
        pattern_str = p.get("pattern", "").lower()
        clean_name = p.get("clean_name", "").lower()
        category = p.get("category", "").lower()
        if query in pattern_str or query in clean_name or query in category:
            pattern_matches.append(f"PATTERN | /{p.get('pattern')}/ -> {p.get('clean_name')} ({p.get('category')})")

    if manual_matches:
        print("\n".join(manual_matches))
        found_any = True
    
    if pattern_matches:
        print("\n".join(pattern_matches))
        found_any = True

    if not found_any:
        print(f"No gold-standard matches for '{query}'.")

if __name__ == "__main__":
    main()
