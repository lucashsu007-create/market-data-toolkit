# Market-data operations toolkit

An interactive model of a market-data estate and the notices that disturb it.

Vendors and venues constantly send notices — feed migrations, schema changes, entitlement updates,
fee changes. Each one *might* break something downstream, and finding out which things means knowing
how feeds, datasets, systems, desks, contracts and entitlements actually connect. This tool models
that estate as a typed graph and traces a notice through it to a routed, prioritised review ticket.

Built as a single self-contained HTML file with [D3](https://d3js.org) — no build step, no server,
no network calls at runtime.

---

## Status — read this first

**This is a work in progress, and two of its five tabs are unbuilt stubs.**

| Tab | State |
|---|---|
| **Overview** | Built — the estate end to end, with summary stats and pipeline layers |
| **Pipeline** | Built — step a notice through all four stages |
| **Graph** | Built — flow / force / matrix views of the estate, with zoom and filtering |
| **Control Plane** | **Stub** — the operator dashboard (review queue, risk overview, catalog audit, evaluation metrics) is not built |
| **Notes** | **Stub** — architecture write-up not written |

**All data in this repository is synthetic.** It is generated, not captured from any real venue,
vendor or firm, and it is labelled as such in the payload itself (`meta.synthetic: true`). No
proprietary or licensed market data is included. Node names like "CME Group" or "Bloomberg" refer to
plausible real-world entities in an invented estate; none of the relationships, contracts, or
entitlements are real.

The bundled dataset contains precomputed evaluation results. **The extraction and evaluation code
that produced them is not in this repository** — this app renders those results, it does not compute
them. Wiring that up is what the Control Plane tab is waiting on.

## What it models

A typed graph of **46 nodes** and **69 edges**:

- **Node types** — venue (5), vendor (2), feed (6), dataset (8), system (9), desk (3), owner (5), contract (4), entitlement (4)
- **Edge types** — `published_by`, `provides`, `derived_from`, `consumed_by`, `depends_on`, `supports`, `owned_by`, `covered_by_contract`, `requires_entitlement`

Alongside it: 20 queued notices, 5 fully worked scenarios with raw notice text, a governance audit
(ownership gaps, expiring and expired contracts and entitlements, orphaned feeds, stale metadata),
and an evaluation of the pipeline's own output.

## The pipeline

Each scenario steps through four stages, so you can see what the system inferred and where it could
be wrong:

1. **Raw inbound notice** — the unstructured vendor email as received
2. **Router output (Layer 1)** — classified notice type, venue, asset class, effective date
3. **Impact (Layer 2)** — the affected feeds, datasets and systems, resolved through the graph
4. **Decision & ticket (Layer 3)** — priority, owner routing, recommended action, and whether a
   human review is required

Stage 4 carries its own confidence signals (`router_confidence`, `graph_match_confidence`,
`review_required`), so a low-confidence match escalates instead of silently auto-clearing.

## Evaluation

The bundled results score the pipeline over 5 worked notices:

| Metric | Value |
|---|---|
| Feed / dataset / system recall | 1.00 |
| Owner routing accuracy | 1.00 |
| Critical risk recall | 1.00 |
| Priority accuracy | 0.80 |
| False clears | 0 |
| Unnecessary review rate | 0.00 |

**These numbers are weak evidence and should not be quoted as more.** n = 5 on synthetic notices
the same author designed, and several per-notice fields are `null` where a check did not apply. The
one honest signal in the table is `priority_accuracy` at 0.80 — one notice out of five was assigned
the wrong priority. A meaningful evaluation needs a larger corpus the pipeline has not been tuned
against.

## Run it

No build step and no dependencies to install:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>. Opening `index.html` directly from the filesystem also works,
since `d3.min.js` is loaded by relative path.

## Layout

```
index.html    the entire app — markup, CSS, D3 code, and the embedded dataset
d3.min.js     vendored D3 v7.9.0 (BSD-3-Clause, © Mike Bostock)
```

The dataset is a single `<script type="application/json">` block inside `index.html`. Everything
else in that file is readable source — roughly 700 lines.

## Roadmap

- **Phase D** — the Control Plane tab: review queue, risk overview, catalog audit, evaluation metrics
- **Phase E** — architecture notes and the ecosystem write-up
- Move extraction and evaluation into this repository so the metrics are reproducible rather than
  precomputed, and grow the notice corpus well beyond 5

## Licence

[MIT](LICENSE) for the code in this repository. Vendored D3 is BSD-3-Clause and remains under its own
licence and copyright.
