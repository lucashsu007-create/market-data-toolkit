"""Ship the rule tables to the browser without shipping a second copy of them.

The demo classifies text typed into the page, which means every rule in
`router.py` and `decision.py` has to run again in JavaScript. Retyping the
tables in `index.html` would guarantee they drift, so they are exported from the
Python source of truth and recompiled client-side.

That leaves one real hazard: Python and JS regexes are not the same language.
Two constructs in these tables mean different things in each engine, and both
differences are silent — the pattern compiles either way and just matches
different text:

* ``\\b`` — Python's word character is Unicode alphanumeric plus underscore; a
  JS ``\\b`` only knows ``[A-Za-z0-9_]``. ``\\bsec\\b`` finds "sec" inside
  "日本sec" in a browser and not in Python.
* ``\\d`` — Python matches every Unicode decimal digit, JS matches ``[0-9]``.
  ``\\btag \\d+`` fires on "tag ٥" in Python only.

`to_js_pattern` rewrites both into ``\\p{...}`` lookarounds that restore the
Python meaning under the ``u`` flag, and refuses everything it has not been
taught. Fail-closed is the point: an unreviewed construct becomes an exception
at build time instead of a wrong classification in front of an interviewer.
"""

from __future__ import annotations

import re

from . import decision, router

#: Python's word character for `str` patterns is `str.isalnum()` plus
#: underscore — categories L*, Nd, Nl, No. `\p{L}\p{N}_` is exactly that set.
WORD_CLASS = r"[\p{L}\p{N}_]"
NOT_WORD_BEFORE = f"(?<!{WORD_CLASS})"
NOT_WORD_AFTER = f"(?!{WORD_CLASS})"

#: Python `\d` on `str` is `Py_UNICODE_ISDECIMAL`, i.e. category Nd.
DIGIT_CLASS = r"\p{Nd}"

# Characters that mean something to a JS regex and so must be escaped if they
# ever arrive as literals.
_JS_SYNTAX = set(r"^$\.*+?()[]{}|/")

# --- presentation lookups the in-browser pipeline also needs ---------------
# These live here rather than in build_payload.py because both the payload
# builder and the JS port read them; one of the two would otherwise be a copy.

ASSET_CLASS = {"cme": "futures", "nasdaq": "equities"}
ASSET_CLASS_DEFAULT = "mixed"

ACTIONS = {
    "feed_change": "Plan and verify migration/connectivity work with every impacted owner before the effective date.",
    "format_change": "Confirm parsers and downstream schemas handle the new format; schedule testing before the effective date.",
    "operational": "Note the operational change; verify schedules and capacity assumptions where relevant.",
    "regulatory": "Track the regulatory item; no immediate system change.",
    "reference_data": "Apply reference-data updates on the effective date.",
    "admin_other": "No action: administrative item.",
}


# --- the converter ---------------------------------------------------------


class _Atom:
    """One parsed unit, plus whether it is guaranteed to start/end on a word
    character. `None` means "cannot be determined", which is what makes an
    ambiguous `\\b` fail closed instead of guessing a side."""

    __slots__ = ("js", "starts_word", "ends_word", "optional", "is_boundary")

    def __init__(self, js, starts_word, ends_word, optional=False, is_boundary=False):
        self.js = js
        self.starts_word = starts_word
        self.ends_word = ends_word
        self.optional = optional
        self.is_boundary = is_boundary


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


class _Parser:
    def __init__(self, pattern: str) -> None:
        self.src = pattern
        self.i = 0

    def fail(self, msg: str):
        return ValueError(
            f"to_js_pattern cannot translate {self.src!r} at offset {self.i}: {msg}. "
            "Extend the whitelist deliberately, and add a parity fixture for it."
        )

    # -- entry -------------------------------------------------------------

    def parse(self) -> list[list[_Atom]]:
        """Top-level alternation: a list of alternatives, each a list of atoms."""
        alternatives = [self._sequence()]
        while self.i < len(self.src) and self.src[self.i] == "|":
            self.i += 1
            alternatives.append(self._sequence())
        if self.i < len(self.src):
            raise self.fail(f"unexpected {self.src[self.i]!r}")
        return alternatives

    def _sequence(self) -> list[_Atom]:
        atoms: list[_Atom] = []
        while self.i < len(self.src) and self.src[self.i] not in "|)":
            atoms.append(self._atom())
        if not atoms:
            raise self.fail("empty alternative")
        return atoms

    # -- atoms -------------------------------------------------------------

    def _atom(self) -> _Atom:
        ch = self.src[self.i]

        if ch == "\\":
            atom = self._escape()
        elif ch == "(":
            atom = self._group()
        elif ch in "^$.[]{}*+?":
            raise self.fail(f"{ch!r} is not in the whitelist")
        else:
            self.i += 1
            js = ("\\" + ch) if ch in _JS_SYNTAX else ch
            word = _is_word_char(ch)
            atom = _Atom(js, word, word)

        return self._quantify(atom)

    def _escape(self) -> _Atom:
        if self.i + 1 >= len(self.src):
            raise self.fail("trailing backslash")
        kind = self.src[self.i + 1]
        self.i += 2
        if kind == "b":
            return _Atom("", None, None, is_boundary=True)
        if kind == "d":
            return _Atom(DIGIT_CLASS, True, True)
        raise self.fail(
            rf"\{kind} is not in the whitelist"
            + (r" (\w and \s differ between Python and JS just as \b does)"
               if kind in "wWsS" else "")
        )

    def _group(self) -> _Atom:
        if not self.src.startswith("(?:", self.i):
            if self.src.startswith("(?", self.i):
                raise self.fail("only (?:...) groups are supported")
            raise self.fail(
                "capturing groups change re.findall from whole matches to group "
                "tuples; use (?:...)"
            )
        self.i += 3
        alternatives = [self._sequence()]
        while self.i < len(self.src) and self.src[self.i] == "|":
            self.i += 1
            alternatives.append(self._sequence())
        if self.i >= len(self.src) or self.src[self.i] != ")":
            raise self.fail("unclosed (?: group")
        self.i += 1

        rendered = "|".join(_render(alt) for alt in alternatives)
        return _Atom(
            f"(?:{rendered})",
            _agree(_edge(alt, first=True) for alt in alternatives),
            _agree(_edge(alt, first=False) for alt in alternatives),
        )

    def _quantify(self, atom: _Atom) -> _Atom:
        if self.i >= len(self.src):
            return atom
        ch = self.src[self.i]
        if ch in "*+?":
            if atom.is_boundary:
                raise self.fail("cannot quantify \\b")
            self.i += 1
            suffix = ch
            optional = ch in "*?"
        elif ch == "{":
            close = self.src.find("}", self.i)
            if close == -1:
                raise self.fail("unclosed {")
            body = self.src[self.i + 1:close]
            if not re.fullmatch(r"\d+(?:,\d*)?", body):
                raise self.fail(f"{{{body}}} is not a plain repetition count")
            self.i = close + 1
            suffix = "{" + body + "}"
            optional = body.startswith("0")
        else:
            return atom

        if self.i < len(self.src) and self.src[self.i] in "?+":
            raise self.fail("lazy and possessive quantifiers are not in the whitelist")

        return _Atom(atom.js + suffix, atom.starts_word, atom.ends_word, optional=optional)


def _agree(values):
    """A property only survives if every alternative agrees on it."""
    seen = set(values)
    return seen.pop() if len(seen) == 1 else None


def _edge(atoms: list[_Atom], first: bool):
    """Whether a sequence is guaranteed to start (or end) on a word character.

    Boundaries are skipped — they consume nothing. An optional atom does not end
    the search: `channels?` ends on a word character whether or not the `s` is
    there, so the scan keeps going and only gives up if the candidates disagree.
    """
    ordered = atoms if first else list(reversed(atoms))
    candidates = []
    for atom in ordered:
        if atom.is_boundary:
            continue
        value = atom.starts_word if first else atom.ends_word
        if value is None:
            return None
        candidates.append(value)
        if not atom.optional:
            break
    if not candidates:
        return None
    return candidates[0] if all(c == candidates[0] for c in candidates) else None


def _render(atoms: list[_Atom]) -> str:
    """Emit a sequence, resolving each `\\b` to the side it is really asserting."""
    out = []
    for idx, atom in enumerate(atoms):
        if not atom.is_boundary:
            out.append(atom.js)
            continue
        before = _edge(atoms[:idx], first=False)
        after = _edge(atoms[idx + 1:], first=True)
        # `\b` asserts a word char on exactly one side. Whichever side the
        # pattern pins, the assertion reduces to "no word char on the other".
        if after and not before:
            out.append(NOT_WORD_BEFORE)
        elif before and not after:
            out.append(NOT_WORD_AFTER)
        elif before and after:
            raise ValueError(
                r"\b between two word characters can never match; "
                "refusing to translate a dead rule"
            )
        else:
            raise ValueError(
                r"cannot tell which side this \b asserts; the whitelist will not "
                "guess, because guessing wrong is silent"
            )
    return "".join(out)


def to_js_pattern(pattern: str) -> str:
    """Translate a Python regex into an equivalent JS source for the `u` flag.

    Whitelist-based and fail-closed: raises `ValueError` on any construct whose
    Python/JS equivalence has not been established here.
    """
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty string")
    # A pattern Python cannot compile is not ours to translate. Re-raised as
    # ValueError so callers have one exception type to catch for "refused".
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{pattern!r} is not a valid Python regex: {exc}") from exc
    alternatives = _Parser(pattern).parse()
    return "|".join(_render(alt) for alt in alternatives)


# --- the exported block ----------------------------------------------------


def export_rules() -> dict:
    """Everything the in-browser pipeline needs, translated and ready to compile.

    Goes into the existing `site-data` payload rather than a block of its own,
    so the CI drift check (`git diff --exit-code index.html`) covers the rules
    for free.
    """
    r = router.rules_snapshot()
    d = decision.rules_snapshot()
    return {
        "router": {
            "venue": r["venue"],
            # Triples: (python source, javascript source, weight). Both sources
            # travel because they do different jobs — JS matches on its own
            # translation, but `evidence` must report the *Python* pattern, so
            # that what the browser says fired is the same string the corpus
            # results and the write-up quote.
            "type": [
                [label, [[pat, to_js_pattern(pat), weight] for pat, weight in pats]]
                for label, pats in r["type"]
            ],
            "feed": [[pat, to_js_pattern(pat), feed_id] for pat, feed_id in r["feed"]],
            "iso_date": to_js_pattern(r["iso_date"]),
            "notice_types": r["notice_types"],
        },
        "decision": {
            "base": d["base"],
            "priorities": d["priorities"],
            "imperative": to_js_pattern(d["imperative"]),
            "calendar": to_js_pattern(d["calendar"]),
            "confidence_floor": d["confidence_floor"],
            "blast_threshold": d["blast_threshold"],
        },
        "presentation": {
            "asset_class": [[venue, cls] for venue, cls in ASSET_CLASS.items()],
            "asset_class_default": ASSET_CLASS_DEFAULT,
            "actions": [[notice_type, text] for notice_type, text in ACTIONS.items()],
        },
    }
