"""The estate: a typed graph of everything a market-data notice can disturb.

Deliberately dependency-free. The graph is small (tens of nodes), so an explicit
adjacency map is clearer than pulling in a graph library — and the traversal
semantics are the interesting part, so they should be readable rather than
delegated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

# Node types present in the estate.
NODE_TYPES = frozenset({
    "venue", "vendor", "feed", "dataset",
    "system", "desk", "owner", "contract", "entitlement",
})

# Edges describing how data physically flows through the estate. Impact
# propagates along these and only these: a notice about a feed reaches the desks
# that ultimately consume it. The remaining edge types (owned_by,
# covered_by_contract, requires_entitlement, published_by) are governance or
# provenance relations — real, but not paths along which a disruption travels.
FLOW_EDGES = frozenset({
    "provides",       # feed    -> dataset
    "derived_from",   # dataset -> dataset
    "consumed_by",    # dataset -> system
    "depends_on",     # system  -> dataset
    "supports",       # system  -> desk
})

GOVERNANCE_EDGES = frozenset({
    "owned_by", "covered_by_contract", "requires_entitlement", "published_by",
})


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    name: str
    owner: str = ""
    criticality: str = ""
    # ISO dates; empty string = not recorded. `expires` is meaningful on
    # contracts and entitlements, `last_reviewed` on any catalogued node.
    expires: str = ""
    last_reviewed: str = ""

    @property
    def has_owner(self) -> bool:
        return bool(self.owner.strip())


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    edge_type: str
    kind: str = ""


@dataclass
class Estate:
    nodes: dict[str, Node]
    edges: list[Edge]
    _out: dict[str, list[Edge]] = field(default_factory=dict, repr=False)
    _in: dict[str, list[Edge]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._out = {}
        self._in = {}
        for edge in self.edges:
            self._out.setdefault(edge.source, []).append(edge)
            self._in.setdefault(edge.target, []).append(edge)

    # -- lookups ---------------------------------------------------------

    def of_type(self, node_type: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.type == node_type]

    def out_edges(self, node_id: str) -> list[Edge]:
        return self._out.get(node_id, [])

    def in_edges(self, node_id: str) -> list[Edge]:
        return self._in.get(node_id, [])

    # -- traversal -------------------------------------------------------

    def downstream(
        self, start: str, edge_types: Iterable[str] = FLOW_EDGES
    ) -> set[str]:
        """Everything reachable from `start` along the given edge types.

        Excludes `start` itself. Cycle-safe: `derived_from` between datasets can
        in principle loop, and a visited set is cheaper than trusting it not to.
        """
        allowed = frozenset(edge_types)
        seen: set[str] = set()
        stack = [start]
        while stack:
            for edge in self.out_edges(stack.pop()):
                if edge.edge_type in allowed and edge.target not in seen:
                    seen.add(edge.target)
                    stack.append(edge.target)
        return seen

    def upstream(
        self, start: str, edge_types: Iterable[str] = FLOW_EDGES
    ) -> set[str]:
        """Everything that reaches `start` along the given edge types."""
        allowed = frozenset(edge_types)
        seen: set[str] = set()
        stack = [start]
        while stack:
            for edge in self.in_edges(stack.pop()):
                if edge.edge_type in allowed and edge.source not in seen:
                    seen.add(edge.source)
                    stack.append(edge.source)
        return seen

    def downstream_of_type(self, start: str, node_type: str) -> list[str]:
        return sorted(
            n for n in self.downstream(start) if self.nodes[n].type == node_type
        )

    def __iter__(self) -> Iterator[Node]:
        return iter(self.nodes.values())

    def __len__(self) -> int:
        return len(self.nodes)
