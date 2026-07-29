"""The in-browser classifier must agree with the Python one, exactly.

The demo's stage 1 is editable, so `index.html` now contains a JavaScript port
of `router` + `impact` + `decision`. A port is a second implementation, and a
second implementation drifts — quietly, because the demo has no label to check
itself against on text somebody just typed. The only thing standing between
"live classification" and "a plausible-looking lie" is this file.

It runs the *shipped* block: `parity_harness.js` lifts the marked region out of
`index.html` and evaluates it under Node. Nothing here re-implements the port,
so there is no third copy to keep honest.

Comparison is against raw, unrounded values. Routing through `as_dict()` would
round to 2dp and hide exactly the small numeric divergences worth catching.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mdt.corpus import load_notices
from mdt.decision import decide
from mdt.impact import resolve_impact
from mdt.loader import load_estate
from mdt.router import route
from mdt.rules_export import ACTIONS, ASSET_CLASS, ASSET_CLASS_DEFAULT

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "js" / "parity_harness.js"
FIXTURES = ROOT / "tests" / "fixtures" / "parity_inputs.json"

_NODE = shutil.which("node")
_NODE_REQUIRED = os.environ.get("MDT_REQUIRE_NODE") == "1"

# Locally a missing node is a skip; in CI it is a failure, because a silently
# skipped parity suite is indistinguishable from a passing one.
pytestmark = pytest.mark.skipif(
    _NODE is None and not _NODE_REQUIRED,
    reason="node not found; set MDT_REQUIRE_NODE=1 to make this a hard failure",
)


def _build_cases() -> list[dict]:
    """Every corpus notice, plus the hand-written adversarial inputs."""
    cases = []
    for nid, notice in sorted(load_notices().items()):
        cases.append({
            "name": f"corpus/{nid}",
            "why": "shipped corpus notice — the live path must reproduce the built payload",
            "text": notice.text,
            "published": notice.published,
        })
    for fixture in json.loads(FIXTURES.read_text(encoding="utf-8")):
        cases.append({
            "name": f"adversarial/{fixture['name']}",
            "why": fixture["why"],
            "text": fixture["text"],
            "published": fixture.get("published"),
            **({"impact_target": fixture["impact_target"]} if "impact_target" in fixture else {}),
        })
    return cases


CASES = _build_cases()


# -- running the shipped block --------------------------------------------

@pytest.fixture(scope="module")
def js_results(tmp_path_factory):
    """One node invocation for the whole suite."""
    if _NODE is None:
        pytest.fail("MDT_REQUIRE_NODE=1 but node is not installed")
    inputs = tmp_path_factory.mktemp("parity") / "inputs.json"
    inputs.write_text(json.dumps(CASES), encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(HARNESS), str(ROOT / "index.html"), str(inputs)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    results = json.loads(proc.stdout)
    # A harness that returns {} would make every comparison below vacuous.
    assert len(results) == len(CASES), "harness dropped inputs"
    assert results and set(results[0]) == {"route", "impact", "decide", "pipeline"}
    return results


@pytest.fixture(scope="module")
def estate():
    return load_estate()


# -- deep comparison -------------------------------------------------------

def _diff(path, py, js, out):
    """Collect every mismatch rather than dying on the first one.

    Lists are compared element-wise and in order on purpose: `evidence`,
    `type_scores`, `reasons` and `impacted` all carry meaning in their ordering.
    """
    if isinstance(py, bool) or isinstance(js, bool):
        if not (isinstance(py, bool) and isinstance(js, bool) and py == js):
            out.append(f"{path}: python {py!r} vs js {js!r}")
    elif isinstance(py, (int, float)) and isinstance(js, (int, float)):
        if not math.isclose(py, js, rel_tol=0.0, abs_tol=1e-12):
            out.append(f"{path}: python {py!r} vs js {js!r}")
    elif isinstance(py, dict) and isinstance(js, dict):
        for key in sorted(set(py) | set(js)):
            if key not in py:
                out.append(f"{path}.{key}: absent in python, js has {js[key]!r}")
            elif key not in js:
                out.append(f"{path}.{key}: absent in js, python has {py[key]!r}")
            else:
                _diff(f"{path}.{key}", py[key], js[key], out)
    elif isinstance(py, (list, tuple)) and isinstance(js, list):
        if len(py) != len(js):
            out.append(f"{path}: length {len(py)} vs {len(js)} — {py!r} vs {js!r}")
        else:
            for i, (a, b) in enumerate(zip(py, js)):
                _diff(f"{path}[{i}]", a, b, out)
    elif py != js:
        out.append(f"{path}: python {py!r} vs js {js!r}")


def assert_parity(case, path, py, js):
    out: list[str] = []
    _diff(path, py, js, out)
    assert not out, (
        f"{case['name']} diverged between Python and the shipped JS port\n"
        f"  why this input exists: {case['why']}\n"
        f"  input: {case['text']!r}\n  " + "\n  ".join(out)
    )


# -- expected values, straight off the Python originals --------------------

def py_route(case):
    r = route(case["text"], published=case.get("published"))
    return {
        "venue": r.venue,
        "notice_type": r.notice_type,
        "effective": r.effective,
        "feeds": r.feeds,
        "unknown_products": r.unknown_products,
        "unknown_target": r.unknown_target,
        "confidence": r.confidence,
        "evidence": r.evidence,
        "type_scores": [[label, score] for label, score in r.type_scores],
        "type_margin": r.type_margin,
    }


def py_impact(estate, case):
    routed = route(case["text"], published=case.get("published"))
    if "impact_target" in case:
        target = case["impact_target"]
    else:
        target = routed.feeds[0] if routed.feeds else None
    i = resolve_impact(estate, target)
    return {
        "origin": i.origin,
        "feeds": i.feeds,
        "datasets": i.datasets,
        "systems": i.systems,
        "desks": i.desks,
        "owners": i.owners,
        "unknown_target": i.unknown_target,
        "blast_radius": i.blast_radius,
    }


def py_decide(estate, case):
    routed = route(case["text"], published=case.get("published"))
    t = decide(estate, routed, case["text"])
    return {
        "notice_type": t.notice_type,
        "priority": t.priority,
        "owners": t.owners,
        "review_required": t.review_required,
        "reasons": t.reasons,
        "blast_radius": t.blast_radius,
        "feeds": t.feeds,
        "effective": t.effective,
        "confidence": t.confidence,
    }


_IDS = [c["name"] for c in CASES]


# -- layer by layer --------------------------------------------------------

@pytest.mark.parametrize("idx,case", list(enumerate(CASES)), ids=_IDS)
def test_route_parity(idx, case, js_results):
    """Layer 1 carries most of the divergence risk: two regex engines, a
    lowercasing step, substring counting and a tie-break, all order-sensitive."""
    assert_parity(case, "route", py_route(case), js_results[idx]["route"])


@pytest.mark.parametrize("idx,case", list(enumerate(CASES)), ids=_IDS)
def test_resolve_impact_parity(idx, case, js_results, estate):
    assert_parity(case, "impact", py_impact(estate, case), js_results[idx]["impact"])


@pytest.mark.parametrize("idx,case", list(enumerate(CASES)), ids=_IDS)
def test_decide_parity(idx, case, js_results, estate):
    assert_parity(case, "decide", py_decide(estate, case), js_results[idx]["decide"])


@pytest.mark.parametrize("idx,case", list(enumerate(CASES)), ids=_IDS)
def test_pipeline_parity(idx, case, js_results, estate):
    """The composed pipeline, against build_payload's own `_pipeline_text`.

    Imported rather than re-derived here: a third copy of the rollup logic
    living in the test would be the next thing to drift.
    """
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_payload import _pipeline_text  # noqa: PLC0415

    routed, ticket, rollup = _pipeline_text(estate, case["text"], case.get("published"))
    js = js_results[idx]["pipeline"]

    assert_parity(case, "pipeline.impact", rollup, js["impact"])
    assert_parity(case, "pipeline.routed", py_route(case), js["routed"])
    assert_parity(case, "pipeline.decision", py_decide(estate, case), js["decision"])

    # The presentation fields that come from shared constants, so a copy of
    # ACTIONS drifting inside index.html would show up here.
    assert js["router_output"]["affected_asset_class"] == ASSET_CLASS.get(
        routed.venue, ASSET_CLASS_DEFAULT
    )
    assert js["risk"]["recommended_action"] == ACTIONS[routed.notice_type]
    assert js["ticket"]["recommended_action"] == ACTIONS[routed.notice_type]
    assert [r["detail"] for r in js["risk"]["risks"]] == ticket.reasons


# -- the honesty invariant -------------------------------------------------

@pytest.mark.parametrize("idx,case", list(enumerate(CASES)), ids=_IDS)
def test_live_output_is_never_graded(idx, case, js_results):
    """The single most important property in this feature.

    Text typed into the page has no ground-truth label. If `pipeline()` ever
    emitted `graded` or `truth`, the renderers would light up their green ticks
    over an answer nobody checked — a demo claiming accuracy it has not
    measured. Absence is the contract; the UI must render "ungraded" from it.
    """
    js = js_results[idx]["pipeline"]
    assert "graded" not in js, "live pipeline invented a grading"
    assert "truth" not in js, "live pipeline invented a ground truth"
    assert js["live"] is True


# -- the live path reproduces the shipped scenarios ------------------------

def test_live_pipeline_reproduces_the_shipped_scenarios(js_results):
    """Seeding the textarea and typing nothing must change nothing.

    Ties the JS port to the payload Python actually built, rather than only to
    Python functions re-run inside the test.
    """
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    import re
    blob = re.search(r'id="site-data"[^>]*>(\{.*?\})</script>', html, re.S)
    payload = json.loads(blob.group(1))
    by_text = {c["text"]: i for i, c in enumerate(CASES)}

    assert payload["scenarios"], "no scenarios to check"
    for scn in payload["scenarios"]:
        idx = by_text.get(scn["router_input"])
        assert idx is not None, f"{scn['id']} router_input is not in the parity corpus"
        js = js_results[idx]["pipeline"]

        shipped = dict(scn["router_output"])
        live = dict(js["router_output"])
        # `id` is the one field live text cannot have: there is no notice.
        assert live.pop("id") is None
        shipped.pop("id")
        assert live == shipped, f"{scn['id']} live router output differs from the built payload"
        assert js["impact"] == scn["impact"], f"{scn['id']} live impact differs"
        assert js["risk"] == scn["risk"], f"{scn['id']} live risk differs"
