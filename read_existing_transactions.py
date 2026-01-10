import os
import json
import logging

### Read existing transactions from raw
def read_existing_transactions() -> dict[str, list[dict]]:
    # load existing json dumps
    raw_dumps: dict[str, list] = {}
    if os.path.exists("raw"):
        for account in os.listdir("raw"):
            account_path = os.path.join("raw", account)
            if not os.path.isdir(account_path):
                continue
            
            raw_dumps[account] = []
            for file in os.listdir(account_path):
                if not file.endswith(".json"):
                    logging.getLogger().warning(
                        f"File {file} is not a JSON file. Skipping."
                    )
                    continue
                file_full_path = os.path.join(account_path, file)
                with open(file_full_path, "r", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                        raw_dumps[account].append(data)
                        logging.getLogger().info(f"Loaded {file} for account {account}.")
                    except json.JSONDecodeError:
                        logging.getLogger().error(f"Failed to decode JSON from {file}")

    # Merge and deduplicate
    per_account_transactions = {}
    
    for account, dumps in raw_dumps.items():
        all_transactions = []
        for i, dump in enumerate(dumps):
            if not isinstance(dump, dict):
                raise ValueError(f"Dump {i} for account '{account}' is not a dictionary.")
            
            transactions_wrapper = dump.get("transactions")
            if not isinstance(transactions_wrapper, dict):
                 raise ValueError(f"Dump {i} for account '{account}' missing 'transactions' dict.")
            
            txs = transactions_wrapper.get("booked")
            if not isinstance(txs, list):
                 raise ValueError(f"Dump {i} for account '{account}' missing 'booked' list in 'transactions'.")

            all_transactions.extend(txs)
        
        # Deduplication based on internalTransactionId
        unique_transactions = []
        seen_ids = set()
        
        for tx in all_transactions:
            if not isinstance(tx, dict):
                 raise ValueError(f"Found non-dict transaction in account '{account}'.")

            tx_id = tx.get("internalTransactionId")
            
            if not tx_id:
                raise ValueError(f"Transaction missing internalTransactionId in account '{account}'. Transaction dump: {json.dumps(tx)}")
            
            if tx_id not in seen_ids:
                seen_ids.add(tx_id)
                unique_transactions.append(tx)
        
        per_account_transactions[account] = unique_transactions

    return per_account_transactions