"""Tests for connection renewal.

Institution identifiers here are invented: which banks an installation uses is
not something the public repo should record.
"""

from renew_connections import (
    agreement_payload,
    institutions_in_use,
    render_qr,
    select_expired_institutions,
    select_targets,
)

ALPHA = "ALPHABANK_ALPHGB2LXXX"
BETA = "BETABANK_BETAGB2LXXX"
GAMMA = "GAMMABANK_GAMMGB2LXXX"


def test_expired_institution_is_selected():
    requisitions = [{"institution_id": ALPHA, "status": "EX", "created": "2026-06-14"}]
    assert select_expired_institutions(requisitions) == [ALPHA]


def test_linked_institution_is_not_selected():
    requisitions = [{"institution_id": ALPHA, "status": "LN", "created": "2026-07-11"}]
    assert select_expired_institutions(requisitions) == []


def test_pending_institution_is_not_selected():
    """A second requisition would leave two authorisation links in flight."""
    requisitions = [{"institution_id": ALPHA, "status": "CR", "created": "2026-09-13"}]
    assert select_expired_institutions(requisitions) == []


def test_pending_institution_survives_an_expired_predecessor():
    requisitions = [
        {"institution_id": ALPHA, "status": "EX", "created": "2026-06-14"},
        {"institution_id": ALPHA, "status": "CR", "created": "2026-09-13"},
    ]
    assert select_expired_institutions(requisitions) == []


def test_most_recent_requisition_decides_per_institution():
    """An institution renewed after an expiry must not be selected again."""
    requisitions = [
        {"institution_id": BETA, "status": "EX", "created": "2026-04-11"},
        {"institution_id": BETA, "status": "LN", "created": "2026-07-11"},
        {"institution_id": ALPHA, "status": "EX", "created": "2026-03-14"},
        {"institution_id": ALPHA, "status": "EX", "created": "2026-06-14"},
    ]
    assert select_expired_institutions(requisitions) == [ALPHA]


def test_order_of_input_does_not_matter():
    """The API does not promise a sort order, so selection must not depend on it."""
    newest_first = [
        {"institution_id": BETA, "status": "LN", "created": "2026-07-11"},
        {"institution_id": BETA, "status": "EX", "created": "2026-04-11"},
    ]
    assert select_expired_institutions(newest_first) == []


def test_multiple_expired_institutions_are_sorted():
    requisitions = [
        {"institution_id": GAMMA, "status": "EX", "created": "2026-04-11"},
        {"institution_id": BETA, "status": "EX", "created": "2026-04-11"},
    ]
    assert select_expired_institutions(requisitions) == [BETA, GAMMA]


def test_empty_requisition_list_selects_nothing():
    assert select_expired_institutions([]) == []


def test_institutions_in_use_requires_a_linked_account():
    """A requisition with no accounts never carried data, so it is not "in use"."""
    requisitions = [
        {"institution_id": ALPHA, "accounts": ["a"]},
        {"institution_id": BETA, "accounts": []},
        {"institution_id": GAMMA, "accounts": ["b", "c"]},
    ]
    assert institutions_in_use(requisitions) == [ALPHA, GAMMA]


def test_institutions_in_use_is_empty_without_accounts():
    assert institutions_in_use([{"institution_id": ALPHA, "accounts": []}]) == []


def test_named_institutions_win_over_everything_else():
    """Onboarding has nothing in use yet, so naming is the only way to start."""
    assert select_targets([], all_in_use=True, institutions=[BETA]) == [BETA]


def test_named_institutions_are_deduplicated():
    assert select_targets([], institutions=[BETA, BETA, ALPHA]) == [ALPHA, BETA]


def test_all_in_use_targets_institutions_with_accounts():
    requisitions = [
        {"institution_id": ALPHA, "accounts": ["a"], "status": "LN", "created": "x"},
        {"institution_id": BETA, "accounts": [], "status": "EX", "created": "x"},
    ]
    assert select_targets(requisitions, all_in_use=True) == [ALPHA]


def test_default_targets_only_expired_institutions():
    requisitions = [
        {"institution_id": ALPHA, "status": "EX", "created": "2026-06-14"},
        {"institution_id": BETA, "status": "LN", "created": "2026-07-11"},
    ]
    assert select_targets(requisitions) == [ALPHA]


def test_agreement_payload_requests_reconfirmation():
    """Reconfirmation is what lets the agreement be extended without full SCA."""
    terms = {"max_historical_days": 449, "access_valid_for_days": 730}
    payload = agreement_payload(ALPHA, terms)
    assert payload == {
        "institution_id": ALPHA,
        "max_historical_days": 449,
        "access_valid_for_days": 730,
        "access_scope": ["balances", "details", "transactions"],
        "reconfirmation": True,
    }


def test_agreement_payload_access_period_exceeds_the_sca_default():
    """GoCardless rejects reconfirmation at 90 days or fewer, so guard the invariant."""
    terms = {"max_historical_days": 449, "access_valid_for_days": 730}
    payload = agreement_payload(ALPHA, terms)
    assert payload["access_valid_for_days"] > 90
    assert payload["reconfirmation"] is True


def test_agreement_payload_raises_a_short_access_period_above_the_limit():
    """An institution reporting the 90-day default must still get a usable period."""
    terms = {"max_historical_days": 90, "access_valid_for_days": 90}
    payload = agreement_payload(ALPHA, terms)
    assert payload["access_valid_for_days"] == 91


def test_render_qr_uses_half_blocks_and_no_wide_characters():
    art = render_qr("https://example.com/authorise")
    lines = art.splitlines()
    assert len(lines) > 5
    assert set("".join(lines)) <= set("█▀▄ ")
    assert len({len(line) for line in lines}) == 1


def test_render_qr_is_square_in_module_terms():
    """Two module rows per text line, so the art is square bar one padding row."""
    art = render_qr("https://example.com/authorise")
    lines = art.splitlines()
    module_width = len(lines[0])
    module_height = len(lines) * 2
    assert module_height - module_width in (0, 1)


def test_render_qr_differs_for_different_urls():
    assert render_qr("https://example.com/a") != render_qr("https://example.com/b")
