"""The rule tables have to survive the trip into JavaScript.

The demo now classifies text typed in the browser, so the rules leave Python and
get recompiled by a JS port. Two failure modes are silent and expensive:

* a pattern whose Python and JS semantics differ (``\\b`` and ``\\d`` are
  Unicode-aware in Python and ASCII-only in JS), and
* a pattern shape the rest of the pipeline quietly mis-reads — a capturing group
  flips ``re.findall`` from full-match to group-tuple semantics, which would
  corrupt ``unknown_products`` with no other symptom.

``to_js_pattern`` is therefore a whitelist that fails closed: an unrecognised
construct raises rather than producing a translation nobody checked.
"""

from __future__ import annotations

import re
import time

import pytest

from mdt.decision import rules_snapshot as decision_rules
from mdt.router import rules_snapshot as router_rules
from mdt.rules_export import export_rules, to_js_pattern

# Every regex source that has to cross into JavaScript, as (where, pattern).
_ROUTER = router_rules()
_DECISION = decision_rules()

_SCORING_PATTERNS = [
    (f"type/{label}", pat)
    for label, pats in _ROUTER["type"]
    for pat, _weight in pats
] + [(f"feed/{feed_id}", pat) for pat, feed_id in _ROUTER["feed"]]

_ALL_PATTERNS = _SCORING_PATTERNS + [
    ("router/iso_date", _ROUTER["iso_date"]),
    ("decision/imperative", _DECISION["imperative"]),
    ("decision/calendar", _DECISION["calendar"]),
]


# -- shape of the tables ---------------------------------------------------

def test_no_scored_pattern_has_a_capturing_group():
    """`_score` and the feed loop both count `re.findall` results.

    With a capturing group, findall returns group tuples instead of whole
    matches. Scores would still look plausible while `unknown_products` filled
    up with fragments — a corruption with no other symptom.
    """
    for where, pat in _SCORING_PATTERNS:
        assert re.compile(pat).groups == 0, f"{where}: {pat!r} has a capturing group"


def test_no_pattern_matches_the_empty_string():
    """A zero-length match makes the JS `g`-flag scan advance differently and
    would score every notice on every rule."""
    for where, pat in _ALL_PATTERNS:
        assert re.compile(pat).match("") is None, f"{where}: {pat!r} matches empty"


def test_venue_markers_are_plain_substrings():
    """Venue scoring is `low.count(marker)` — plain counting, not `re`.

    A marker containing regex metacharacters would work in Python (counted
    literally) and silently mean something else if a port ever fed it to a
    regex engine. Keep them boring.
    """
    meta = set(r"\^$.|?*+()[]{}")
    for venue, markers in _ROUTER["venue"]:
        assert markers, f"{venue} has no markers"
        for marker in markers:
            assert marker, f"{venue} has an empty marker"
            assert not (set(marker) & meta), f"{venue}: {marker!r} has regex metacharacters"
            assert marker == marker.lower(), f"{venue}: {marker!r} must be lowercase"


# -- the two rewrites ------------------------------------------------------

_NOT_WORD_BEFORE = r"(?<![\p{L}\p{N}_])"
_NOT_WORD_AFTER = r"(?![\p{L}\p{N}_])"


def test_word_boundary_is_rewritten_by_side():
    """`\\b` is Unicode-aware in Python and ASCII-only in JS.

    Untranslated, `\\bsec\\b` would match inside "日本sec" in the browser and not
    in Python. The lookaround forms restore Python's definition.
    """
    assert to_js_pattern(r"\bretire") == _NOT_WORD_BEFORE + "retire"
    assert to_js_pattern(r"\bformat\b") == _NOT_WORD_BEFORE + "format" + _NOT_WORD_AFTER


def test_digit_class_is_rewritten():
    """JS `\\d` is `[0-9]`; Python's matches every Unicode decimal digit."""
    assert to_js_pattern(r"\btag \d+") == _NOT_WORD_BEFORE + r"tag \p{Nd}+"
    assert to_js_pattern(r"\b20\d{2}-\d{2}-\d{2}\b") == (
        _NOT_WORD_BEFORE + r"20\p{Nd}{2}-\p{Nd}{2}-\p{Nd}{2}" + _NOT_WORD_AFTER
    )


def test_non_capturing_groups_and_alternation_pass_through():
    assert to_js_pattern(r"\bnew (?:market data )?multicast") == (
        _NOT_WORD_BEFORE + r"new (?:market data )?multicast"
    )
    assert to_js_pattern(r"\bipo\b|\binitial public offering\b") == (
        _NOT_WORD_BEFORE + "ipo" + _NOT_WORD_AFTER + "|"
        + _NOT_WORD_BEFORE + "initial public offering" + _NOT_WORD_AFTER
    )


@pytest.mark.parametrize("pattern", [
    r"(?i)retire",          # inline flags: JS has no equivalent mid-pattern
    r"\wretire",            # \w differs the same way \b does
    r"\sretire",
    r"\Dretire",
    r"retire\Z",
    r"(retire)",            # capturing group: changes findall semantics
    r"(retire)\1",
    r"(?=retire)x",         # lookahead we have not reasoned about
    r"(?<=x)retire",
    r"[a-z]retire",         # class semantics under the u flag are subtle
    r"^retire",             # ^/$ differ on trailing newlines
    r"retire$",
    r"retir.",              # . matches \r and U+2028 in Python, not in JS
    r"retire*?",            # lazy quantifier: unused, so unreviewed
    r"\-retire",            # identity escape is a SyntaxError in u mode
])
def test_to_js_pattern_fails_closed(pattern):
    """Anything outside the whitelist raises rather than guessing."""
    with pytest.raises(ValueError):
        to_js_pattern(pattern)


@pytest.mark.parametrize("pattern,because", [
    (r"retire)", "unbalanced close paren"),
    (r"retire|", "empty alternative"),
    (r"(?:)retire", "empty group body"),
    (r"retire\\", "trailing backslash"),
    (r"(?:retire", "unclosed group"),
    (r"\b?retire", "a quantified \\b is meaningless"),
    (r"retire{2", "unclosed repetition"),
    (r"retire{a}", "repetition count that is not a count"),
    (r"retire{2,3}?", "lazy repetition"),
    (r"foo\bbar", "a \\b between two word characters can never match"),
    (r"(?:-)\b(?:-)", "no way to tell which side the \\b asserts"),
])
def test_malformed_and_ambiguous_patterns_raise(pattern, because):
    """The fail-closed paths, which are the entire value of the whitelist.

    None of these appear in the shipped tables — that is the point. They are the
    shapes a future rule might take, and each one has to stop the build rather
    than produce a translation whose JS meaning nobody has checked.
    """
    with pytest.raises(ValueError):
        to_js_pattern(pattern)


@pytest.mark.parametrize("bad", ["", None, 42])
def test_non_patterns_raise(bad):
    with pytest.raises(ValueError):
        to_js_pattern(bad)


def test_shipped_patterns_all_convert():
    """Every rule actually in the tables must be translatable."""
    for where, pat in _ALL_PATTERNS:
        js = to_js_pattern(pat)
        assert js, f"{where} converted to nothing"
        assert r"\b" not in js, f"{where}: {js!r} still has a raw \\b"
        assert r"\d" not in js, f"{where}: {js!r} still has a raw \\d"


# -- no pattern may be a denial of service ---------------------------------

def test_every_pattern_is_fast_on_hostile_input():
    """The browser runs these on whatever an interviewer types.

    Catastrophic backtracking in a rule would hang the tab; 20k chars is the
    textarea cap, so this is the worst case the UI can hand the engine.
    """
    hostile = ["a" * 20000, "tag " + "1" * 20000, " " * 20000, "-" * 20000]
    for where, pat in _ALL_PATTERNS:
        compiled = re.compile(pat, re.IGNORECASE)
        for text in hostile:
            start = time.perf_counter()
            compiled.findall(text)
            elapsed = time.perf_counter() - start
            assert elapsed < 0.05, f"{where} took {elapsed:.3f}s on {text[:8]!r}…"


# -- constants the JS port needs to agree on -------------------------------

def test_decision_snapshot_exposes_the_tuning_constants():
    """`12` and `0.5` are decisions, not magic numbers, and the browser copy
    must read the same ones rather than a hand-typed duplicate."""
    assert _DECISION["blast_threshold"] == 12
    assert _DECISION["confidence_floor"] == 0.5
    assert _DECISION["priorities"] == ["low", "medium", "high"]
    assert {t for t, _p in _DECISION["base"]} == set(_ROUTER["notice_types"])


def test_rule_tables_are_pairs_not_objects():
    """Declaration order carries meaning — evidence order, and the venue
    tie-break that makes `nasdaq` win. A JSON object would not promise it."""
    assert isinstance(_ROUTER["venue"], list)
    assert _ROUTER["venue"][0][0] == "nasdaq"
    for entry in _ROUTER["type"]:
        assert isinstance(entry, list) and len(entry) == 2
    for entry in _ROUTER["feed"]:
        assert isinstance(entry, list) and len(entry) == 2


def test_export_carries_both_pattern_sources():
    """`evidence` must name the Python rule, not its JS translation.

    The browser matches on the translated pattern but reports the original, so
    a rule that fires in the demo is quotable against the repo.
    """
    exported = export_rules()
    for label, rules in exported["router"]["type"]:
        for py_src, js_src, weight in rules:
            assert to_js_pattern(py_src) == js_src, f"{label}: {py_src!r} mistranslated"
            assert isinstance(weight, int) and weight > 0
    for py_src, js_src, feed_id in exported["router"]["feed"]:
        assert to_js_pattern(py_src) == js_src
        assert feed_id is None or isinstance(feed_id, str)
