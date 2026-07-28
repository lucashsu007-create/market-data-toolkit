"""Layer 2 — resolve what a notice actually touches.

Given the thing a notice names (usually a feed), walk the estate to the datasets,
systems and desks that would be affected, and report how confident the match is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Estate


@dataclass
class ImpactResult:
    origin: str | None
    feeds: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    desks: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    unknown_target: bool = False

    @property
    def blast_radius(self) -> int:
        """How many things a notice touches, ignoring who owns them."""
        return len(self.feeds) + len(self.datasets) + len(self.systems) + len(self.desks)

    def as_dict(self) -> dict:
        return {
            "origin": self.origin,
            "feeds": self.feeds,
            "datasets": self.datasets,
            "systems": self.systems,
            "desks": self.desks,
            "owners": self.owners,
            "unknown_target": self.unknown_target,
            "blast_radius": self.blast_radius,
        }


def _owners_of(estate: Estate, node_ids: list[str]) -> list[str]:
    """Owners recorded against any of these nodes.

    Deliberately reads the `owner` attribute rather than following `owned_by`
    edges: the two disagree in the shipped catalog, and the attribute is the one
    the ownership audit uses. Worth reconciling once the schema is tightened.
    """
    owners = {
        estate.nodes[n].owner.strip()
        for n in node_ids
        if estate.nodes[n].owner.strip()
    }
    return sorted(owners)


def resolve_impact(estate: Estate, target: str | None) -> ImpactResult:
    """Resolve the blast radius of a notice naming `target`.

    An unresolvable target is not an error — a notice about a venue the firm
    does not yet model is a real and important case, and it must escalate rather
    than silently resolve to nothing.
    """
    if target is None or target not in estate.nodes:
        return ImpactResult(origin=target, unknown_target=True)

    reached = estate.downstream(target)
    by_type = lambda t: sorted(n for n in reached if estate.nodes[n].type == t)  # noqa: E731

    origin_node = estate.nodes[target]
    feeds = by_type("feed")
    if origin_node.type == "feed":
        feeds = sorted({target, *feeds})

    datasets, systems, desks = by_type("dataset"), by_type("system"), by_type("desk")
    return ImpactResult(
        origin=target,
        feeds=feeds,
        datasets=datasets,
        systems=systems,
        desks=desks,
        owners=_owners_of(estate, [*feeds, *datasets, *systems, *desks]),
    )
