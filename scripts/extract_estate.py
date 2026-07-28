"""Extract the estate catalog and the bundled audit output from index.html.

The demo ships its dataset inline, as a single <script type="application/json">
block. This pulls that apart into files the Python package can load, and into a
test fixture recording what the demo currently claims. Provenance matters here:
the audit numbers in the fixture were produced by code that no longer exists, so
they are treated as an expectation to be re-derived, not as ground truth.

Usage:  python scripts/extract_estate.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "index.html"
ESTATE_OUT = ROOT / "data" / "estate.json"
FIXTURE_OUT = ROOT / "tests" / "fixtures" / "bundled_audit.json"

_PAYLOAD = re.compile(r'type="application/json"[^>]*>(\{.*?\})</script>', re.S)


def load_payload(html: str) -> dict:
    match = _PAYLOAD.search(html)
    if match is None:
        raise SystemExit("no embedded JSON payload found in index.html")
    return json.loads(match.group(1))


def main() -> None:
    payload = load_payload(DEMO.read_text(encoding="utf-8"))

    estate = {
        "meta": {
            "source": "index.html embedded payload",
            "version": payload["meta"]["version"],
            "synthetic": payload["meta"]["synthetic"],
        },
        "nodes": payload["catalog"]["nodes"],
        "links": payload["catalog"]["links"],
    }
    ESTATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    ESTATE_OUT.write_text(json.dumps(estate, indent=2) + "\n", encoding="utf-8")

    FIXTURE_OUT.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_OUT.write_text(json.dumps(payload["audit"], indent=2) + "\n", encoding="utf-8")

    print(f"estate  -> {ESTATE_OUT.relative_to(ROOT)}  "
          f"({len(estate['nodes'])} nodes, {len(estate['links'])} links)")
    print(f"fixture -> {FIXTURE_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
