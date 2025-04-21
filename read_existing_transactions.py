import os
import json
import logging
import polars as pl
from polars import col as C

### Read existing transactions from raw
def read_existing_transactions() -> dict[str, pl.DataFrame]:
    # load existing json dumps
    raw_dumps: dict[str, list] = {}
    for account in os.listdir("raw"):
        raw_dumps[account] = []
        for file in os.listdir("raw/" + account):
            if not file.endswith(".json"):
                logging.getLogger().warning(
                    f"File {file} is not a JSON file. Skipping."
                )
                continue
            with open("raw/" + account + "/" + file, "r") as f:
                raw_dumps[account].append(json.load(f))
                logging.getLogger().info(f"Loaded {file} for account {account}.")

    # partially normalise
    per_account_transactions = {
        account: pl.concat(
            [
                pl.from_dicts(dump["transactions"]["booked"], infer_schema_length=None)
                .with_columns(
                    C("bookingDate").cast(pl.Date),
                    C("valueDate").cast(pl.Date),
                    C("bookingDateTime").cast(pl.Datetime),
                    C("valueDateTime").cast(pl.Datetime),
                    C("transactionAmount").struct.unnest(),
                )
                .with_columns(
                    C("amount").cast(pl.Float32),
                )
                for dump in dumps
            ],
            how="diagonal_relaxed", # allow for missing fields in some of the shorter top-ups
        )
        .unique() # remove the one-day overlap in update_transactions.py
        .sort("bookingDateTime", descending=True)
        for (account, dumps) in raw_dumps.items()
    }

    return per_account_transactions
