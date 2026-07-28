"""Estate model and traversal tests.

Traversal correctness is asserted against hand-built graphs with known answers,
not against the shipped estate — a test that only reads real data tends to
encode whatever that data happens to do.
"""

from __future__ import annotations

import pytest

from mdt import load_estate
from mdt.loader import load_estate as _load
from mdt.model import FLOW_EDGES, GOVERNANCE_EDGES, Edge, Estate, Node


def build(nodes: dict[str, str], edges: list[tuple[str, str, str]]) -> Estate:
    return Estate(
        nodes={i: Node(id=i, type=t, name=i) for i, t in nodes.items()},
        edges=[Edge(source=s, target=t, edge_type=e) for s, t, e in edges],
    )


# -- traversal on known-answer graphs -------------------------------------

def test_downstream_follows_a_chain_transitively():
    estate = build(
        {"f": "feed", "d": "dataset", "s": "system", "k": "desk"},
        [("f", "d", "provides"), ("d", "s", "consumed_by"), ("s", "k", "supports")],
    )
    assert estate.downstream("f") == {"d", "s", "k"}
    assert estate.downstream("d") == {"s", "k"}
    assert estate.downstream("k") == set()


def test_downstream_excludes_the_starting_node():
    estate = build({"f": "feed", "d": "dataset"}, [("f", "d", "provides")])
    assert "f" not in estate.downstream("f")


def test_downstream_ignores_governance_edges():
    """Ownership is not a path a disruption travels along."""
    estate = build(
        {"f": "feed", "o": "owner", "c": "contract"},
        [("f", "o", "owned_by"), ("f", "c", "covered_by_contract")],
    )
    assert estate.downstream("f") == set()
    assert estate.downstream("f", edge_types=GOVERNANCE_EDGES) == {"o", "c"}


def test_downstream_terminates_on_a_cycle():
    estate = build(
        {"a": "dataset", "b": "dataset"},
        [("a", "b", "derived_from"), ("b", "a", "derived_from")],
    )
    assert estate.downstream("a") == {"a", "b"}


def test_downstream_handles_a_diamond_without_duplicating():
    estate = build(
        {"f": "feed", "d1": "dataset", "d2": "dataset", "s": "system"},
        [
            ("f", "d1", "provides"), ("f", "d2", "provides"),
            ("d1", "s", "consumed_by"), ("d2", "s", "consumed_by"),
        ],
    )
    assert estate.downstream("f") == {"d1", "d2", "s"}


def test_upstream_is_the_reverse_of_downstream():
    estate = build(
        {"f": "feed", "d": "dataset", "s": "system"},
        [("f", "d", "provides"), ("d", "s", "consumed_by")],
    )
    assert estate.upstream("s") == {"f", "d"}
    assert estate.upstream("f") == set()


def test_downstream_of_unknown_node_is_empty():
    estate = build({"f": "feed"}, [])
    assert estate.downstream("nope") == set()


def test_downstream_of_type_filters_and_sorts():
    estate = build(
        {"f": "feed", "b": "dataset", "a": "dataset", "s": "system"},
        [("f", "b", "provides"), ("f", "a", "provides"), ("a", "s", "consumed_by")],
    )
    assert estate.downstream_of_type("f", "dataset") == ["a", "b"]


def test_flow_and_governance_edge_sets_are_disjoint():
    assert not (FLOW_EDGES & GOVERNANCE_EDGES)


# -- loader validation ----------------------------------------------------

def test_loader_rejects_a_dangling_edge(tmp_path):
    """A dangling edge silently truncates impact — the exact bug this tool hunts."""
    bad = tmp_path / "estate.json"
    bad.write_text(
        '{"nodes": [{"id": "f", "type": "feed", "name": "f"}],'
        ' "links": [{"source": "f", "target": "ghost", "edge_type": "provides"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown target"):
        _load(bad)


def test_loader_rejects_an_unknown_node_type(tmp_path):
    bad = tmp_path / "estate.json"
    bad.write_text(
        '{"nodes": [{"id": "x", "type": "wormhole", "name": "x"}], "links": []}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown node type"):
        _load(bad)


def test_loader_rejects_duplicate_ids(tmp_path):
    bad = tmp_path / "estate.json"
    bad.write_text(
        '{"nodes": [{"id": "f", "type": "feed", "name": "a"},'
        ' {"id": "f", "type": "feed", "name": "b"}], "links": []}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate node id"):
        _load(bad)


# -- the shipped estate ---------------------------------------------------

def test_shipped_estate_loads_with_expected_shape():
    estate = load_estate()
    assert len(estate) == 46
    assert len(estate.edges) == 69


def test_shipped_estate_edge_types_are_all_classified():
    estate = load_estate()
    used = {e.edge_type for e in estate.edges}
    assert used <= (FLOW_EDGES | GOVERNANCE_EDGES), used - (FLOW_EDGES | GOVERNANCE_EDGES)
