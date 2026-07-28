"""Governance audit over the estate.

Scope note, deliberately visible in the code rather than buried in a doc:

The demo ships a precomputed audit with ten checks. Only three of them can be
re-derived from the catalog it also ships, because the catalog carries just
`id / type / name / owner / criticality`. The other seven need fields the
catalog does not have — contract and entitlement expiry dates, a metadata
review date, and a secondary-owner relation.

Rather than invent values so the numbers match, the unsupported checks are
declared as `UNSUPPORTED` with the field each one is waiting on. Fabricating
inputs to reproduce a published figure would defeat the point of the audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Estate

#: Checks that cannot run against the current schema, and what each one needs.
UNSUPPORTED: dict[str, str] = {
    "systems_missing_secondary_owner": "no secondary-owner relation on system nodes",
    "contracts_expiring": "no expiry date on contract nodes",
    "expired_contracts": "no expiry date on contract nodes",
    "entitlements_expiring": "no expiry date on entitlement nodes",
    "expired_entitlements": "no expiry date on entitlement nodes",
    "stale_metadata": "no last-reviewed date on any node",
    "structural_issues": "check was never specified; bundled output is empty",
}


@dataclass
class AuditReport:
    feeds_without_owner: list[str] = field(default_factory=list)
    datasets_without_owner: list[str] = field(default_factory=list)
    feeds_without_consumers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "feeds_without_owner": self.feeds_without_owner,
            "datasets_without_owner": self.datasets_without_owner,
            "feeds_without_consumers": self.feeds_without_consumers,
        }

    @property
    def total_findings(self) -> int:
        return sum(len(v) for v in self.as_dict().values())


def unowned(estate: Estate, node_type: str) -> list[str]:
    """Nodes of a type with no owner recorded — nobody to route a notice to."""
    return sorted(n.id for n in estate.of_type(node_type) if not n.has_owner)


def feeds_without_consumers(estate: Estate) -> list[str]:
    """Feeds with no system or desk downstream of them.

    Consumption is transitive, not a direct edge: a feed *provides* a dataset,
    which is *consumed_by* a system, which *supports* a desk. Checking only for
    a direct consumer would flag every feed in the estate.

    A feed nothing consumes is worth surfacing either way — it may be a licence
    still being paid for, or a gap in the catalog.
    """
    orphans = []
    for feed in estate.of_type("feed"):
        reached = estate.downstream(feed.id)
        if not any(estate.nodes[n].type in ("system", "desk") for n in reached):
            orphans.append(feed.id)
    return sorted(orphans)


def run_audit(estate: Estate) -> AuditReport:
    return AuditReport(
        feeds_without_owner=unowned(estate, "feed"),
        datasets_without_owner=unowned(estate, "dataset"),
        feeds_without_consumers=feeds_without_consumers(estate),
    )
