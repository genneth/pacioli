"""Delete stale GoCardless requisitions and the agreements they own.

Nothing is deleted unless ``--apply`` is passed, so the default run is a report.

Deleting a requisition also deletes its end-user agreement, so the two are
handled together. Agreements that no requisition references are reported
separately: nothing can use them, but they still clutter the account.
"""

import argparse
import sys

from go_cardless_client import Client


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

    stale = select_stale_requisitions(requisition_list)
    print(f"{len(requisition_list)} requisitions; {len(stale)} stale")
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
    agreements = client.get("agreements/enduser/")
    if not agreements:
        sys.exit("Failed to fetch agreements.")
    remaining_requisitions = (
        client.get("requisitions/").get("results", []) if args.apply else requisition_list
    )
    orphans = select_orphan_agreements(agreements.get("results", []), remaining_requisitions)
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
