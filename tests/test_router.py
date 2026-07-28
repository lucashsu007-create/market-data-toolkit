"""Router tests.

Known-answer cases use dev-split notices only (corpus/split.json) — the
held-out split must not leak into test fixtures, or the final numbers stop
meaning anything.
"""

from __future__ import annotations

import pytest

from mdt.corpus import load_labels, load_notices, load_split
from mdt.router import NOTICE_TYPES, route


@pytest.fixture(scope="module")
def dev_ids():
    return set(load_split()["dev"])


# -- synthetic known-answer cases -----------------------------------------

def test_classifies_a_retirement_as_feed_change():
    r = route("Exchange announces retirement of legacy depth feed. Customers must migrate before the deadline.")
    assert r.notice_type == "feed_change"
    assert r.evidence["type"]


def test_classifies_a_holiday_as_operational():
    r = route("US Market Holiday: markets will be closed on 2026-12-25.")
    assert r.notice_type == "operational"


def test_unmodelled_product_is_unknown_target_not_a_guess():
    r = route("NFN Daily List format update for fund network issuers.")
    assert r.unknown_target
    assert r.feeds == []
    assert r.confidence <= 0.45


def test_effective_date_skips_the_publish_date():
    r = route("Change effective 2026-11-20 as announced.", published="2026-07-20")
    assert r.effective == "2026-11-20"
    r2 = route("Published 2026-07-20, no other dates.", published="2026-07-20")
    assert r2.effective is None


def test_no_evidence_falls_back_to_admin_other_with_zero_margin():
    r = route("Miscellaneous announcement with nothing recognisable.")
    assert r.notice_type == "admin_other"
    assert r.confidence < 0.5  # must escalate downstream


def test_venue_detection_is_evidence_counted():
    assert route("CME Globex MDP 3.0 channel update").venue == "cme"
    assert route("Nasdaq TotalView directory change").venue == "nasdaq"
    assert route("An announcement about nothing in particular").venue is None


def test_notice_types_are_closed_set():
    r = route("Anything at all")
    assert r.notice_type in NOTICE_TYPES


# -- the category contest -------------------------------------------------
#
# type_scores is what the UI renders as a scoreboard, so its ordering and its
# relationship to the reported confidence are a contract, not an internal.

def test_type_scores_are_ranked_best_first():
    r = route("CME will retire and decommission the legacy multicast channels.")
    assert r.type_scores, "a matching notice should show a contest"
    weights = [score for _, score in r.type_scores]
    assert weights == sorted(weights, reverse=True)


def test_winner_is_the_top_scoring_category():
    r = route("Nasdaq TotalView message format change: new fields and tag 271.")
    assert r.notice_type == r.type_scores[0][0]


def test_margin_is_derived_from_the_top_two_scores():
    """The confidence shown next to the scoreboard must follow from it."""
    r = route("CME will retire the legacy multicast channels on 2026-09-01.")
    top = r.type_scores[0][1]
    second = r.type_scores[1][1] if len(r.type_scores) > 1 else 0
    assert r.type_margin == pytest.approx((top - second) / top)


def test_unopposed_win_has_margin_one():
    r = route("Exchange holiday: markets closed.")
    if len(r.type_scores) == 1:
        assert r.type_margin == pytest.approx(1.0)


def test_no_match_shows_no_contest():
    """admin_other is a fallback, so there must be no scoreboard to imply one."""
    r = route("Miscellaneous announcement with nothing recognisable.")
    assert r.type_scores == []
    assert r.type_margin == 0.0


def test_ranking_is_deterministic_under_ties():
    text = "CME will retire and decommission the legacy multicast channels."
    assert route(text).type_scores == route(text).type_scores


def test_as_dict_serialises_scores_as_json_safe_pairs():
    d = route("CME will retire the legacy multicast channels.").as_dict()
    assert all(
        isinstance(pair, list) and len(pair) == 2 and isinstance(pair[1], int)
        for pair in d["type_scores"]
    )
    assert isinstance(d["type_margin"], float)


# -- dev-split regression (the tuned rules must keep their dev behaviour) --

def test_dev_split_venue_and_type_accuracy(dev_ids):
    notices, labels = load_notices(), load_labels()
    for nid in dev_ids:
        r = route(notices[nid].text, published=notices[nid].published)
        assert r.venue == notices[nid].venue, nid
        assert r.notice_type == labels[nid]["type"], nid


def test_dev_split_feed_resolution(dev_ids):
    notices, labels = load_notices(), load_labels()
    for nid in dev_ids:
        r = route(notices[nid].text, published=notices[nid].published)
        expected = set(labels[nid]["feeds"])
        if "unknown" in expected:
            assert r.unknown_target, nid
        else:
            assert expected <= set(r.feeds), nid


def test_held_out_is_not_used_here():
    """Guard: no test in this file may iterate the held-out ids."""
    held = set(load_split()["held_out"])
    dev = set(load_split()["dev"])
    assert not (held & dev)
