"""Layer 3 — decision: priority, owner routing, escalation.

Consumes the router's output and the estate. The safety property this layer is
built around: **a notice must never be auto-cleared because we failed to
understand it.** Low confidence and unresolvable targets escalate to a human,
always.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .impact import resolve_impact
from .model import Estate
from .router import RouterResult

PRIORITIES = ("low", "medium", "high")

# Base priority per notice type (dev-set reasoning: feed changes force work on
# a deadline; format changes usually need parser attention; the rest is mostly
# awareness).
_BASE = {
    "feed_change": "medium",
    "format_change": "medium",
    "operational": "low",
    "regulatory": "low",
    "reference_data": "low",
    "admin_other": "low",
}

# Language that signals mandatory action rather than information.
_IMPERATIVE = re.compile(
    r"\bmust\b|\brequired\b|\bdiscontinu|\bretire|\bno longer\b|\bdeadline\b",
    re.IGNORECASE,
)

CONFIDENCE_FLOOR = 0.5


def _bump(priority: str, steps: int = 1) -> str:
    idx = min(PRIORITIES.index(priority) + steps, len(PRIORITIES) - 1)
    return PRIORITIES[idx]


@dataclass
class Ticket:
    notice_type: str
    priority: str
    owners: list[str]
    review_required: bool
    reasons: list[str] = field(default_factory=list)
    blast_radius: int = 0
    feeds: list[str] = field(default_factory=list)
    effective: str | None = None
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "notice_type": self.notice_type,
            "priority": self.priority,
            "owners": self.owners,
            "review_required": self.review_required,
            "reasons": self.reasons,
            "blast_radius": self.blast_radius,
            "feeds": self.feeds,
            "effective": self.effective,
            "confidence": self.confidence,
        }


def decide(estate: Estate, routed: RouterResult, text: str) -> Ticket:
    reasons: list[str] = []
    priority = _BASE.get(routed.notice_type, "low")

    # Impact over every resolved feed
    owners: set[str] = set()
    blast = 0
    critical_feed = False
    for feed_id in routed.feeds:
        impact = resolve_impact(estate, feed_id)
        owners.update(impact.owners)
        blast += impact.blast_radius
        node = estate.nodes.get(feed_id)
        if node is not None and node.criticality == "high":
            critical_feed = True

    # Calendar notices (holidays, market closures) are routine regardless of
    # which feed they mention — a closure of a critical feed is still just a
    # closure. Dev-set evidence: every holiday notice is labelled low.
    calendar = bool(re.search(r"\bholiday\b|\bmarkets? (?:will be )?closed\b", text, re.IGNORECASE))

    if not calendar:
        if _IMPERATIVE.search(text):
            priority = _bump(priority)
            reasons.append("mandatory-action language")
        if critical_feed and routed.notice_type in ("feed_change", "format_change", "operational"):
            priority = _bump(priority)
            reasons.append("touches a criticality-high feed")
        # Threshold sits above the blast radius of any single feed in this
        # estate (max 10): only multi-feed notices trip it, so it flags genuine
        # breadth instead of re-flagging every CME notice.
        if blast >= 12:
            priority = _bump(priority)
            reasons.append(f"wide blast radius ({blast} nodes)")

    # Escalation: unknowns and low confidence always go to a human; so does
    # anything that ended up high priority.
    review = False
    if routed.unknown_target:
        review = True
        reasons.append("names a product the estate does not model")
    if routed.confidence < CONFIDENCE_FLOOR:
        review = True
        reasons.append(f"router confidence {routed.confidence:.2f} below floor")
    if priority == "high":
        review = True
        reasons.append("high priority requires sign-off")

    return Ticket(
        notice_type=routed.notice_type,
        priority=priority,
        owners=sorted(owners),
        review_required=review,
        reasons=reasons,
        blast_radius=blast,
        feeds=routed.feeds,
        effective=routed.effective,
        confidence=routed.confidence,
    )
