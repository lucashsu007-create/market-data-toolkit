"""The demo must not put a verdict over text nobody labelled.

The Pipeline tab's stage 1 is editable. Everything downstream — the router
readout, the impact panel, the decision card — is precomputed and *graded*
against a hand-written label while the text is the shipped notice, and is
nothing but classifier output the moment a character changes.

Rendering the shipped grading over invented text would be the demo claiming an
accuracy it has not measured, on the one screen an interviewer is most likely to
poke at. That is the failure this file exists to prevent, so the assertions are
about what the page *says*, not only about what it computes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "js" / "xss_harness.js"

_NODE = shutil.which("node")
_NODE_REQUIRED = os.environ.get("MDT_REQUIRE_NODE") == "1"

pytestmark = pytest.mark.skipif(
    _NODE is None and not _NODE_REQUIRED,
    reason="node not found; set MDT_REQUIRE_NODE=1 to make this a hard failure",
)

STAGES = ["stageRouter", "stageImpact", "stageDecision"]

CASES = [
    {"name": "original", "original": True, "text": ""},
    {"name": "edited", "text": "NASDAQ will retire the TotalView multicast feed on 2026-03-01."},
    {"name": "edited-clean-clear", "text": "Quarterly governance administrator update."},
    {"name": "edited-empty", "text": ""},
]


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    if _NODE is None:
        pytest.fail("MDT_REQUIRE_NODE=1 but node is not installed")
    inputs = tmp_path_factory.mktemp("ui") / "inputs.json"
    inputs.write_text(json.dumps(CASES), encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(HARNESS), str(ROOT / "index.html"), str(inputs)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    results = {r["name"]: r for r in json.loads(proc.stdout)}
    assert set(results) == {c["name"] for c in CASES}
    return results


# -- the ungraded caveat ---------------------------------------------------

@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("case", ["edited", "edited-clean-clear", "edited-empty"])
def test_edited_text_is_labelled_ungraded_on_every_stage(stage, case, rendered):
    """Every stage that shows a verdict must carry the caveat, not just one."""
    html = rendered[case][stage]
    assert "live-note" in html, f"{stage} showed live output with no ungraded note"
    assert "ungraded" in html.lower()
    assert "no label" in html.lower()


@pytest.mark.parametrize("stage", STAGES)
def test_the_shipped_notice_keeps_its_grading(stage, rendered):
    """The caveat must not fire on the untouched notice.

    A note that is always on says nothing; the switch is the point.
    """
    html = rendered["original"][stage]
    assert "live-note" not in html, f"{stage} called the shipped notice ungraded"


def test_stage_four_does_not_claim_the_corpus_result_for_live_text(rendered):
    """The auto-clear copy cites the held-out evaluation — a measured claim
    about 26 labelled notices. It says nothing about text somebody just typed,
    so it must not appear next to it."""
    claim = "the evaluation confirms it never clears one that should have been reviewed"
    for case in ("edited", "edited-clean-clear", "edited-empty"):
        assert claim not in rendered[case]["stageDecision"], f"{case} reused the corpus claim"
    # ...and is still made where it is true.
    original = rendered["original"]["stageDecision"]
    assert ("live-note" not in original)


def test_stage_one_marks_edited_text_in_its_own_status_line(rendered):
    edited = rendered["edited"]["stageRaw"]
    assert "Edited." in edited and "ungraded" in edited
    assert "/ 20000 characters" in edited
    original = rendered["original"]["stageRaw"]
    assert "Edited." not in original
    assert "graded against its hand-written label" in original


def test_stage_one_is_editable_and_capped(rendered):
    html = rendered["original"]["stageRaw"]
    assert "<textarea" in html
    assert 'maxlength="20000"' in html
    assert 'data-ref="preset"' in html, "no reset control"
    assert "Reset to the original notice" in html


def test_stage_one_preserves_a_leading_newline(rendered):
    """An HTML parser drops the first newline inside `<textarea>`.

    Without a deliberate extra one, text an interviewer typed starting with a
    blank line would lose it every time the stage repainted — and the
    classification would then quietly be of something they did not write.
    """
    html = rendered["original"]["stageRaw"]
    body = html.split("<textarea", 1)[1]
    assert body[body.index(">") + 1] == "\n", "no padding newline before the content"


def test_stage_one_still_shows_where_the_notice_came_from(rendered):
    """Editing must not cost the provenance: the paraphrase, the notice number
    and the source URL are the licensing story and stay reachable."""
    html = rendered["original"]["stageRaw"]
    assert "Paraphrase of the public notice" in html
    assert "https://" in html


# -- source-level invariants the DOM stub cannot observe -------------------

@pytest.fixture(scope="module")
def app_source():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    start = html.index("<script>/* MDIGGraph")
    return html[start:]


def test_recompute_drives_the_graph_instead_of_remounting_it(app_source):
    """Stage 3 mounts MDIGGraph once on entry.

    Remounting a force simulation on every keystroke restarts the layout, so the
    panel would jump around under the cursor while typing. `applyLive` must
    reach for `setScenario`, never for a fresh mount.
    """
    body = re.search(r"function applyLive\(\) \{(.*?)\n  \}\n", app_source, re.S)
    assert body, "applyLive not found"
    assert "MDIGGraph(" not in body.group(1), "applyLive remounts the graph"
    assert "pipeGraph.setScenario" in body.group(1)


def test_the_live_block_is_pure(app_source):
    """The parity test can only run this block because it touches no DOM.

    The harness enforces this at runtime by supplying a sandbox with no
    `document` at all; this is the cheaper, earlier signal. Comments are
    stripped first — the block's own docstring names what it does not use.
    """
    start = app_source.index("/* @mdt-live-start */")
    end = app_source.index("/* @mdt-live-end */")
    block = app_source[start:end]
    code = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    for forbidden in ("document", "innerHTML", "querySelector", "addEventListener", "localStorage"):
        assert forbidden not in code, f"the live block reached for {forbidden}"


def test_the_editor_debounces(app_source):
    """Unbounded input handling would reclassify and rebuild the DOM on every
    keypress; the cap keeps a paste from handing the regex engine an
    unbounded string."""
    assert "setTimeout(" in app_source
    assert re.search(r"\}, 1[0-9]{2}\);", app_source), "no ~100ms debounce found"
    assert "MAX_LIVE_CHARS = 20000" in app_source
    assert "slice(0, MAX_LIVE_CHARS)" in app_source
