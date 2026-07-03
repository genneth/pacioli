from cli_common import setup_logging
from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    setup_logging()

    # 1. Load Transactions
    rows = load_transactions()
    tm = TransactionManager()
    
    # 2. Purge overridden cache entries
    # This removes entries from llm_cache.json if they are now handled by 
    # MANUAL, PATTERN, TRANSFER, or ZERO_AMOUNT rules.
    purged_count = tm.purge_override_cache(rows)
    
    if purged_count > 0:
        print(f"\n[SUCCESS] Purged {purged_count} redundant entries from LLM cache.")
    else:
        print("\n[INFO] No redundant entries found in LLM cache.")

if __name__ == "__main__":
    main()