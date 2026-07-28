"""Impact resolution tests."""

from __future__ import annotations

import pytest

from mdt import load_estate, resolve_impact
from mdt.model import Edge, Estate, Node


def build(nodes, edges, owners=None):
    owners = owners or {}
    return Estate(
        nodes={
            i: Node(id=i, type=t, name=i, owner=owners.get(i, ""))
            for i, t in nodes.items()
        },
        edges=[Edge(source=s, target=t, edge_type=e) for s, t, e in edges],
    )


@pytest.fixture(scope="module")
def estate():
    return load_estate()


def test_resolves_a_chain_into_each_layer():
    e = build(
        {"f": "feed", "d": "dataset", "s": "system", "k": "desk"},
        [("f", "d", "provides"), ("d", "s", "consumed_by"), ("s", "k", "supports")],
    )
    result = resolve_impact(e, "f")
    assert result.feeds == ["f"]
    assert result.datasets == ["d"]
    assert result.systems == ["s"]
    assert result.desks == ["k"]
    assert not result.unknown_target


def test_origin_feed_is_included_in_its_own_impact():
    """A notice about a feed affects that feed, not only what is downstream."""
    e = build({"f": "feed", "d": "dataset"}, [("f", "d", "provides")])
    assert "f" in resolve_impact(e, "f").feeds


def test_unknown_target_escalates_rather_than_resolving_empty():
    """The dangerous failure is a notice that looks harmless because nothing matched."""
    e = build({"f": "feed"}, [])
    result = resolve_impact(e, "tsx_unlisted")
    assert result.unknown_target
    assert result.blast_radius == 0
    assert result.origin == "tsx_unlisted"


def test_none_target_is_treated_as_unknown():
    assert resolve_impact(build({"f": "feed"}, []), None).unknown_target


def test_collects_owners_across_every_affected_layer():
    e = build(
        {"f": "feed", "d": "dataset", "s": "system"},
        [("f", "d", "provides"), ("d", "s", "consumed_by")],
        owners={"f": "md-ops", "d": "", "s": "pricing"},
    )
    assert resolve_impact(e, "f").owners == ["md-ops", "pricing"]


def test_owners_are_deduplicated():
    e = build(
        {"f": "feed", "d": "dataset", "s": "system"},
        [("f", "d", "provides"), ("d", "s", "consumed_by")],
        owners={"f": "md-ops", "d": "md-ops", "s": "md-ops"},
    )
    assert resolve_impact(e, "f").owners == ["md-ops"]


def test_blast_radius_counts_nodes_not_owners():
    e = build(
        {"f": "feed", "d": "dataset", "s": "system"},
        [("f", "d", "provides"), ("d", "s", "consumed_by")],
        owners={"f": "a", "d": "b", "s": "c"},
    )
    assert resolve_impact(e, "f").blast_radius == 3


def test_leaf_node_has_no_downstream_impact():
    e = build({"k": "desk"}, [])
    assert resolve_impact(e, "k").blast_radius == 0


# -- against the shipped estate -------------------------------------------

def test_orphan_feed_reaches_nothing(estate):
    """eurex_emdi is the estate's known orphan; it should resolve to no consumers."""
    result = resolve_impact(estate, "eurex_emdi")
    assert not result.unknown_target
    assert result.systems == []
    assert result.desks == []


def test_busiest_feed_reaches_multiple_systems(estate):
    result = resolve_impact(estate, "nasdaq_totalview")
    assert len(result.systems) >= 3
    assert result.datasets
    assert result.owners


def test_impact_is_serialisable(estate):
    payload = resolve_impact(estate, "cme_mdp3_futures").as_dict()
    assert payload["origin"] == "cme_mdp3_futures"
    assert payload["blast_radius"] == (
        len(payload["feeds"]) + len(payload["datasets"])
        + len(payload["systems"]) + len(payload["desks"])
    )
