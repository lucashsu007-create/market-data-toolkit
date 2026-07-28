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

ROOT = Path(__file__).resolve().parent.parent

_PAYLOAD = re.compile(r'id="site-data"[^>]*>(\{.*?\})</script>', re.S)


@pytest.fixture(scope="module")
def payload():
    """The payload as actually embedded in the shipped index.html."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    match = _PAYLOAD.search(html)
    assert match, "index.html has no embedded site-data payload"
    return json.loads(match.group(1))


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
