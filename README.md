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

All five tabs are built, and the demo renders **computed** output: `scripts/build_payload.py` runs
the pipeline (`src/mdt/`) over the corpus and estate and regenerates the page's embedded data. CI
fails if the committed payload drifts from a fresh build.

**What is real:** the 26 notices in `corpus/` are real public notices — 21 from Nasdaq
(nasdaqtrader.com, full depth) and 5 from CME (cmegroup.com blocks automated access; those records
are reconstructed from public metadata and marked `depth: shallow`). Records store the source URL,
structured fields and an authored paraphrase — never the original text, which is the exchange's
copyright.

**What is synthetic:** the estate. No firm publishes its real feed→dataset→system→desk topology, so
the graph is invented, and its lifecycle dates are authored against a reference date of 2025-10-20.
Node names like "CME Group" refer to real venues in an invented estate; none of the relationships,
contracts or entitlements are real.

## What it models

A typed graph of **48 nodes** and **74 edges**:

- **Node types** — venue (5), vendor (2), feed (7), dataset (9), system (9), desk (3), owner (5), contract (4), entitlement (4)
- **Edge types** — `published_by`, `provides`, `derived_from`, `consumed_by`, `depends_on`, `supports`, `owned_by`, `covered_by_contract`, `requires_entitlement`

Alongside it: the 26-notice review queue, 5 fully worked scenarios, a governance audit
(ownership gaps, orphaned feeds, contract/entitlement expiry, stale metadata), and the pipeline's
evaluation of its own output on a frozen held-out split.

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

A stratified dev/held-out split (19/7, seeded — `corpus/split.json`) was **frozen before any
classification rule existed**. Rules were tuned on dev only; held-out was scored once and is
reported as-is:

| Metric | Dev (n=19) | **Held-out (n=7)** |
|---|---|---|
| Venue accuracy | 1.00 | **0.86** |
| Type accuracy | 1.00 | **1.00** |
| Feed recall | 1.00 | **0.86** |
| Priority accuracy | 0.95 | **0.43** |
| False clears | 0 | **1** |
| Unnecessary reviews | 0 | **1** |

The held-out numbers are the honest ones, and they are mixed. Three of the four failures are on the
conservative side (priority too high, one extra review). The dangerous one is the **false clear**:
`nasdaq-utp2026-15` carries no venue markers and no recognisable product name in its title/summary,
so it sailed through as a confident format change attached to nothing. The systemic cause: the
escalation rule covered *unknown* products but not *no product at all*. The one-line fix (escalate on
empty feed resolution) is deliberately **not applied** — it was discovered on held-out data, and
rules are only tuned on dev. It ships in the next iteration and gets measured on a fresh corpus.

n=7 is a smoke signal, not a benchmark. Labels and paraphrases share an author with the rules; the
frozen split mitigates tuning leakage, not labelling bias.

## The Python package (`mdt`)

Everything the demo displays is derived by this package. Dependency-free at runtime — the estate is
small enough that an explicit adjacency map is clearer than a graph library, and the traversal
semantics are the interesting part.

All three layers exist as code: `router.py` (Layer 1 — deterministic, evidence-logging keyword
scoring with margin-based confidence), `impact.py` (Layer 2 — typed graph traversal), `decision.py`
(Layer 3 — priority, owner routing, and the escalation rule: unknown targets, low confidence and
high priority always go to a human), `audit.py` (governance checks), `evaluate.py` (scores both
splits with explicit n and split provenance).

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest --cov=mdt
```

The demo's Pipeline tab lets you edit the notice text and reclassifies it in the browser, which
means `index.html` carries a JavaScript port of Layers 1–3. A port is a second implementation, so
`tests/test_js_parity.py` extracts the shipped block, runs it under Node, and diffs it against the
Python original over all 26 corpus notices plus ~20 adversarial inputs (Unicode word boundaries and
digits, scoring ties, the confidence cap). Rules are exported from the Python tables rather than
retyped — `rules_export.to_js_pattern` rewrites `\b` and `\d` into their Unicode-correct JS
equivalents and **refuses** anything else, so an unreviewed construct fails the build instead of
silently classifying differently in the browser.

Node is only needed for that suite. Without it those tests skip; set `MDT_REQUIRE_NODE=1` (as CI
does) to turn a missing Node into a failure, since a parity suite that skips itself looks
identical to one that passes. Live classification of edited text is rendered explicitly **ungraded**
— there is no label for text you just typed, and the accuracy figures on the site are the frozen
corpus's, not that text's.

```python
from mdt import load_estate, resolve_impact, run_audit

estate = load_estate()
impact = resolve_impact(estate, "nasdaq_totalview")
print(impact.systems, impact.blast_radius)
print(run_audit(estate).as_dict())
```

### The governance audit, and two grades of honesty

Eight of the original ten audit checks are implemented. The parity tests distinguish two grades:
the **ownership/orphan checks** genuinely re-derive the originally published findings from graph
relationships (`feeds_without_consumers` is transitive — a one-hop check would flag every feed);
the **lifecycle checks** (contract/entitlement expiry, stale metadata) run on synthetic
`expires`/`last_reviewed` dates that were *authored to reproduce* the published findings — real
code, fixture alignment by construction, and the tests say so in their docstrings. The remaining
two checks are declared in `audit.UNSUPPORTED` with the schema each is waiting on, and a test
asserts none is silently dropped.

## Run the demo

No build step and no dependencies to install:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>. Opening `index.html` directly from the filesystem also works,
since `d3.min.js` is loaded by relative path.

## Layout

```
index.html              the web app — markup, CSS, D3 code, and the generated embedded payload
d3.min.js               vendored D3 v7.9.0 (BSD-3-Clause, © Mike Bostock)
src/mdt/
  model.py              typed estate graph + traversal
  loader.py             load and validate the estate
  router.py             Layer 1 — classify a notice (rules, evidence, confidence)
  impact.py             Layer 2 — what a notice touches
  decision.py           Layer 3 — priority, owner routing, escalation
  audit.py              governance checks
  evaluate.py           dev vs held-out scoring
  corpus.py             corpus loader
corpus/                 26 real notices, labels, frozen split (see corpus/README.md)
data/estate.json        the synthetic estate (source of truth for the demo)
scripts/build_payload.py    runs the pipeline and regenerates index.html's payload
scripts/extract_estate.py   historical bootstrap (the original extraction direction)
tests/                  68 tests, incl. parity tests and a held-out leakage guard
```

## Roadmap

1. ~~Estate model, impact resolution, audit~~ — done
2. ~~Real notice corpus with a pre-registered held-out split~~ — done (replaced the planned synthetic
   corpus generator: real notices kill the self-authored-template circularity problem outright)
3. ~~Router, decision layer, evaluation; Control Plane + Notes tabs~~ — done
4. **Next:** apply the escalate-on-empty-resolution fix found by the held-out run, grow the corpus
   (fresh notices become the new held-out), deepen the CME records, and add Euronext if a public
   route to their notices appears
5. The two remaining `UNSUPPORTED` audit checks, when the schema gains a secondary-owner relation

## Licence

[MIT](LICENSE) for the code in this repository. Vendored D3 is BSD-3-Clause and remains under its own
licence and copyright.
