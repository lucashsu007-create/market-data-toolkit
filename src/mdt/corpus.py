"""Load the real-notice corpus: records, ground-truth labels, frozen split."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"


@dataclass(frozen=True)
class Notice:
    id: str
    venue: str
    source_url: str
    published: str
    notice_no: str
    title: str
    summary: str
    quote: str
    effective: str | None
    depth: str

    @property
    def text(self) -> str:
        """What the router is allowed to see. Venue and the record's own
        `effective` field are deliberately excluded — deriving them is the
        router's job, and feeding them in would grade it on its own answers."""
        return f"{self.title}\n{self.summary}"


def load_notices(corpus_dir: Path = CORPUS_DIR) -> dict[str, Notice]:
    notices = {}
    for path in sorted((corpus_dir / "notices").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        notices[raw["id"]] = Notice(**raw)
    return notices


def load_labels(corpus_dir: Path = CORPUS_DIR) -> dict[str, dict]:
    return json.loads((corpus_dir / "labels.json").read_text(encoding="utf-8"))


def load_split(corpus_dir: Path = CORPUS_DIR) -> dict:
    return json.loads((corpus_dir / "split.json").read_text(encoding="utf-8"))
