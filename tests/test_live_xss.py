"""Text typed into the demo must not become markup.

Stage 1 is an editable textarea, so every stage renderer downstream of it now
receives arbitrary text from whoever is at the keyboard. The renderers build
HTML by string concatenation into `innerHTML`, which is exactly the shape where
one unescaped interpolation is a scripting bug.

These tests drive the *shipped* renderers through `window.__MDT_TEST__` rather
than a copy, and assert on the HTML they emit. They are deliberately blunt: no
`<script`, no inline event handler, and no `<` in the output that came from the
input. A cleverer assertion would be easier to satisfy accidentally.
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

# The sentinels `highlight()` wraps matches in before swapping them for <mark>.
# If they survive from the input, the caller chooses the tags.
SENTINELS = ""

PAYLOADS = [
    {"name": "img-onerror", "text": '<img src=x onerror=alert(1)>'},
    {"name": "script-close", "text": '</script><script>alert(1)</script>'},
    {"name": "svg-onload", "text": '<svg/onload=alert(1)>'},
    {"name": "attribute-break", "text": '" onmouseover="alert(1)" x="'},
    {"name": "sentinel-bytes", "text": f'{SENTINELS[0]}script src=//evil{SENTINELS[1]}'},
    {"name": "sentinel-with-markup", "text": f'{SENTINELS[0]}img src=x onerror=alert(1){SENTINELS[1]}'},
    {"name": "mixed-with-a-real-rule", "text": 'NASDAQ will retire TotalView <img src=x onerror=alert(1)>'},
    {"name": "entity-double-encode", "text": '&lt;script&gt;alert(1)&lt;/script&gt;'},
    {"name": "iframe-srcdoc", "text": '<iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;">'},
    {"name": "unicode-and-markup", "text": '日本 <b onclick=alert(1)>tag ٥</b>'},
    # Exactly the characters esc() must neutralise, so its contract can be
    # asserted directly rather than inferred from a larger payload.
    {"name": "bare-metacharacters", "text": "\"'<>&"},
]

# Every renderer output the harness collects, so a new one cannot be added
# without deciding whether it is in scope here.
RENDERED = ["esc", "kv", "kvHTML", "highlight", "stageRaw", "stageRouter",
            "stageImpact", "stageDecision"]

# An `onerror=` sitting in escaped text content is inert; one inside a real tag
# is not. Scan tags only, or the assertion fails on correctly escaped output.
_TAG = re.compile(r"<[^>]*>")
_EVENT_HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    if _NODE is None:
        pytest.fail("MDT_REQUIRE_NODE=1 but node is not installed")
    inputs = tmp_path_factory.mktemp("xss") / "inputs.json"
    inputs.write_text(json.dumps(PAYLOADS), encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(HARNESS), str(ROOT / "index.html"), str(inputs)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    results = json.loads(proc.stdout)
    assert len(results) == len(PAYLOADS)
    # A harness returning empty strings would satisfy every assertion below.
    for result in results:
        for key in RENDERED:
            assert key in result, f"harness produced no {key}"
            assert result[key], f"{result['name']}.{key} rendered nothing"
    return {r["name"]: r for r in results}


_IDS = [p["name"] for p in PAYLOADS]


@pytest.mark.parametrize("payload", PAYLOADS, ids=_IDS)
@pytest.mark.parametrize("renderer", RENDERED)
def test_no_script_tag_survives(payload, renderer, rendered):
    html = rendered[payload["name"]][renderer]
    assert "<script" not in html.lower(), f"{renderer} emitted a script tag"
    assert "</script" not in html.lower()


@pytest.mark.parametrize("payload", PAYLOADS, ids=_IDS)
@pytest.mark.parametrize("renderer", RENDERED)
def test_no_inline_event_handler_survives(payload, renderer, rendered):
    """`esc()` does not escape quotes, so user text must never reach an
    attribute position. A handler inside a real tag means it did."""
    html = rendered[payload["name"]][renderer]
    for tag in _TAG.findall(html):
        assert not _EVENT_HANDLER.search(tag), f"{renderer} emitted a handler in {tag!r}"


@pytest.mark.parametrize("payload", PAYLOADS, ids=_IDS)
@pytest.mark.parametrize("renderer", RENDERED)
def test_no_unescaped_angle_bracket_from_the_input(payload, renderer, rendered):
    """The strong form: strip the markup the renderer is entitled to emit, and
    nothing bracket-shaped may remain."""
    html = rendered[payload["name"]][renderer]
    stripped = re.sub(
        r"</?(?:div|span|p|pre|b|h5|mark|textarea|button|em|code|a|small"
        r"|details|summary)\b[^>]*>",
        "", html,
    )
    assert "<" not in stripped, f"{renderer} leaked a tag: {stripped!r}"


def test_esc_escapes_the_characters_the_other_assertions_lean_on(rendered):
    """Pin `esc()`'s contract, because two tests above silently depend on it.

    `test_no_inline_event_handler_survives` scans `<[^>]*>` for `on*=`; that scan
    is only sound because user text cannot contribute a raw `>` to terminate the
    tag early. And attribute-context injection is only unreachable because
    quotes are escaped. Neither property is obvious from reading those tests, so
    "simplify esc()" is a plausible future cleanup that would quietly defeat
    them. Assert both here.
    """
    assert rendered["bare-metacharacters"]["esc"] == "&quot;&#39;&lt;&gt;&amp;"


@pytest.mark.parametrize("payload", PAYLOADS, ids=_IDS)
def test_no_dangerous_url_scheme_reaches_an_href(payload, rendered):
    """No renderer may emit an `href`/`src` with a non-http(s) scheme.

    There is no sink taking user text into a URL today. This asserts one is not
    added later — the failure mode the battery exists to catch, and the one gap
    the other three assertions miss: `<a href="javascript:alert(1)">` passes all
    of them.
    """
    for renderer, html in rendered[payload["name"]].items():
        for attr, value in re.findall(r'\b(href|src)="([^"]*)"', html):
            scheme = value.split(":", 1)[0].lower() if ":" in value.split("?")[0] else ""
            assert scheme in ("", "http", "https"), (
                f"{renderer} emitted {attr}={value!r} with scheme {scheme!r}"
            )


@pytest.mark.parametrize("payload", PAYLOADS, ids=_IDS)
def test_kv_escapes_its_value_without_help_from_the_caller(payload, rendered):
    """`kv()` must be safe by default.

    It was previously a raw concatenation that relied on every call site
    remembering `esc()`. That is a rule which holds until someone adds the
    call site that forgets, and now user text flows through it.
    """
    html = rendered[payload["name"]]["kv"]
    assert "<" not in html.replace('<div class="k">', "").replace('<div class="v">', "").replace("</div>", "")


@pytest.mark.parametrize("payload", PAYLOADS, ids=_IDS)
def test_highlight_strips_its_own_sentinels_from_the_input(payload, rendered):
    """`highlight()` marks matches with two control bytes and swaps them for
    `<mark>` at the end. Text containing those bytes would choose its own tags,
    so they must be removed from the input before the pattern pass."""
    html = rendered[payload["name"]]["highlight"]
    assert SENTINELS[0] not in html and SENTINELS[1] not in html
    assert html.count("<mark>") == html.count("</mark>")


def test_sentinel_input_cannot_manufacture_a_mark(rendered):
    """The specific defect: sentinels in the input became real tags."""
    html = rendered["sentinel-bytes"]["highlight"]
    assert "<mark>" not in html, "input control bytes were promoted to markup"


def test_a_real_match_is_still_highlighted(rendered):
    """The fix must not disable highlighting — a stripped-to-nothing renderer
    would pass every assertion above."""
    html = rendered["mixed-with-a-real-rule"]["highlight"]
    assert "<mark>" in html and "</mark>" in html
    assert "retire" in html.lower()
