"""Layer 1 — deterministic notice router.

Classifies a raw notice (title + summary text) into venue, notice type, effective
date and affected estate feeds, with an evidence-backed confidence. Rules were
written against the corpus **dev split only** (see corpus/split.json, frozen
before this file existed); the held-out split is scored once by evaluate.py.

Design choice: weighted keyword evidence with a margin-based confidence, not
first-match-wins. Every hit is recorded, so a wrong answer can be traced to the
rule that produced it — diagnosability is the point of a rules baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NOTICE_TYPES = (
    "feed_change",      # migrations, retirements, new channels, connectivity
    "format_change",    # message/field/schema/directory format changes
    "operational",      # capacity, testing, schedules, holidays
    "regulatory",       # SEC actions, rule relief, exemption filings
    "reference_data",   # listings, transfers, symbol changes
    "admin_other",      # governance/administrative, no feed impact
)

# --- rule tables (tuned on dev only) --------------------------------------

_VENUE_RULES: dict[str, tuple[str, ...]] = {
    "nasdaq": ("nasdaq", "nfn", "utp", "uqdf", "utdf", "totalview", "sip"),
    "cme": ("cme", "globex", "mdp", "brokertec", "ebs"),
}

# (pattern, weight) — patterns are matched case-insensitively on title+summary.
_TYPE_RULES: dict[str, tuple[tuple[str, int], ...]] = {
    "feed_change": (
        (r"\bretire", 3), (r"\bdiscontinu", 3), (r"\bmigrat", 3),
        (r"\bnew (?:market data )?multicast", 3), (r"\bmulticast channels?\b", 2),
        (r"\bno longer (?:carry|support)", 3), (r"\bdecommission", 3),
        (r"\bupgrade to \d+Gbps", 2), (r"\bmarket segments?\b", 1),
    ),
    "format_change": (
        (r"\bformat\b", 3), (r"\bfields?\b", 2), (r"\bmessages?\b", 2),
        (r"\bdirectory\b", 2), (r"\bschema\b", 3), (r"\btag \d+", 3),
        (r"\bdecimals?\b", 1), (r"\bmessage codes?\b", 2),
    ),
    "operational": (
        (r"\bholiday\b", 4), (r"\bmarkets? (?:will be )?closed\b", 3),
        (r"\btest(?:ing)? (?:schedule|calendar|transmissions)\b", 3),
        (r"\bbandwidth\b", 3), (r"\bcapacity\b", 2), (r"\bfailover\b", 3),
        (r"\bpackets?-per-second\b", 3), (r"\bthreshold\b", 2),
        (r"\boperating schedule\b", 3), (r"\b23x5\b|\b23/5\b|\b23 hours\b", 2),
        (r"\bmaintenance window", 2),
    ),
    "regulatory": (
        (r"\bsec\b", 3), (r"\bregulation\b", 2), (r"\bexempt", 3),
        (r"\brelief\b", 3), (r"\bcompliance\b", 2), (r"\brule\b", 1),
    ),
    "reference_data": (
        (r"\blisting and trading\b", 4), (r"\btransfers? from\b", 3),
        (r"\bticker\b", 2), (r"\bsymbol change\b", 3),
        (r"\bipo\b|\binitial public offering\b", 3), (r"\bwhen-issued\b", 2),
        (r"\bglobal select\b", 2),
    ),
    "admin_other": (
        (r"\brfp\b", 3), (r"\badministrator\b", 2), (r"\bgovernance\b", 2),
    ),
}

# Product mentions → estate feed ids. None = a real product the estate does not
# model; resolving to "we don't know this one" is a first-class outcome.
_FEED_RULES: tuple[tuple[str, str | None], ...] = (
    (r"\btotalview\b|\blevel 2\b|\bglimpse\b|\bnasdaq basic\b|\bnoiview\b|\bnois\b", "nasdaq_totalview"),
    (r"\butp\b|\buqdf\b|\butdf\b|\bconsolidated (?:data|feed|tape)\b|\bsips?\b|\bredistributors?\b", "utp_sip"),
    (r"\bmdp\b|\bglobex\b|\bmarket data platform\b", "cme_mdp3_futures"),
    (r"\bnfn\b|\bfund network\b|\bnfnds\b", None),
)

_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


@dataclass
class RouterResult:
    venue: str | None
    notice_type: str
    effective: str | None
    feeds: list[str]
    unknown_products: list[str]
    confidence: float
    evidence: dict[str, list[str]] = field(default_factory=dict)
    #: Every category that scored, best first, as (label, weight) pairs. The
    #: classification is a contest between these, and the runners-up are what
    #: make the confidence legible — a 7-vs-3 win and a 7-vs-6 win are very
    #: different claims. Kept so callers can show the contest, not just its
    #: winner.
    type_scores: list[tuple[str, int]] = field(default_factory=list)
    #: (top - second) / top. 0.0 = tie, 1.0 = unopposed. Feeds `confidence`.
    type_margin: float = 0.0

    @property
    def unknown_target(self) -> bool:
        return bool(self.unknown_products) and not self.feeds

    def as_dict(self) -> dict:
        return {
            "venue": self.venue,
            "notice_type": self.notice_type,
            "effective": self.effective,
            "feeds": self.feeds,
            "unknown_products": self.unknown_products,
            "unknown_target": self.unknown_target,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "type_scores": [[label, score] for label, score in self.type_scores],
            "type_margin": round(self.type_margin, 2),
        }


def _score(text: str, rules) -> tuple[dict[str, int], dict[str, list[str]]]:
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for label, pats in rules.items():
        for pat, weight in pats:
            found = re.findall(pat, text)
            if found:
                scores[label] = scores.get(label, 0) + weight * len(found)
                hits.setdefault(label, []).append(pat)
    return scores, hits


def route(text: str, published: str | None = None) -> RouterResult:
    low = text.lower()
    evidence: dict[str, list[str]] = {}

    # venue: evidence counting over marker words
    venue_scores = {
        v: sum(low.count(m) for m in markers) for v, markers in _VENUE_RULES.items()
    }
    venue = max(venue_scores, key=venue_scores.get) if any(venue_scores.values()) else None
    if venue:
        evidence["venue"] = [m for m in _VENUE_RULES[venue] if m in low]

    # type: weighted keyword scores; confidence from the margin between the
    # top two candidates (a one-sided walkover is more trustworthy than a
    # near-tie, regardless of absolute score)
    type_scores, type_hits = _score(low, _TYPE_RULES)
    if type_scores:
        # Ties broken by label so the ranking is deterministic; otherwise the
        # scoreboard could reorder between runs and the payload would churn.
        ranked = sorted(type_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        notice_type = ranked[0][0]
        top = ranked[0][1]
        second = ranked[1][1] if len(ranked) > 1 else 0
        margin = (top - second) / top  # 0 = tie, 1 = unopposed
        evidence["type"] = type_hits[notice_type]
    else:
        # Nothing matched: no contest to show, and the fallback label is a
        # default rather than a decision.
        ranked, notice_type, margin = [], "admin_other", 0.0

    # effective date: first ISO date in the text that isn't the publish date
    effective = None
    for m in _ISO_DATE.findall(text):
        if m != published:
            effective = m
            break

    # affected feeds
    feeds: list[str] = []
    unknown: list[str] = []
    feed_hits: list[str] = []
    for pat, feed_id in _FEED_RULES:
        found = re.findall(pat, low)
        if found:
            feed_hits.append(pat)
            if feed_id is None:
                unknown.extend(sorted(set(found)))
            elif feed_id not in feeds:
                feeds.append(feed_id)
    if feed_hits:
        evidence["feeds"] = feed_hits

    # confidence: type margin, tempered by whether venue and feed resolution
    # produced anything at all
    confidence = 0.2 + 0.5 * margin
    if venue is not None:
        confidence += 0.15
    if feeds:
        confidence += 0.15
    elif unknown:
        confidence = min(confidence, 0.45)  # we matched something we can't place

    return RouterResult(
        venue=venue,
        notice_type=notice_type,
        effective=effective,
        feeds=sorted(feeds),
        unknown_products=sorted(set(unknown)),
        confidence=min(confidence, 1.0),
        evidence=evidence,
        type_scores=ranked,
        type_margin=margin,
    )
