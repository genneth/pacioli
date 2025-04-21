import json
import datetime
import logging
from go_cardless_client import Client
from read_existing_transactions import read_existing_transactions


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
per_account_transactions = read_existing_transactions()

max_dates = {
    account: tran["bookingDate"].max().strftime("%Y-%m-%d")
    for account, tran in per_account_transactions.items()
}

yesterday = datetime.date.today() - datetime.timedelta(days=1)
yesterday_str = yesterday.strftime("%Y-%m-%d")

# THIS IS THE DELICATE BIT: doing this wrong could overwrite the existing data
for account, max_date in max_dates.items():
    if max_date >= yesterday_str:
        logging.getLogger().info(f"Account {account} is up to date.")
        continue
    try:
        with open(
            "raw/" + account + "/" + yesterday_str + ".json", "x"
        ) as f:  # notice the x instead of w
            dump = client.get(
                "accounts/" + account + "/transactions/",
                {
                    "date_from": max_date,  # deliberately overlap one day
                    "date_to": yesterday_str,
                },
            )
            logging.getLogger().info(
                f"Downloaded {len(dump['transactions']['booked'])} transaction(s) for {account} from {max_date} to {yesterday_str}."
            )
            json.dump(dump, f)
    except FileExistsError:
        logging.getLogger().error(
            f"File {yesterday_str} already exists for {account}. Skipping."
        )
        continue
