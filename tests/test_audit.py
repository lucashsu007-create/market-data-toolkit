"""Audit tests.

The load-bearing ones are the parity tests: the demo publishes audit findings
produced by code that no longer exists, and these assert this implementation
re-derives them exactly. If they fail, either the reimplementation is wrong or
the published figures never followed from the shipped catalog — both worth
knowing, which is why they are asserted rather than eyeballed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdt import load_estate, run_audit
from mdt.audit import UNSUPPORTED, feeds_without_consumers, unowned

FIXTURE = Path(__file__).parent / "fixtures" / "bundled_audit.json"


@pytest.fixture(scope="module")
def estate():
    return load_estate()


@pytest.fixture(scope="module")
def bundled():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# -- parity with the published demo output --------------------------------

@pytest.mark.parametrize(
    "check",
    ["feeds_without_owner", "datasets_without_owner", "feeds_without_consumers"],
)
def test_matches_bundled_output(estate, bundled, check):
    computed = getattr(run_audit(estate), check)
    assert computed == sorted(bundled[check]), (
        f"{check} does not reproduce the figure shipped in the demo"
    )


def test_unsupported_checks_are_declared_not_silently_dropped(bundled):
    """Every bundled check is either reimplemented or explicitly unsupported.

    Guards against a check quietly disappearing: if someone adds a field to the
    schema and implements one of these, they must remove it from UNSUPPORTED,
    and if a new bundled check appears it has to be classified.
    """
    implemented = set(run_audit(load_estate()).as_dict())
    classified = implemented | set(UNSUPPORTED)
    bundled_checks = set(bundled) - {"config"}
    assert bundled_checks <= classified, bundled_checks - classified


def test_unsupported_checks_each_state_a_reason():
    assert all(reason.strip() for reason in UNSUPPORTED.values())


# -- behaviour ------------------------------------------------------------

def test_ownership_check_reads_blank_owners_as_unowned(estate):
    unowned_feeds = unowned(estate, "feed")
    assert all(not estate.nodes[f].owner.strip() for f in unowned_feeds)
    owned = {f.id for f in estate.of_type("feed")} - set(unowned_feeds)
    assert all(estate.nodes[f].owner.strip() for f in owned)


def test_orphan_feed_has_no_downstream_system_or_desk(estate):
    for feed_id in feeds_without_consumers(estate):
        reached = estate.downstream(feed_id)
        assert not any(estate.nodes[n].type in ("system", "desk") for n in reached)


def test_a_consumed_feed_is_not_flagged_as_orphan(estate):
    """A one-hop check would flag every feed; this pins the transitive semantics."""
    orphans = set(feeds_without_consumers(estate))
    consumed = [f.id for f in estate.of_type("feed") if f.id not in orphans]
    assert consumed, "fixture should contain at least one consumed feed"
    for feed_id in consumed:
        reached = estate.downstream(feed_id)
        assert any(estate.nodes[n].type in ("system", "desk") for n in reached)
        # ...and none of them are reachable in a single hop.
        direct = {e.target for e in estate.out_edges(feed_id)}
        assert not any(estate.nodes[n].type == "system" for n in direct)


def test_results_are_sorted_and_deduplicated(estate):
    for values in run_audit(estate).as_dict().values():
        assert values == sorted(set(values))


def test_total_findings_counts_every_check(estate):
    report = run_audit(estate)
    assert report.total_findings == sum(len(v) for v in report.as_dict().values())
