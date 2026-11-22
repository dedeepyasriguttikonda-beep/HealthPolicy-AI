"""Compare freshly collected policy records with Memento history.

Classification per item:
  new        item_id never seen before for this source
  changed    same item, content hash differs and text similarity < threshold (meaningful edit)
  cosmetic   same item, hash differs but similarity >= threshold (whitespace/punctuation) -> treated as unchanged
  unchanged  identical content hash
  removed    previously active item no longer present on a successfully crawled page
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .memento_store import MementoStore
from .preprocess import PolicyRecord

NUM = re.compile(r"(?:₹|\$|rs\.?\s?)?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|crore|lakh|million|billion|days?|hours?|months?|years?)?", re.I)


@dataclass
class Change:
    change_type: str  # new | changed | removed
    record: PolicyRecord | None
    previous: dict | None = None
    similarity: float | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    numbers_changed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def item_id(self) -> str:
        return self.record.item_id if self.record else self.previous["item_id"]

    @property
    def title(self) -> str:
        return self.record.title if self.record else self.previous["title"]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if len(p.strip()) > 3]


def similarity(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[^\w%\s]", " ", s.lower())).strip()
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def sentence_diff(old: str, new: str) -> tuple[list[str], list[str]]:
    o, n = sentences(old), sentences(new)
    added = [s for s in n if s not in o]
    removed = [s for s in o if s not in n]
    return added, removed


def number_diff(old: str, new: str) -> list[tuple[str, str]]:
    on = [m.group(0).strip() for m in NUM.finditer(old)]
    nn = [m.group(0).strip() for m in NUM.finditer(new)]
    gone = [x for x in on if x not in nn]
    came = [x for x in nn if x not in on]
    pairs = list(zip(gone, came))
    pairs += [(g, "") for g in gone[len(pairs):]] + [("", c) for c in came[len(pairs):]]
    return pairs[:10]


@dataclass
class DetectionResult:
    new: list[Change] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)
    removed: list[Change] = field(default_factory=list)
    unchanged: list[PolicyRecord] = field(default_factory=list)
    cosmetic: list[PolicyRecord] = field(default_factory=list)

    @property
    def actionable(self) -> list[Change]:
        return self.new + self.changed + self.removed

    def counts(self) -> dict:
        return {"new": len(self.new), "changed": len(self.changed), "removed": len(self.removed),
                "unchanged": len(self.unchanged) + len(self.cosmetic)}


def detect(records_by_source: dict[str, list[PolicyRecord]], memento: MementoStore,
           threshold: float = 0.97) -> DetectionResult:
    res = DetectionResult()
    for source_id, records in records_by_source.items():
        known = memento.known_items(source_id)
        current_ids = set()
        for rec in records:
            current_ids.add(rec.item_id)
            prev = known.get(rec.item_id)
            if prev is None:
                res.new.append(Change("new", rec))
            elif prev["current_hash"] == rec.content_hash:
                res.unchanged.append(rec)
            else:
                sim = similarity(prev["current_text"], rec.text)
                if sim >= threshold:
                    res.cosmetic.append(rec)
                else:
                    added, removed = sentence_diff(prev["current_text"], rec.text)
                    res.changed.append(Change("changed", rec, prev, round(sim, 3), added, removed,
                                              number_diff(prev["current_text"], rec.text)))
        # only infer removals when the page was crawled successfully and parsed into records
        if records:
            for item_id, prev in known.items():
                if item_id not in current_ids:
                    res.removed.append(Change("removed", None, prev))
    return res
