"""Governance audit over the estate.

History, deliberately visible in the code rather than buried in a doc: the demo
originally shipped a precomputed ten-check audit whose catalog carried only
`id / type / name / owner / criticality`, so most checks could not be
re-derived. The ownership and orphan checks were reimplemented first; the
lifecycle checks (contract/entitlement expiry, stale metadata) became
implementable when `expires` and `last_reviewed` were added to the schema.
The date values in data/estate.json are synthetic and were authored to
reproduce the originally published findings — the *checks* are real code, the
*fixture data* is aligned by construction, and the parity tests say so.

Anything still in `UNSUPPORTED` names the schema it is waiting on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .model import Estate

#: Checks that cannot run against the current schema, and what each one needs.
UNSUPPORTED: dict[str, str] = {
    "systems_missing_secondary_owner": "no secondary-owner relation on system nodes",
    "structural_issues": "check was never specified; bundled output is empty",
}


@dataclass
class AuditReport:
    feeds_without_owner: list[str] = field(default_factory=list)
    datasets_without_owner: list[str] = field(default_factory=list)
    feeds_without_consumers: list[str] = field(default_factory=list)
    contracts_expiring: list[str] = field(default_factory=list)
    expired_contracts: list[str] = field(default_factory=list)
    entitlements_expiring: list[str] = field(default_factory=list)
    expired_entitlements: list[str] = field(default_factory=list)
    stale_metadata: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "feeds_without_owner": self.feeds_without_owner,
            "datasets_without_owner": self.datasets_without_owner,
            "feeds_without_consumers": self.feeds_without_consumers,
            "contracts_expiring": self.contracts_expiring,
            "expired_contracts": self.expired_contracts,
            "entitlements_expiring": self.entitlements_expiring,
            "expired_entitlements": self.expired_entitlements,
            "stale_metadata": self.stale_metadata,
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


def _expiry(
    estate: Estate, node_type: str, today: date, horizon_days: int
) -> tuple[list[str], list[str]]:
    """(expiring within the horizon, already expired) for dated nodes.

    Nodes without an `expires` date are skipped, not flagged: "no date
    recorded" is an ownership/metadata problem, not an expiry finding.
    """
    expiring, expired = [], []
    horizon = today + timedelta(days=horizon_days)
    for node in estate.of_type(node_type):
        if not node.expires:
            continue
        expires = date.fromisoformat(node.expires)
        if expires < today:
            expired.append(node.id)
        elif expires <= horizon:
            expiring.append(node.id)
    return sorted(expiring), sorted(expired)


def stale_metadata(estate: Estate, today: date, stale_days: int) -> list[str]:
    """Nodes whose catalog entry has not been reviewed within `stale_days`.

    A stale entry is dangerous in a specific way: impact resolution silently
    trusts it. Undated nodes are not flagged, same reasoning as `_expiry`.
    """
    cutoff = today - timedelta(days=stale_days)
    return sorted(
        n.id
        for n in estate
        if n.last_reviewed and date.fromisoformat(n.last_reviewed) < cutoff
    )


def run_audit(
    estate: Estate,
    today: date | None = None,
    contract_expiry_days: int = 30,
    stale_days: int = 90,
) -> AuditReport:
    """Thresholds default to the config the demo originally published
    (contract_expiry_days=30, stale_days=90)."""
    today = today or date.today()
    contracts_expiring, expired_contracts = _expiry(
        estate, "contract", today, contract_expiry_days
    )
    entitlements_expiring, expired_entitlements = _expiry(
        estate, "entitlement", today, contract_expiry_days
    )
    return AuditReport(
        feeds_without_owner=unowned(estate, "feed"),
        datasets_without_owner=unowned(estate, "dataset"),
        feeds_without_consumers=feeds_without_consumers(estate),
        contracts_expiring=contracts_expiring,
        expired_contracts=expired_contracts,
        entitlements_expiring=entitlements_expiring,
        expired_entitlements=expired_entitlements,
        stale_metadata=stale_metadata(estate, today, stale_days),
    )
