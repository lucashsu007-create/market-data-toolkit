"""Tests for the payload the demo renders.

The web app has no logic of its own — it draws whatever `build_payload.py`
embeds in `index.html`. So the payload is the contract, and the risk worth
testing is that it drifts from the code that supposedly produced it: a queue
row claiming a notice was graded one way while `evaluate.py` says another
would make the demo quietly lie.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mdt.corpus import load_notices
from mdt.decision import decide
from mdt.loader import load_estate
from mdt.router import route
from mdt.rules_export import ASSET_CLASS, ASSET_CLASS_DEFAULT, export_rules

ROOT = Path(__file__).resolve().parent.parent

_PAYLOAD = re.compile(r'id="site-data"[^>]*>(\{.*?\})</script>', re.S)


@pytest.fixture(scope="module")
def payload_blob():
    """The raw JSON text as embedded, before parsing."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    match = _PAYLOAD.search(html)
    assert match, "index.html has no embedded site-data payload"
    return match.group(1)


@pytest.fixture(scope="module")
def payload(payload_blob):
    """The payload as actually embedded in the shipped index.html."""
    return json.loads(payload_blob)


@pytest.fixture(scope="module")
def queue_by_id(payload):
    return {row["id"]: row for row in payload["queue"]}


# -- the demo must agree with the evaluator -------------------------------

_FLAGS = ["venue_ok", "type_ok", "priority_ok", "false_clear", "unnecessary_review"]


def test_queue_grading_agrees_with_the_evaluator(payload, queue_by_id):
    """`graded` is recomputed in build_payload; it must match evaluate.py.

    Two independent derivations of the same judgement is exactly where a demo
    starts showing a green tick over a result the evaluator called wrong.
    """
    checked = 0
    for split in ("dev", "held_out"):
        for record in payload["evaluation"][split]["per_notice"]:
            graded = queue_by_id[record["notice_id"]]["graded"]
            for flag in _FLAGS:
                if record.get(flag) is None:
                    continue
                checked += 1
                assert bool(graded[flag]) == bool(record[flag]), (
                    f"{record['notice_id']}.{flag}: queue says {graded[flag]}, "
                    f"evaluator says {record[flag]}"
                )
    assert checked > 100, "expected the corpus to exercise most flags"


def test_queue_split_matches_the_evaluation_split(payload, queue_by_id):
    """A notice shown as held-out must have been scored as held-out."""
    for split in ("dev", "held_out"):
        for record in payload["evaluation"][split]["per_notice"]:
            assert queue_by_id[record["notice_id"]]["split"] == split


def test_every_notice_appears_exactly_once(payload):
    ids = [row["id"] for row in payload["queue"]]
    assert len(ids) == len(set(ids))
    scored = {
        record["notice_id"]
        for split in ("dev", "held_out")
        for record in payload["evaluation"][split]["per_notice"]
    }
    assert set(ids) == scored


# -- fields the breakdown needs -------------------------------------------

def test_rows_carry_what_the_breakdown_renders(payload):
    required = {"title", "summary", "evidence", "type_scores", "type_margin",
                "truth", "graded", "split", "source_url"}
    for row in payload["queue"]:
        missing = required - set(row)
        assert not missing, f"{row['id']} missing {missing}"


def test_type_scores_are_ranked_and_include_the_winner(payload):
    for row in payload["queue"]:
        scores = row["type_scores"]
        if not scores:
            # No keyword matched: admin_other is a fallback, so there is no
            # contest to display and none should be implied.
            assert row["notice_type"] == "admin_other"
            continue
        assert [s for _, s in scores] == sorted((s for _, s in scores), reverse=True)
        assert scores[0][0] == row["notice_type"]


def test_a_false_clear_is_present_and_visible(payload):
    """The safety-critical failure must stay reachable in the demo.

    If a corpus change ever removes it, the write-up claiming the pipeline has
    a known false clear becomes false — better to fail here than ship that.
    """
    false_clears = [r for r in payload["queue"] if r["graded"]["false_clear"]]
    assert len(false_clears) == 1, "expected exactly one known false clear"
    assert false_clears[0]["split"] == "held_out"


def test_summaries_are_short_enough_to_be_our_own_words(payload):
    """Guards the licensing shape: summaries are authored, not pasted."""
    for row in payload["queue"]:
        assert len(row["summary"].split()) <= 80, f"{row['id']} summary is too long"


# -- rules shipped to the browser -----------------------------------------
# The Pipeline tab classifies text typed into the page, so the rule tables now
# travel in the payload. They ride inside the existing site-data block rather
# than a second one, which is what makes the CI drift check cover them.

def test_payload_carries_the_exported_rules(payload):
    """Deep equality against the exporter, not a retyped copy.

    Retyping the tables here would test that two hand-written copies agree, and
    the thing worth catching is the payload going stale against the Python
    rules that are still the source of truth.
    """
    assert payload["rules"] == export_rules()


def test_rules_ride_in_the_single_site_data_block(payload_blob):
    """One block, one `re.subn` in build_payload, one drift check covering both."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert html.count('type="application/json"') == 1
    assert json.loads(payload_blob)["rules"]["router"]["type"]


def test_payload_cannot_break_out_of_its_script_tag(payload_blob):
    """`</script>` anywhere in the JSON would end the block early and drop the
    rest of the payload into the document as markup."""
    lowered = payload_blob.lower()
    assert "</script" not in lowered
    assert "<!--" not in payload_blob


# -- scenarios must be reproducible from what they claim to have routed ---

@pytest.fixture(scope="module")
def estate():
    return load_estate()


@pytest.fixture(scope="module")
def notices():
    return load_notices()


def test_scenarios_carry_the_exact_text_the_router_saw(payload, notices):
    """`router_input` is the seed for the editable stage 1.

    It must be `title\\n summary` — what `route()` is actually given — and not
    the display `raw_text`, which wraps the notice in a source header. Seeding
    the textarea from the wrong string would make the live classifier disagree
    with the shipped result the moment the page loaded.
    """
    assert payload["scenarios"], "no scenarios in the payload"
    for scn in payload["scenarios"]:
        notice = notices[scn["id"]]
        assert scn["router_input"] == notice.text, f"{scn['id']} router_input drifted"
        assert scn["published"] == notice.published
        assert scn["router_input"] != scn["raw_text"]


def test_rerunning_the_router_on_router_input_reproduces_the_scenario(payload, estate):
    """The strongest available check that the seed is the real input.

    If `router_input` were seeded from anything else, this reproduction would
    diverge on evidence or effective date even where the labels happened to
    agree.
    """
    for scn in payload["scenarios"]:
        routed = route(scn["router_input"], published=scn["published"])
        ticket = decide(estate, routed, scn["router_input"])
        expected = {
            "id": scn["id"],
            "notice_type": routed.notice_type,
            "source": (routed.venue or "unknown").upper(),
            "affected_exchange": (routed.venue or "unknown").upper(),
            "affected_asset_class": ASSET_CLASS.get(routed.venue, ASSET_CLASS_DEFAULT),
            "effective_date": routed.effective,
            "urgency": ticket.priority,
            "summary": scn["router_output"]["summary"],
            "confidence": routed.confidence,
            "needs_review": ticket.review_required,
            "evidence": routed.evidence,
        }
        assert scn["router_output"] == expected, f"{scn['id']} router_output drifted"


def test_asset_class_follows_the_router_not_the_corpus_record(payload, notices):
    """Asset class is shown next to the router's own venue call.

    Deriving it from the corpus record's venue would print `equities` beside a
    venue the router never identified — a field silently sourced from the
    answer key. It is display-only; `evaluate.py` does not read it.
    """
    for row in payload["queue"]:
        routed_venue = None if row["venue"] == "?" else row["venue"].lower()
        assert row["asset_class"] == ASSET_CLASS.get(routed_venue, ASSET_CLASS_DEFAULT)

    missed = [
        row for row in payload["queue"]
        if (row["venue"] == "?" or row["venue"].lower() != notices[row["id"]].venue)
    ]
    assert missed, "expected at least one row where the router missed the venue"
