"""Regenerate the demo's embedded JSON payload from the real pipeline.

Inverse of extract_estate.py: everything the demo renders — queue, scenarios,
audit, evaluation — is computed here by mdt.{router,decision,audit,evaluate}
over the real notice corpus and the synthetic estate, then written into the
single <script type="application/json"> block in index.html. The demo displays
output; it no longer authors any.

Temporal note: the estate is synthetic with an authored reference date
(2025-10-20) that the lifecycle audit runs against; the notices are real and
span 2025-2026. That mismatch is stated in the demo's Notes tab rather than
papered over.

Usage: python scripts/build_payload.py   (CI checks the result is committed)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mdt.audit import run_audit  # noqa: E402
from mdt.corpus import load_labels, load_notices, load_split  # noqa: E402
from mdt.decision import decide  # noqa: E402
from mdt.evaluate import evaluate  # noqa: E402
from mdt.impact import resolve_impact  # noqa: E402
from mdt.loader import load_estate  # noqa: E402
from mdt.router import route  # noqa: E402
from mdt.rules_export import (  # noqa: E402
    ACTIONS,
    ASSET_CLASS,
    ASSET_CLASS_DEFAULT,
    export_rules,
)

ESTATE_REFERENCE_DATE = date(2025, 10, 20)

# The five notices walked through on the Pipeline tab: a migration, a
# retirement, a format change, an unknown product, and a routine clearance.
SCENARIO_IDS = [
    "cme-20260720",
    "nasdaq-dtn2026-14",
    "nasdaq-utp2026-23",
    "nasdaq-dtn2026-15",
    "nasdaq-utp2026-17",
]


def _asset_class(venue: str | None) -> str:
    """Asset class for the venue **the router called**, not the corpus record's.

    Display-only (evaluate.py does not read it), and it belongs to the router's
    answer: printing `equities` next to a venue the router failed to identify
    would be quietly sourcing the field from the answer key. On the rows where
    the router misses the venue this now reads `mixed`, which is the honest
    consequence of that miss.
    """
    return ASSET_CLASS.get(venue, ASSET_CLASS_DEFAULT)


def _slug(reason: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")


def _governance(estate, feed_ids):
    contracts, entitlements = set(), set()
    for fid in feed_ids:
        for edge in estate.out_edges(fid):
            if edge.edge_type == "covered_by_contract":
                contracts.add(edge.target)
            elif edge.edge_type == "requires_entitlement":
                entitlements.add(edge.target)
    return sorted(contracts), sorted(entitlements)


def _pipeline_text(estate, text, published):
    """Run the real pipeline over arbitrary text; return routed, ticket, rollup.

    Split out from `_pipeline` because the demo's stage 1 is editable: the
    JavaScript port has to reproduce exactly this sequence over text nobody has
    a label for, and a function taking `(text, published)` is the shape that
    port mirrors. Everything downstream of `route()` is unchanged.
    """
    routed = route(text, published=published)
    ticket = decide(estate, routed, text)

    feeds, datasets, systems, desks, owners = set(routed.feeds), set(), set(), set(), set()
    for fid in routed.feeds:
        imp = resolve_impact(estate, fid)
        datasets.update(imp.datasets)
        systems.update(imp.systems)
        desks.update(imp.desks)
        owners.update(imp.owners)
    contracts, entitlements = _governance(estate, routed.feeds)
    # Feed resolution is deterministic id matching: full confidence on a match,
    # none on an unknown — there is no fuzzy middle to dress up.
    graph_conf = 1.0 if routed.feeds else 0.0
    rollup = {
        "matched_feeds": sorted(feeds),
        "unknown_feed": routed.unknown_target,
        "graph_match_confidence": graph_conf,
        "feeds": sorted(feeds),
        "datasets": sorted(datasets),
        "systems": sorted(systems),
        "desks": sorted(desks),
        "owners": sorted(owners),
        "responder_owners": ticket.owners,
        "contracts": contracts,
        "entitlements": entitlements,
        "impacted": sorted(feeds) + sorted(datasets) + sorted(systems)
        + sorted(desks) + sorted(owners) + contracts + entitlements,
        "counts": {
            "feeds": len(feeds), "datasets": len(datasets), "systems": len(systems),
            "desks": len(desks), "owners": len(owners),
            "contracts": len(contracts), "entitlements": len(entitlements),
        },
    }
    return routed, ticket, rollup


def _pipeline(estate, notice):
    """The pipeline over a corpus notice — `notice.text` is all the router sees."""
    return _pipeline_text(estate, notice.text, notice.published)


def build() -> dict:
    estate = load_estate()
    notices = load_notices()
    split = load_split()
    labels = load_labels()
    split_of = {nid: "dev" for nid in split["dev"]}
    split_of.update({nid: "held_out" for nid in split["held_out"]})

    queue, scenarios = [], []
    for nid, notice in sorted(notices.items(), key=lambda kv: kv[1].published, reverse=True):
        routed, ticket, rollup = _pipeline(estate, notice)
        entry = {
            "id": nid,
            "label": notice.title if len(notice.title) <= 60 else notice.title[:57] + "…",
            "notice_type": routed.notice_type,
            "venue": (routed.venue or "?").upper(),
            "asset_class": _asset_class(routed.venue),
            "effective_date": routed.effective,
            "published": notice.published,
            "urgency": ticket.priority,
            "router_needs_review": ticket.review_required,
            "router_confidence": routed.confidence,
            "matched_feeds": rollup["matched_feeds"],
            "unknown_feed": rollup["unknown_feed"],
            "graph_match_confidence": rollup["graph_match_confidence"],
            "review_required": ticket.review_required,
            "status": "needs_review" if ticket.review_required else "cleared",
            "priority": ticket.priority,
            "risks": [_slug(r) for r in ticket.reasons],
            "risk_details": ticket.reasons,
            "assignees": ticket.owners,
            "counts": rollup["counts"],
            "split": split_of[nid],
            "source_url": notice.source_url,
            "notice_no": notice.notice_no,
            "depth": notice.depth,
            # --- click-to-route breakdown ---------------------------------
            # The demo lets you open any queued notice and watch it being
            # classified, so each row carries what the router saw and what it
            # was graded against.
            #
            # `title`/`summary` are our own words about a public notice, not
            # exchange copy — the same licensing-safe shape the corpus uses.
            "title": notice.title,
            "summary": notice.summary,
            # Everything the notice reaches, so the breakdown can light up the
            # estate graph without re-deriving the traversal in JavaScript.
            "impacted": rollup["impacted"],
            "datasets": rollup["datasets"],
            "systems": rollup["systems"],
            "desks": rollup["desks"],
            "evidence": routed.evidence,
            "type_scores": [[lab, sc] for lab, sc in routed.type_scores],
            "type_margin": round(routed.type_margin, 2),
            # Graded per field rather than pass/fail overall: type is right on
            # every notice, and collapsing that with priority (which is not)
            # would hide the only interesting result in here.
            "truth": {
                "type": labels[nid]["type"],
                "feeds": labels[nid].get("feeds", []),
                "priority": labels[nid]["priority"],
                "escalate": labels[nid]["escalate"],
                "note": labels[nid].get("note"),
            },
            "graded": {
                "venue_ok": (routed.venue or "") == notice.venue,
                "type_ok": routed.notice_type == labels[nid]["type"],
                "priority_ok": ticket.priority == labels[nid]["priority"],
                "escalate_ok": ticket.review_required == labels[nid]["escalate"],
                # A false clear is the failure that matters: the pipeline said
                # "no review needed" on something that needed one.
                "false_clear": (not ticket.review_required) and labels[nid]["escalate"],
                "unnecessary_review": ticket.review_required and not labels[nid]["escalate"],
            },
        }
        queue.append(entry)

        if nid in SCENARIO_IDS:
            scenarios.append({
                "id": nid,
                "label": notice.title if len(notice.title) <= 44 else notice.title[:41] + "…",
                "notice_type": routed.notice_type,
                # What `route()` was actually handed, and what the editable
                # stage 1 is seeded with. Deliberately not `raw_text`: that
                # wraps the notice in a source header for display, and seeding
                # from it would make the live classifier disagree with the
                # shipped result on first paint.
                "router_input": notice.text,
                "published": notice.published,
                "raw_text": (
                    f"Source: {notice.venue.upper()} {notice.notice_no} · published {notice.published}\n"
                    f"{notice.source_url}\n\n{notice.title}\n\n{notice.summary}\n\n"
                    "[Paraphrase of the public notice — original text is the exchange's copyright.]"
                ),
                "router_output": {
                    "id": nid,
                    "notice_type": routed.notice_type,
                    "source": (routed.venue or "unknown").upper(),
                    "affected_exchange": (routed.venue or "unknown").upper(),
                    "affected_asset_class": _asset_class(routed.venue),
                    "effective_date": routed.effective,
                    "urgency": ticket.priority,
                    "summary": notice.title,
                    "confidence": routed.confidence,
                    "needs_review": ticket.review_required,
                    "evidence": routed.evidence,
                },
                "impact": rollup,
                "risk": {
                    "review_required": ticket.review_required,
                    "priority": ticket.priority,
                    "risks": [{"flag": _slug(r), "detail": r} for r in ticket.reasons],
                    "recommended_action": ACTIONS[routed.notice_type],
                },
                "ticket": {
                    "id": nid,
                    "title": notice.title,
                    "priority": ticket.priority,
                    "assignees": ticket.owners,
                    "due_date": routed.effective,
                    "recommended_action": ACTIONS[routed.notice_type],
                    "audit": {
                        "router_confidence": routed.confidence,
                        "graph_match_confidence": rollup["graph_match_confidence"],
                        "review_required": ticket.review_required,
                    },
                },
            })

    scenarios.sort(key=lambda s: SCENARIO_IDS.index(s["id"]))

    audit_report = run_audit(estate, today=ESTATE_REFERENCE_DATE)
    audit = {
        "config": {
            "today": ESTATE_REFERENCE_DATE.isoformat(),
            "contract_expiry_days": 30,
            "stale_days": 90,
        },
        **audit_report.as_dict(),
    }

    ev = evaluate(estate)
    total_false_clears = (
        ev["dev"]["metrics"]["false_clears"] + ev["held_out"]["metrics"]["false_clears"]
    )
    evaluation = {
        # summary block (Overview reads .metrics.false_clears)
        "metrics": {
            "evaluated": ev["dev"]["metrics"]["n"] + ev["held_out"]["metrics"]["n"],
            "false_clears": total_false_clears,
        },
        "split_meta": ev["split_meta"],
        "dev": ev["dev"],
        "held_out": ev["held_out"],
    }

    return {
        "meta": {
            # deterministic (latest notice date), so the CI drift check does
            # not fail purely because it ran on a different day
            "corpus_through": max(n.published for n in notices.values()),
            "version": "0.6.0-real-corpus",
            "estate": "synthetic (reference date 2025-10-20)",
            "notices": "real public notices; see corpus/ for sources",
            "synthetic": False,
        },
        "catalog": {
            "nodes": json.loads((ROOT / "data" / "estate.json").read_text())["nodes"],
            "links": json.loads((ROOT / "data" / "estate.json").read_text())["links"],
        },
        # The rule tables, translated for JavaScript, so the Pipeline tab can
        # classify text typed into the page. They ride in this block rather than
        # one of their own: `main()` rewrites exactly one <script>, and the CI
        # drift check watches this file, so the rules get the same guard the
        # rest of the payload already has.
        "rules": export_rules(),
        "scenarios": scenarios,
        "queue": queue,
        "audit": audit,
        "evaluation": evaluation,
    }


def main() -> None:
    payload = build()
    html_path = ROOT / "index.html"
    html = html_path.read_text(encoding="utf-8")
    blob = json.dumps(payload, separators=(",", ": "), ensure_ascii=False)
    new_html, n = re.subn(
        r'(<script id="site-data" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + blob + m.group(2),
        html,
        flags=re.S,
    )
    if n != 1:
        raise SystemExit(f"expected exactly one payload block, found {n}")
    html_path.write_text(new_html, encoding="utf-8")
    ho = payload["evaluation"]["held_out"]["metrics"]
    print(f"payload rebuilt: {len(payload['queue'])} queue entries, "
          f"{len(payload['scenarios'])} scenarios")
    print("HELD-OUT:", json.dumps(ho))


if __name__ == "__main__":
    main()
