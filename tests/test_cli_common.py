import json

import cli_common


def test_load_enriched_returns_rows_manager_and_dataframe(tmp_path):
    raw = tmp_path / "raw" / "acc1"
    raw.mkdir(parents=True)
    dump = {
        "transactions": {
            "booked": [
                {
                    "internalTransactionId": "t1",
                    "bookingDate": "2026-07-01",
                    "transactionAmount": {"amount": "-2.38", "currency": "GBP"},
                    "creditorName": "Google Cloud",
                }
            ]
        }
    }
    (raw / "2026-07-02.json").write_text(json.dumps(dump))
    data = tmp_path / "data"
    data.mkdir()

    rows, tm, df = cli_common.load_enriched(
        raw_dir=str(tmp_path / "raw"), data_dir=str(data)
    )

    assert len(rows) == 1
    assert df.height == 1
    assert df["counterparty"][0] == "Google Cloud"
    # Enrichment must have run transfer detection (no hidden-state warning later)
    assert tm._transfers_detected
