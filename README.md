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

The bundled dataset contains precomputed pipeline output and evaluation results. **The web app
renders those results; it does not compute them.** Replacing them with real code is in progress —
see below.

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

## The Python package (`mdt`)

Being built to replace the precomputed output with code that actually derives it. Dependency-free at
runtime — the estate is small enough that an explicit adjacency map is clearer than a graph library,
and the traversal semantics are the interesting part.

**Done so far:** the estate model and loader, impact resolution (Layer 2), and the parts of the
governance audit the data can support.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest --cov=mdt
```

```python
from mdt import load_estate, resolve_impact, run_audit

estate = load_estate()
impact = resolve_impact(estate, "nasdaq_totalview")
print(impact.systems, impact.blast_radius)
print(run_audit(estate).as_dict())
```

### Reproducing the published audit

Three of the demo's ten audit checks are re-derived here and asserted, in
`tests/test_audit.py`, to match the shipped figures **exactly**:

- `feeds_without_owner`
- `datasets_without_owner`
- `feeds_without_consumers` — which is transitive: a feed *provides* a dataset, *consumed_by* a
  system, which *supports* a desk. A one-hop check would flag every feed in the estate.

The other seven **cannot** be computed from the shipped catalog, which carries only
`id / type / name / owner / criticality`. They need contract and entitlement expiry dates, a metadata
review date, and a secondary-owner relation — none of which are in the data. Rather than invent
values so the numbers match, those checks are declared in `audit.UNSUPPORTED` with the field each is
waiting on, and a test asserts none of them is silently dropped.

## Run the demo

No build step and no dependencies to install:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>. Opening `index.html` directly from the filesystem also works,
since `d3.min.js` is loaded by relative path.

## Layout

```
index.html              the web app — markup, CSS, D3 code, and the embedded dataset
d3.min.js               vendored D3 v7.9.0 (BSD-3-Clause, © Mike Bostock)
src/mdt/
  model.py              typed estate graph + traversal
  loader.py             load and validate the estate
  impact.py             Layer 2 — what a notice touches
  audit.py              governance checks
data/estate.json        estate extracted from the demo payload
scripts/extract_estate.py   regenerates data/ and the test fixture from index.html
tests/                  including parity tests against the demo's published figures
```

The dataset is a single `<script type="application/json">` block inside `index.html`. Everything
else in that file is readable source — roughly 700 lines.

## Roadmap

1. ~~Estate model, impact resolution, and the supportable audit checks~~ — done
2. **Layer 1 router** — classify raw notice text into type / venue / asset class / effective date
   with an explicit confidence, as a deterministic rules baseline so every failure is diagnosable
3. **Notice corpus generator** — scale past 5 notices with free ground-truth labels. The risk to
   manage: if a generator writes the notices *and* the classifier is tuned on them, the evaluation
   only measures whether the parser can read its own templates. Mitigated by varying phrasing and
   holding out template families the classifier never sees — and by saying so plainly.
4. **Layer 3 decision + evaluation harness** — priority, owner routing, escalation rule, then metrics
   on a held-out split with explicit `n`
5. **Control Plane tab** — the operator dashboard, driven by real output instead of a fixture
6. **Notes tab** — method and limitations, including the circularity caveat above

Once step 4 lands, the schema gains the fields the seven unsupported audit checks need, and they can
be implemented properly rather than declared.

## Licence

[MIT](LICENSE) for the code in this repository. Vendored D3 is BSD-3-Clause and remains under its own
licence and copyright.
