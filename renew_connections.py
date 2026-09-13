"""Renew GoCardless bank connections as reconfirmable end-user agreements.

Institutions are discovered from the API, so this file holds no account,
agreement, or requisition identifiers.

An end-user agreement created with ``reconfirmation`` set can be extended once
it expires without the end user repeating strong customer authentication: the
API returns a URL for them to confirm. GoCardless only allows that above the
90-day SCA default, so the access period is requested at the institution's
``max_access_valid_for_days_reconfirmation``.
"""

import argparse
import datetime
import sys
import time

import polars as pl
import qrcode

from go_cardless_client import Client

ACCESS_SCOPE = ["balances", "details", "transactions"]
POLL_INTERVAL_SECONDS = 5
SCA_DEFAULT_DAYS = 90


def institutions_in_use(requisitions):
    """Institutions with at least one linked account, i.e. ones actually in use."""
    return sorted({req["institution_id"] for req in requisitions if req.get("accounts")})


def select_expired_institutions(requisitions):
    """Institutions whose most recent requisition has expired.

    GoCardless expires an End User Agreement 90 days after consent, after which
    the end user must re-authorise. Deriving the target list from the API keeps
    it correct without anyone remembering to edit it.

    A pending requisition is left alone. It is waiting on the end user, not
    broken, and acting on it would leave two authorisation links in flight.
    """
    latest = {}
    for req in requisitions:
        inst_id = req["institution_id"]
        if inst_id not in latest or req.get("created", "") > latest[inst_id].get(
            "created", ""
        ):
            latest[inst_id] = req
    return sorted(inst for inst, req in latest.items() if req.get("status") == "EX")


def select_targets(requisitions, *, all_in_use=False, institutions=None):
    """Which institutions to connect, most explicit request first.

    Naming institutions directly is the only form that works during onboarding,
    where nothing is in use yet and there is nothing to derive a target from.
    """
    if institutions:
        return sorted(set(institutions))
    if all_in_use:
        return institutions_in_use(requisitions)
    return select_expired_institutions(requisitions)


def agreement_payload(institution_id, terms):
    """Request the longest access period the institution allows with reconfirmation.

    Reconfirmation is rejected at or below the 90-day SCA default, so the two
    fields have to move together.
    """
    access_valid_for_days = max(terms["access_valid_for_days"], SCA_DEFAULT_DAYS + 1)
    return {
        "institution_id": institution_id,
        "max_historical_days": terms["max_historical_days"],
        "access_valid_for_days": access_valid_for_days,
        "access_scope": ACCESS_SCOPE,
        "reconfirmation": True,
    }


def render_qr(data, border=2):
    """Render a QR code using half-block characters, one column per module.

    Nothing touches the filesystem. Two module rows per text line keeps the
    code narrow enough to survive being pasted into a chat window.
    """
    qr = qrcode.QRCode(border=border, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(data)
    qr.make(fit=True)

    rows = qr.get_matrix()
    if len(rows) % 2:
        rows.append([False] * len(rows[0]))

    return "\n".join(
        "".join(
            "█" if top and bottom else "▀" if top else "▄" if bottom else " "
            for top, bottom in zip(upper, lower, strict=True)
        )
        for upper, lower in zip(rows[::2], rows[1::2], strict=True)
    )


def institution_terms(institutions, institution_id):
    """Terms to request for an institution, preferring the reconfirmable maximum."""
    row = institutions.filter(pl.col("id") == institution_id)
    if row.height == 0:
        return None

    def value(column, fallback):
        if column not in row.columns:
            return fallback
        found = row.select(column).item(0, 0)
        return fallback if found is None else int(found)

    return {
        "name": row.select("name").item(0, 0),
        "max_historical_days": value("transaction_total_days", 730),
        "access_valid_for_days": value(
            "max_access_valid_for_days_reconfirmation", SCA_DEFAULT_DAYS
        ),
    }


def create_connection(client, institution_id, terms):
    """Create a reconfirmable agreement and a requisition that links to it."""
    agreement = client.post(
        "agreements/enduser/", agreement_payload(institution_id, terms)
    )
    if not agreement:
        return None

    reference = f"{terms['name'].split()[0]}_reconfirmed_{datetime.date.today():%Y_%m}"
    requisition = client.post(
        "requisitions/",
        {
            "institution_id": institution_id,
            "agreement": agreement["id"],
            "redirect": "https://google.com",
            "reference": reference,
        },
    )
    if not requisition:
        return None

    return {
        "name": terms["name"],
        "institution_id": institution_id,
        "requisition_id": requisition["id"],
        "link": requisition["link"],
        "status": requisition.get("status", "CR"),
        "accounts": [],
    }


def poll_until_linked(client, created):
    """Report status until every new requisition has linked, or the user aborts."""
    print("\nPolling for authorisation status... (Press Ctrl+C to abort)")
    try:
        while True:
            data = client.get("requisitions/")
            if not data:
                print("Failed to fetch requisition status; retrying in 5s...")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            by_id = {req["id"]: req for req in data.get("results", [])}
            statuses = []
            all_linked = True
            for entry in created:
                live = by_id.get(entry["requisition_id"])
                if live:
                    entry["status"] = live.get("status", entry["status"])
                    entry["accounts"] = live.get("accounts", [])
                if entry["status"] != "LN":
                    all_linked = False
                statuses.append(f"{entry['name']}: {entry['status']}")

            print(
                f"[{datetime.datetime.now():%H:%M:%S}] " + " | ".join(statuses),
                end="\r",
            )

            if all_linked:
                print("\n\nAll connections linked.")
                return created

            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nPolling aborted. Re-run to check status.")
        return created


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="remake every connection in use, not only the expired ones",
    )
    parser.add_argument(
        "--institution",
        action="append",
        default=[],
        metavar="ID",
        help="connect this institution; repeatable, and required when nothing is in use yet",
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="print the authorisation links and exit instead of waiting",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    print("Initialising GoCardless client...")
    client = Client()

    data = client.get("requisitions/")
    if not data:
        sys.exit("Failed to fetch requisitions; cannot determine what to renew.")
    requisitions = data.get("results", [])

    targets = select_targets(
        requisitions,
        all_in_use=args.all,
        institutions=args.institution,
    )
    if not targets:
        print("Nothing to do. Every connection is linked.")
        return 0

    print(f"Connecting {len(targets)} institution(s): {', '.join(targets)}\n")

    created = []
    for institution_id in targets:
        terms = institution_terms(client.institutions, institution_id)
        if terms is None:
            print(f"! {institution_id} is not in the institutions list; skipping.")
            continue

        entry = create_connection(client, institution_id, terms)
        if entry is None:
            print(f"! Failed to create a requisition for {institution_id}; skipping.")
            continue

        created.append(entry)
        print("=" * 68)
        print(f"{entry['name']} ({institution_id})")
        print("=" * 68)
        print(f"Authorise at: {entry['link']}\n")
        print(render_qr(entry["link"]))
        print()

    if not created:
        sys.exit("No requisitions were created.")

    if args.no_poll:
        return 0

    poll_until_linked(client, created)
    return 0


if __name__ == "__main__":
    sys.exit(main())
