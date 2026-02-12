from transaction_manager import TransactionManager


def main():
    tm = TransactionManager()
    print("\nMaster Category List:")
    for cat in tm.categories:
        print(f" - {cat}")

if __name__ == "__main__":
    main()