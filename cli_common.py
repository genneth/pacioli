"""Shared plumbing for the CLI scripts.

Every script needs the same three things: consistent logging, the
load-transactions/manager/enrich pipeline, and the CSV filename contract between
enrich_transactions.py (writer) and generate_spending_viz.py (reader). Keeping
them here stops the scripts from drifting apart.
"""

import logging

import polars as pl

from transaction_loader import Transaction, load_transactions
from transaction_manager import DATA_DIR, TransactionManager

ALL_TRANSACTIONS_CSV = "all_transactions.csv"
ENRICHED_CSV = "enriched_transactions.csv"


def setup_logging(level: int = logging.INFO) -> None:
    """One logging config for all scripts.

    Agent-facing scripts (find_uncategorized, test_pattern, ...) pass
    logging.WARNING so their stdout stays parseable; pipeline scripts use the
    INFO default.
    """
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)8s %(message)s")


def load_enriched(
    raw_dir: str = "raw", data_dir: str = DATA_DIR
) -> tuple[list[Transaction], TransactionManager, pl.DataFrame]:
    """Load raw transactions, build the manager, and enrich — the standard triple."""
    rows = load_transactions(raw_dir)
    tm = TransactionManager(data_dir)
    return rows, tm, tm.enrich_transactions(rows)
