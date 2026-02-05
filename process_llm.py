import argparse
import logging
import os

import dotenv
from google import genai

from transaction_loader import load_transactions
from transaction_manager import TransactionManager


def main():
    parser = argparse.ArgumentParser(description="Process transactions with Gemini LLM.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-processing of already cached AI labels.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)8s %(message)s"
    )

    # Load environment variables
    dotenv.load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logging.error("GOOGLE_API_KEY not found in environment.")
        return

    # 1. Initialize Clients
    genai_client = genai.Client(api_key=api_key)
    tm = TransactionManager(genai_client=genai_client)

    # 2. Load Transactions
    logging.info("Loading transactions...")
    rows = load_transactions()

    # 3. Batch Process
    tm.batch_process_llm(rows, force_update=args.force)

    logging.info("LLM processing complete.")


if __name__ == "__main__":
    main()
