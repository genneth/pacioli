"""
Safe Transaction Log Updater

This script downloads new transactions and appends them to the 'raw/' directory as
immutable daily JSON files.

Safety & Idempotency Principles:
1.  **Append-Only:** We never modify existing JSON files. We only create new files for
    the current target date.
2.  **Exclusive Creation:** We use file mode "x" to guarantee we don't accidentally
    overwrite data. If a file exists, we skip it.
3.  **Atomic-ish Writes:** If the API fetch fails or the script crashes mid-write,
    the specific `except` block ensures the partial/empty file is deleted. This
    prevents "zombie" files from blocking future runs.
4.  **Data Overlap:** We deliberately overlap the fetch window with the last known
    transaction date. This ensures we don't miss transactions that might have settled
    late on that day. The reading logic (`read_existing_transactions.py`) is responsible
    for deduplicating these overlapping records.
"""

import datetime
import json
import logging
import os

from go_cardless_client import Client
from transaction_loader import load_transactions

# helps w/ debugging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
# Remove all existing handlers (to prevent duplicate logging)
if logger.hasHandlers():
    logger.handlers.clear()
formatter = logging.Formatter("%(asctime)s %(levelname)8s %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# initialize the client, hopefully fully authenticated + working
client = Client()

# existing data
transactions = load_transactions()

max_dates = {}
for t in transactions:
    if t.account_id not in max_dates or t.booking_date > max_dates[t.account_id]:
        max_dates[t.account_id] = t.booking_date

yesterday = datetime.date.today() - datetime.timedelta(days=1)

# THIS IS THE DELICATE BIT: doing this wrong could overwrite the existing data
for account, max_date in max_dates.items():
    if max_date >= yesterday:
        logging.getLogger().info(f"Account {account} is up to date.")
        continue

    yesterday_str = yesterday.strftime("%Y-%m-%d")
    max_date_str = max_date.strftime("%Y-%m-%d")
    file_path = "raw/" + account + "/" + yesterday_str + ".json"
    try:
        # Use exclusive creation mode ("x") to ensure we never overwrite existing data.
        # This makes the script idempotent and safe to re-run if it fails mid-process.
        with open(file_path, "x") as f:
            dump = client.get(
                "accounts/" + account + "/transactions/",
                {
                    # Deliberately overlap with the last known date.
                    # We do this because bank settlement times can vary, and we might
                    # have missed a transaction late in the day on the previous run.
                    # Downstream consumers (transaction_loader.py) MUST handle
                    # deduplication.
                    "date_from": max_date_str,
                    "date_to": yesterday_str,
                },
            )
            if not dump:
                raise ValueError("No data returned from API")

            logging.getLogger().info(
                f"Downloaded {len(dump['transactions']['booked'])} transaction(s) for "
                f"{account} from {max_date} to {yesterday_str}."
            )
            json.dump(dump, f)
    except FileExistsError:
        logging.getLogger().error(
            f"File {yesterday_str} already exists for {account}. Skipping."
        )
        continue
    except Exception as e:
        logging.getLogger().error(f"Failed to update {account}: {e}")
        # Atomic Cleanup:
        # If ANY error occurs (network, disk full, invalid JSON), we must delete the
        # file. Otherwise, we leave a 0-byte or partial 'zombie' file that blocks
        # future runs (due to 'x' mode).
        if os.path.exists(file_path):
            os.remove(file_path)
