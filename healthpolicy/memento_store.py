"""Memento - persistent policy history for HealthPolicy AI.

The Memento store remembers every policy item that has been collected and reviewed, with
a full version history, so each new crawl can be compared against what is already known.

Tables (SQLite, file: data/memento.db):
  runs          one row per tracking cycle
  policies      latest known state of every policy item (item_id is stable across crawls)
  versions      every distinct content version of an item (content_hash), with timestamps
  briefs        generated LLM update briefs, linked to the version that triggered them
  reviews       human review status of an item (new -> reviewed / dismissed)

Optional: with MEMENTO_BACKEND=memento-memory the same facts are mirrored into the
`memento-memory` bitemporal knowledge graph (pip install memento-memory) so an agent can
recall policy history semantically. The SQLite store remains the source of truth.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .preprocess import PolicyRecord

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, finished_at TEXT, mode TEXT, label TEXT,
    pages INTEGER DEFAULT 0, records INTEGER DEFAULT 0,
    new INTEGER DEFAULT 0, changed INTEGER DEFAULT 0, unchanged INTEGER DEFAULT 0, removed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS policies (
    item_id TEXT PRIMARY KEY, source_id TEXT, source_name TEXT, url TEXT, category TEXT, region TEXT,
    authority TEXT, title TEXT, published TEXT, link TEXT, current_hash TEXT, current_text TEXT,
    first_seen TEXT, last_seen TEXT, last_changed TEXT, status TEXT DEFAULT 'active', version_count INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, content_hash TEXT, text TEXT, published TEXT,
    seen_at TEXT, run_id INTEGER, UNIQUE(item_id, content_hash)
);
CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, content_hash TEXT, change_type TEXT,
    brief_json TEXT, provider TEXT, model TEXT, created_at TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS reviews (
    item_id TEXT PRIMARY KEY, status TEXT, note TEXT, reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_policies_source ON policies(source_id);
CREATE INDEX IF NOT EXISTS ix_versions_item ON versions(item_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MementoStore:
    def __init__(self, db_path: Path, backend: str = "local"):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.backend = backend
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.graph = _GraphMirror() if backend == "memento-memory" else None

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---------- runs ----------
    def start_run(self, mode: str, label: str = "") -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO runs(started_at, mode, label) VALUES (?,?,?)", (now(), mode, label))
            return cur.lastrowid

    def finish_run(self, run_id: int, **counts):
        cols = ", ".join(f"{k}=?" for k in counts)
        with self.tx() as c:
            c.execute(f"UPDATE runs SET finished_at=?, {cols} WHERE run_id=?", (now(), *counts.values(), run_id))

    def runs(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM runs ORDER BY run_id DESC")]

    # ---------- recall ----------
    def recall(self, item_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM policies WHERE item_id=?", (item_id,)).fetchone()
        return dict(r) if r else None

    def known_items(self, source_id: str) -> dict[str, dict]:
        rows = self.conn.execute("SELECT * FROM policies WHERE source_id=? AND status='active'", (source_id,))
        return {r["item_id"]: dict(r) for r in rows}

    def history(self, item_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM versions WHERE item_id=? ORDER BY id", (item_id,))
        return [dict(r) for r in rows]

    def is_reviewed(self, item_id: str, content_hash: str) -> bool:
        """True if a brief already exists for exactly this version (prevents duplicate alerts)."""
        r = self.conn.execute("SELECT 1 FROM briefs WHERE item_id=? AND content_hash=?", (item_id, content_hash)).fetchone()
        return r is not None

    def all_policies(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM policies ORDER BY last_changed DESC")]

    def briefs(self, run_id: int | None = None) -> list[dict]:
        q, args = "SELECT * FROM briefs", ()
        if run_id is not None:
            q, args = q + " WHERE run_id=?", (run_id,)
        out = []
        for r in self.conn.execute(q + " ORDER BY id DESC", args):
            d = dict(r)
            d["brief"] = json.loads(d.pop("brief_json"))
            out.append(d)
        return out

    # ---------- remember ----------
    def remember(self, rec: PolicyRecord, run_id: int) -> None:
        t = now()
        with self.tx() as c:
            existing = c.execute("SELECT current_hash, version_count FROM policies WHERE item_id=?", (rec.item_id,)).fetchone()
            if existing is None:
                c.execute(
                    """INSERT INTO policies(item_id, source_id, source_name, url, category, region, authority, title,
                       published, link, current_hash, current_text, first_seen, last_seen, last_changed)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rec.item_id, rec.source_id, rec.source_name, rec.url, rec.category, rec.region, rec.authority,
                     rec.title, rec.published, rec.link, rec.content_hash, rec.text, t, t, t))
            elif existing["current_hash"] != rec.content_hash:
                c.execute(
                    """UPDATE policies SET current_hash=?, current_text=?, published=?, link=?, last_seen=?,
                       last_changed=?, status='active', version_count=version_count+1 WHERE item_id=?""",
                    (rec.content_hash, rec.text, rec.published, rec.link, t, t, rec.item_id))
            else:
                c.execute("UPDATE policies SET last_seen=?, status='active' WHERE item_id=?", (t, rec.item_id))
            c.execute("INSERT OR IGNORE INTO versions(item_id, content_hash, text, published, seen_at, run_id) VALUES (?,?,?,?,?,?)",
                      (rec.item_id, rec.content_hash, rec.text, rec.published, t, run_id))
        if self.graph:
            self.graph.ingest(f"[{rec.authority}] {rec.title} (published {rec.published or 'unknown'}): {rec.text[:800]}", t)

    def touch_unchanged(self, rec: PolicyRecord) -> None:
        """Seen again with only cosmetic edits: keep the reviewed version, update last_seen."""
        with self.tx() as c:
            c.execute("UPDATE policies SET last_seen=? WHERE item_id=?", (now(), rec.item_id))

    def mark_removed(self, item_id: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE policies SET status='removed', last_changed=? WHERE item_id=?", (now(), item_id))

    def save_brief(self, item_id: str, content_hash: str, change_type: str, brief: dict,
                   provider: str, model: str, run_id: int) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO briefs(item_id, content_hash, change_type, brief_json, provider, model, created_at, run_id) VALUES (?,?,?,?,?,?,?,?)",
                      (item_id, content_hash, change_type, json.dumps(brief, ensure_ascii=False), provider, model, now(), run_id))
            c.execute("INSERT OR REPLACE INTO reviews(item_id, status, note, reviewed_at) VALUES (?,?,?,?)",
                      (item_id, "brief_generated", "", now()))
        if self.graph:
            self.graph.ingest(f"Policy update brief ({change_type}) for '{brief.get('policy_name')}': {brief.get('summary')}", now())

    def set_review(self, item_id: str, status: str, note: str = "") -> None:
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO reviews(item_id, status, note, reviewed_at) VALUES (?,?,?,?)",
                      (item_id, status, note, now()))

    def related_context(self, query: str) -> str:
        """Semantic recall from the memento-memory graph (empty string when not enabled)."""
        return self.graph.recall(query) if self.graph else ""

    def reset(self) -> None:
        self.conn.close()
        Path(self.db_path).unlink(missing_ok=True)
        self.__init__(self.db_path, self.backend)


class _GraphMirror:
    """Thin wrapper around memento-memory's MemoryStore; failures never break the pipeline."""

    def __init__(self):
        try:
            from memento import MemoryStore

            self.store = MemoryStore()
        except Exception as e:  # not installed / no LLM key for extraction
            log.warning("memento-memory graph disabled: %s", e)
            self.store = None

    def ingest(self, text: str, ts: str) -> None:
        if self.store:
            try:
                self.store.ingest(text, source_type="document", timestamp=ts)
            except Exception as e:
                log.warning("memento-memory ingest failed: %s", e)

    def recall(self, query: str) -> str:
        if not self.store:
            return ""
        try:
            return self.store.recall(query, token_budget=600).text
        except Exception as e:
            log.warning("memento-memory recall failed: %s", e)
            return ""
