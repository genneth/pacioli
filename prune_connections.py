"""Report the state of every bank connection, and delete the stale ones.

The report names the requisition currently in use for each institution, when
its reconfirmation falls due, and which requisitions and agreements are stale.
Nothing is deleted unless ``--apply`` is passed.

Deleting a requisition also deletes its end-user agreement, so the two are
handled together. Agreements that no requisition references are reported
separately: nothing can use them, but they still clutter the account.
"""

import argparse
import sys
from datetime import date, datetime, timedelta

from go_cardless_client import Client

# Reconfirmation falls due this long after acceptance, whatever the agreement's
# access period is. See the reconfirmation section of docs/gocardless.md.
RECONFIRMATION_WINDOW = timedelta(days=90)
DUE_SOON = timedelta(days=14)


def _current_rank(requisition):
    """Sort key for "which requisition is in use": live beats pending, then newest."""
    status_rank = {"LN": 2, "CR": 1}.get(requisition.get("status"), 0)
    return (status_rank, requisition.get("created", ""))


def select_current_connections(requisitions, agreements):
    """The requisition in use per institution, joined to its agreement.

    A pending requisition is reported when nothing is live yet, so that a fresh
    installation still shows what it is waiting to have authorised.
    """
    by_id = {agr["id"]: agr for agr in agreements}
    current = {}
    for req in requisitions:
        institution = req["institution_id"]
        if institution not in current or _current_rank(req) > _current_rank(current[institution]):
            current[institution] = req

    connections = []
    for institution, req in sorted(current.items()):
        agreement = by_id.get(req.get("agreement"), {})
        connections.append(
            {
                "institution_id": institution,
                "requisition_status": req.get("status"),
                "requisition_id": req["id"],
                "agreement_id": req.get("agreement"),
                "reconfirmation": agreement.get("reconfirmation"),
                "access_valid_for_days": agreement.get("access_valid_for_days"),
                "accepted": agreement.get("accepted"),
                "accounts": req.get("accounts", []),
            }
        )
    return connections


def reconfirmation_due(accepted, window=RECONFIRMATION_WINDOW):
    """When reconfirmation falls due, or None while the agreement is unaccepted."""
    if not accepted:
        return None
    return datetime.fromisoformat(accepted).date() + window


def format_connection(connection, today):
    fields = [
        f"{connection['institution_id']:24}",
        f"{connection['requisition_status']}",
        f"accounts={len(connection['accounts'])}",
    ]
    if not connection["reconfirmation"]:
        fields.append("NOT reconfirmable: next renewal needs a full bank login")
        return "  " + "  ".join(fields)

    fields.append(f"reconfirmable, access {connection['access_valid_for_days']}d")
    due = reconfirmation_due(connection["accepted"])
    if due is None:
        fields.append("reconfirmation starts once authorised")
    else:
        remaining = (due - today).days
        fields.append(f"reconfirm by {due} ({remaining}d)")
        if remaining <= DUE_SOON.days:
            fields.append("DUE SOON")
    return "  " + "  ".join(fields)


def select_stale_requisitions(requisitions):
    """Requisitions that are safe to delete.

    A pending (CR) requisition may still be authorised, so it is kept. Of the
    live (LN) ones only the newest per institution is kept, because an older
    live requisition has been superseded by a remake. Everything else has
    expired or been replaced.
    """
    by_institution = {}
    for req in requisitions:
        by_institution.setdefault(req["institution_id"], []).append(req)

    stale = []
    for reqs in by_institution.values():
        live = [req for req in reqs if req.get("status") == "LN"]
        newest_live = max(live, key=lambda req: req.get("created", ""), default=None)
        for req in reqs:
            if req.get("status") == "CR" or req is newest_live:
                continue
            stale.append(req)
    return sorted(stale, key=lambda req: (req["institution_id"], req.get("created", "")))


def select_orphan_agreements(agreements, requisitions):
    """Agreements no requisition references, so nothing can ever use them."""
    referenced = {req.get("agreement") for req in requisitions}
    return sorted(
        (agr for agr in agreements if agr["id"] not in referenced),
        key=lambda agr: agr.get("created", ""),
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually delete; without it this only reports what it would delete",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    client = Client()

    requisitions = client.get("requisitions/")
    if not requisitions:
        sys.exit("Failed to fetch requisitions.")
    requisition_list = requisitions.get("results", [])

    agreements = client.get("agreements/enduser/")
    if not agreements:
        sys.exit("Failed to fetch agreements.")
    agreement_list = agreements.get("results", [])

    today = date.today()
    connections = select_current_connections(requisition_list, agreement_list)
    print(f"{len(connections)} connection(s) in use")
    for connection in connections:
        print(format_connection(connection, today))

    stale = select_stale_requisitions(requisition_list)
    print(f"\n{len(requisition_list)} requisitions; {len(stale)} stale")
    for req in stale:
        print(
            f"  {req['institution_id']:24} {req.get('status')} "
            f"created {req.get('created', '?')[:10]}  {req['id']}"
        )

    if args.apply:
        for req in stale:
            if client.delete(f"requisitions/{req['id']}/") is None:
                print(f"! Failed to delete requisition {req['id']}")
        print(f"Deleted {len(stale)} stale requisition(s).")

    # Re-read: deleting a requisition takes its agreement with it.
    if args.apply:
        agreement_list = client.get("agreements/enduser/").get("results", [])
        requisition_list = client.get("requisitions/").get("results", [])
    orphans = select_orphan_agreements(agreement_list, requisition_list)
    print(f"\n{len(orphans)} orphan agreement(s) not referenced by any requisition")
    for agr in orphans:
        print(
            f"  {agr['institution_id']:24} reconfirmation={agr.get('reconfirmation')} "
            f"created {agr.get('created', '?')[:10]}  {agr['id']}"
        )

    if args.apply:
        for agr in orphans:
            if client.delete(f"agreements/enduser/{agr['id']}/") is None:
                print(f"! Failed to delete agreement {agr['id']}")
        print(f"Deleted {len(orphans)} orphan agreement(s).")

    if not args.apply:
        print("\nDry run. Re-run with --apply to delete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
