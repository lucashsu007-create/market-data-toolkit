"""Evaluation harness tests — mostly structural guarantees, because the
numeric results are findings to be published, not values to assert."""

from __future__ import annotations

import pytest

from mdt.corpus import load_labels, load_notices, load_split
from mdt.evaluate import evaluate
from mdt.loader import load_estate


@pytest.fixture(scope="module")
def result():
    return evaluate(load_estate())


def test_reports_both_splits_with_explicit_n(result):
    split = load_split()
    assert result["dev"]["metrics"]["n"] == len(split["dev"])
    assert result["held_out"]["metrics"]["n"] == len(split["held_out"])


def test_split_provenance_travels_with_the_numbers(result):
    """The metrics must carry when/how the split was frozen — a held-out number
    without its provenance is indistinguishable from a tuned one."""
    assert result["split_meta"]["seed"] == 20260728
    assert "before router" in result["split_meta"]["frozen"]


def test_every_corpus_notice_is_scored_exactly_once(result):
    scored = {r["notice_id"] for s in ("dev", "held_out") for r in result[s]["per_notice"]}
    assert scored == set(load_notices())


def test_false_clear_definition(result):
    """false_clear == labelled escalate but not escalated; recomputed from rows."""
    for split in ("dev", "held_out"):
        rows = result[split]["per_notice"]
        recomputed = sum(1 for r in rows if r["should_escalate"] and not r["escalated"])
        assert result[split]["metrics"]["false_clears"] == recomputed


def test_labels_cover_all_notices_and_valid_types():
    labels, notices = load_labels(), load_notices()
    assert set(labels) == set(notices)
    from mdt.router import NOTICE_TYPES
    for nid, lab in labels.items():
        assert lab["type"] in NOTICE_TYPES, nid
        assert lab["priority"] in ("low", "medium", "high"), nid


def test_dev_has_no_false_clears(result):
    """The safety property the rules were explicitly tuned to on dev. Held-out
    is deliberately NOT asserted — whatever it is, it gets reported."""
    assert result["dev"]["metrics"]["false_clears"] == 0
