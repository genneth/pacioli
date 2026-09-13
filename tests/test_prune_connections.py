"""Tests for connection pruning.

Institution identifiers here are invented: which banks an installation uses is
not something the public repo should record.
"""

from prune_connections import select_orphan_agreements, select_stale_requisitions

ALPHA = "ALPHABANK_ALPHGB2LXXX"
BETA = "BETABANK_BETAGB2LXXX"


def req(institution, status, created, identifier="r", accounts=None):
    return {
        "id": identifier,
        "institution_id": institution,
        "status": status,
        "created": created,
        "accounts": accounts or [],
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
