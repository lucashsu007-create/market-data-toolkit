"""Decision-layer tests. The property that matters most: nothing the router
failed to understand may be silently cleared."""

from __future__ import annotations

import pytest

from mdt.decision import CONFIDENCE_FLOOR, decide
from mdt.model import Edge, Estate, Node
from mdt.router import RouterResult


def make_estate() -> Estate:
    return Estate(
        nodes={
            "f": Node(id="f", type="feed", name="f", owner="ops", criticality="high"),
            "d": Node(id="d", type="dataset", name="d", owner="ops"),
            "s": Node(id="s", type="system", name="s", owner="pricing"),
        },
        edges=[
            Edge("f", "d", "provides"),
            Edge("d", "s", "consumed_by"),
        ],
    )


def routed(**kw) -> RouterResult:
    base = dict(venue="nasdaq", notice_type="operational", effective=None,
                feeds=[], unknown_products=[], confidence=0.9, evidence={})
    base.update(kw)
    return RouterResult(**base)


# -- escalation safety -----------------------------------------------------

def test_unknown_target_always_escalates():
    t = decide(make_estate(), routed(unknown_products=["mystery"], confidence=0.9), "text")
    assert t.review_required
    assert any("does not model" in r for r in t.reasons)


def test_low_confidence_always_escalates():
    t = decide(make_estate(), routed(confidence=CONFIDENCE_FLOOR - 0.01), "text")
    assert t.review_required


def test_high_priority_always_escalates():
    t = decide(make_estate(), routed(notice_type="feed_change", feeds=["f"]),
               "the legacy feed will be discontinued")
    assert t.priority == "high"
    assert t.review_required


def test_routine_confident_notice_is_cleared():
    t = decide(make_estate(), routed(notice_type="regulatory", feeds=["f"]),
               "informational filing, no action")
    assert not t.review_required
    assert t.priority == "low"


# -- priority rules --------------------------------------------------------

def test_imperative_language_bumps_priority():
    quiet = decide(make_estate(), routed(notice_type="format_change", feeds=["f"]),
                   "fields are being added")
    loud = decide(make_estate(), routed(notice_type="format_change", feeds=["f"]),
                  "consumers must update parsers")
    assert quiet.priority != "low" or loud.priority != "low"
    order = ["low", "medium", "high"]
    assert order.index(loud.priority) >= order.index(quiet.priority)


def test_calendar_notices_stay_low_even_on_critical_feeds():
    """A holiday closure of a critical feed is still just a closure."""
    t = decide(make_estate(), routed(notice_type="operational", feeds=["f"]),
               "US Market Holiday: markets will be closed on 2026-12-25")
    assert t.priority == "low"
    assert not t.review_required


def test_owners_come_from_impact_not_just_the_feed():
    t = decide(make_estate(), routed(notice_type="feed_change", feeds=["f"]),
               "feed retirement, migrate now")
    assert t.owners == ["ops", "pricing"]
    # feed + dataset + system: resolve_impact counts the origin feed itself
    assert t.blast_radius == 3


def test_ticket_serialises():
    t = decide(make_estate(), routed(feeds=["f"]), "text")
    d = t.as_dict()
    assert set(d) >= {"notice_type", "priority", "owners", "review_required",
                      "reasons", "blast_radius", "feeds", "confidence"}
