"""Load an Estate from the extracted JSON."""

from __future__ import annotations

import json
from pathlib import Path

from .model import NODE_TYPES, Edge, Estate, Node

DEFAULT_ESTATE = Path(__file__).resolve().parents[2] / "data" / "estate.json"


def load_estate(path: Path | str = DEFAULT_ESTATE) -> Estate:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    nodes: dict[str, Node] = {}
    for raw in payload["nodes"]:
        if raw["type"] not in NODE_TYPES:
            raise ValueError(f"unknown node type {raw['type']!r} on {raw['id']!r}")
        if raw["id"] in nodes:
            raise ValueError(f"duplicate node id {raw['id']!r}")
        nodes[raw["id"]] = Node(
            id=raw["id"],
            type=raw["type"],
            name=raw.get("name", ""),
            owner=raw.get("owner", "") or "",
            criticality=raw.get("criticality", "") or "",
            expires=raw.get("expires", "") or "",
            last_reviewed=raw.get("last_reviewed", "") or "",
        )

    edges: list[Edge] = []
    for raw in payload["links"]:
        # A dangling edge would silently truncate impact traversal, which is
        # exactly the failure mode this tool exists to catch. Fail loudly.
        for end in ("source", "target"):
            if raw[end] not in nodes:
                raise ValueError(
                    f"edge {raw['source']}->{raw['target']} has unknown {end} {raw[end]!r}"
                )
        edges.append(
            Edge(
                source=raw["source"],
                target=raw["target"],
                edge_type=raw["edge_type"],
                kind=raw.get("kind", ""),
            )
        )

    return Estate(nodes=nodes, edges=edges)
