"""Score router + decision against the labelled corpus, per split.

Reports dev and held-out separately, with explicit n. The held-out split was
frozen before any rule was written and must never be used for tuning; if a
held-out number is disappointing, it gets published, not fixed.

The safety metric is `false_clears`: notices a human should have reviewed
(label escalate=true) that the pipeline cleared. Everything else is quality;
that one is the reason the system is allowed to exist.
"""

from __future__ import annotations

from .corpus import load_labels, load_notices, load_split
from .decision import decide
from .model import Estate
from .router import route


def _score_one(estate: Estate, notice, label) -> dict:
    routed = route(notice.text, published=notice.published)
    ticket = decide(estate, routed, notice.text)

    labelled_feeds = set(label["feeds"])
    expects_unknown = "unknown" in labelled_feeds
    known_expected = labelled_feeds - {"unknown"}

    matched = known_expected & set(routed.feeds)
    feed_recall = None
    if known_expected:
        feed_recall = len(matched) / len(known_expected)
    unknown_ok = routed.unknown_target == expects_unknown if (expects_unknown or routed.unknown_products) else None

    return {
        "notice_id": notice.id,
        "venue_ok": routed.venue == notice.venue,
        "type_ok": routed.notice_type == label["type"],
        "feed_recall": feed_recall,
        "unknown_ok": unknown_ok,
        "priority_ok": ticket.priority == label["priority"],
        "escalated": ticket.review_required,
        "should_escalate": label["escalate"],
        "false_clear": label["escalate"] and not ticket.review_required,
        "unnecessary_review": ticket.review_required and not label["escalate"],
        "routed": routed.as_dict(),
        "ticket": ticket.as_dict(),
    }


def _aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    def rate(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None
    recalls = [r["feed_recall"] for r in rows if r["feed_recall"] is not None]
    return {
        "n": n,
        "venue_accuracy": rate("venue_ok"),
        "type_accuracy": rate("type_ok"),
        "feed_recall": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "priority_accuracy": rate("priority_ok"),
        "false_clears": sum(r["false_clear"] for r in rows),
        "unnecessary_reviews": sum(r["unnecessary_review"] for r in rows),
        "unnecessary_review_rate": rate("unnecessary_review"),
    }


def evaluate(estate: Estate) -> dict:
    notices = load_notices()
    labels = load_labels()
    split = load_split()

    out = {"split_meta": {"seed": split["seed"], "frozen": split["frozen"]}}
    for name in ("dev", "held_out"):
        rows = [
            _score_one(estate, notices[nid], labels[nid])
            for nid in split[name]
        ]
        out[name] = {"metrics": _aggregate(rows), "per_notice": rows}
    return out


if __name__ == "__main__":
    import json

    from .loader import load_estate

    result = evaluate(load_estate())
    slim = {k: (v["metrics"] if isinstance(v, dict) and "metrics" in v else v)
            for k, v in result.items()}
    print(json.dumps(slim, indent=2))
