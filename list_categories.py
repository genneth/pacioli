import logging

from cli_common import setup_logging
from transaction_manager import TransactionManager


def main():
    setup_logging(logging.WARNING)
    tm = TransactionManager()
    print("\nMaster Category List:")
    for cat in tm.categories:
        print(f" - {cat}")

if __name__ == "__main__":
    main()