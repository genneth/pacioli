"""Tests for connection pruning.

Institution identifiers here are invented: which banks an installation uses is
not something the public repo should record.
"""

from datetime import date

from prune_connections import (
    reconfirmation_due,
    select_current_connections,
    select_orphan_agreements,
    select_stale_requisitions,
)

ALPHA = "ALPHABANK_ALPHGB2LXXX"
BETA = "BETABANK_BETAGB2LXXX"


def req(institution, status, created, identifier="r", accounts=None, agreement=None):
    return {
        "id": identifier,
        "institution_id": institution,
        "status": status,
        "created": created,
        "accounts": accounts or [],
        "agreement": agreement,
    }


def agr(identifier, accepted=None, reconfirmation=True, access_valid_for_days=730):
    return {
        "id": identifier,
        "created": "2026-09-13T06:23:16Z",
        "accepted": accepted,
        "reconfirmation": reconfirmation,
        "access_valid_for_days": access_valid_for_days,
    }


def test_expired_requisition_is_stale():
    requisitions = [req(ALPHA, "EX", "2026-06-14T09:33:33Z", "old")]
    assert [r["id"] for r in select_stale_requisitions(requisitions)] == ["old"]


def test_lone_live_requisition_is_kept():
    requisitions = [req(BETA, "LN", "2026-07-11T11:35:10Z", "live")]
    assert select_stale_requisitions(requisitions) == []


def test_pending_requisition_is_kept_even_when_expired_ones_exist():
    requisitions = [
        req(ALPHA, "EX", "2026-06-14T09:33:33Z", "old"),
        req(ALPHA, "CR", "2026-09-13T05:53:25Z", "pending"),
    ]
    assert [r["id"] for r in select_stale_requisitions(requisitions)] == ["old"]


def test_live_requisition_survives_while_a_remake_is_only_pending():
    """Deleting the live one here would cut off a working connection."""
    requisitions = [
        req(BETA, "LN", "2026-07-11T11:35:10Z", "live"),
        req(BETA, "CR", "2026-09-13T05:53:25Z", "pending"),
    ]
    assert select_stale_requisitions(requisitions) == []


def test_older_live_requisition_is_stale_once_the_remake_links():
    requisitions = [
        req(BETA, "LN", "2026-07-11T11:35:10Z", "old-live"),
        req(BETA, "LN", "2026-09-13T05:53:25Z", "new-live"),
    ]
    assert [r["id"] for r in select_stale_requisitions(requisitions)] == ["old-live"]


def test_institutions_are_pruned_independently():
    requisitions = [
        req(BETA, "LN", "2026-07-11T11:35:10Z", "beta-live"),
        req(ALPHA, "EX", "2026-06-14T09:33:33Z", "alpha-old"),
    ]
    assert [r["id"] for r in select_stale_requisitions(requisitions)] == ["alpha-old"]


def test_no_requisitions_is_empty():
    assert select_stale_requisitions([]) == []


def test_orphan_agreement_is_found():
    agreements = [{"id": "a1", "created": "2026-09-13T05:00:00Z"}]
    assert [a["id"] for a in select_orphan_agreements(agreements, [])] == ["a1"]


def test_referenced_agreement_is_not_orphaned():
    agreements = [{"id": "a1", "created": "2026-09-13T05:00:00Z"}]
    requisitions = [{"id": "r1", "agreement": "a1"}]
    assert select_orphan_agreements(agreements, requisitions) == []


def test_orphans_are_sorted_by_creation():
    agreements = [
        {"id": "b", "created": "2026-09-13T05:00:00Z"},
        {"id": "a", "created": "2026-01-01T05:00:00Z"},
    ]
    assert [a["id"] for a in select_orphan_agreements(agreements, [])] == ["a", "b"]


def test_current_connection_carries_its_agreement_terms():
    requisitions = [req(ALPHA, "LN", "2026-09-13T06:23:16Z", "r1", ["acc"], "a1")]
    agreements = [agr("a1", accepted="2026-09-13T06:29:19Z")]

    (connection,) = select_current_connections(requisitions, agreements)

    assert connection["institution_id"] == ALPHA
    assert connection["requisition_status"] == "LN"
    assert connection["agreement_id"] == "a1"
    assert connection["reconfirmation"] is True
    assert connection["access_valid_for_days"] == 730
    assert connection["accounts"] == ["acc"]


def test_pending_connection_is_reported_while_nothing_is_live():
    """Onboarding has no live requisition yet, but still needs the state shown."""
    requisitions = [req(BETA, "CR", "2026-09-13T05:53:25Z", "pending", agreement="a1")]

    (connection,) = select_current_connections(requisitions, [agr("a1")])

    assert connection["requisition_status"] == "CR"


def test_live_connection_outranks_a_pending_remake():
    requisitions = [
        req(BETA, "CR", "2026-09-13T05:53:25Z", "pending", agreement="a2"),
        req(BETA, "LN", "2026-07-11T11:35:10Z", "live", agreement="a1"),
    ]

    (connection,) = select_current_connections(requisitions, [agr("a1"), agr("a2")])

    assert connection["requisition_id"] == "live"


def test_newest_live_connection_is_the_current_one():
    requisitions = [
        req(BETA, "LN", "2026-07-11T11:35:10Z", "old-live", agreement="a1"),
        req(BETA, "LN", "2026-09-13T05:53:25Z", "new-live", agreement="a2"),
    ]

    (connection,) = select_current_connections(requisitions, [agr("a1"), agr("a2")])

    assert connection["requisition_id"] == "new-live"


def test_each_institution_gets_its_own_connection():
    requisitions = [
        req(BETA, "LN", "2026-07-11T11:35:10Z", "beta", agreement="a1"),
        req(ALPHA, "LN", "2026-06-14T09:33:33Z", "alpha", agreement="a2"),
    ]

    connections = select_current_connections(requisitions, [agr("a1"), agr("a2")])

    assert [c["institution_id"] for c in connections] == [ALPHA, BETA]


def test_connection_survives_a_missing_agreement():
    """A dangling agreement reference must not hide the connection itself."""
    requisitions = [req(ALPHA, "LN", "2026-09-13T06:23:16Z", "r1", agreement="gone")]

    (connection,) = select_current_connections(requisitions, [])

    assert connection["reconfirmation"] is None
    assert connection["accepted"] is None


def test_reconfirmation_falls_due_90_days_after_acceptance():
    assert reconfirmation_due("2026-09-13T06:29:19.563226Z") == date(2026, 12, 12)


def test_unaccepted_agreement_has_no_reconfirmation_date():
    assert reconfirmation_due(None) is None
