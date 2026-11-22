"""End-to-end HealthPolicy AI tracking cycle.

collect (Firecrawl) -> preprocess -> detect changes vs Memento -> LLM briefs -> remember -> report
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from .briefs import generate_brief, render_markdown
from .change_detector import detect
from .collector import FirecrawlCollector, OfflineCollector, collect
from .config import OUTPUT_DIR, Settings, load_sources
from .llm import LLMClient
from .memento_store import MementoStore
from .preprocess import to_records

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    run_id: int
    counts: dict
    briefs: list[dict]
    pages: list[dict]
    output_md: str
    output_json: str


def run_cycle(settings: Settings | None = None, offline_cycle: str | None = None,
              source_ids: list[str] | None = None, baseline_only: bool = False,
              label: str = "", output_dir=None) -> RunReport:
    settings = settings or Settings()
    sources = load_sources()
    if source_ids:
        sources = [s for s in sources if s.id in source_ids]
    collector = OfflineCollector(offline_cycle) if offline_cycle else FirecrawlCollector(settings)
    mode = f"offline:{offline_cycle}" if offline_cycle else "live"
    memento = MementoStore(settings.memento_db, settings.memento_backend)
    llm = LLMClient(settings)
    run_id = memento.start_run(mode, label)

    # 1. collect
    pages = collect(sources, collector)
    # 2. preprocess
    records_by_source = {p.source_id: to_records(p) for p in pages if p.status == "ok"}
    n_records = sum(len(v) for v in records_by_source.values())
    # 3. detect against Memento history
    result = detect(records_by_source, memento, settings.change_threshold)
    log.info("Run %d: %s", run_id, result.counts())

    # 4. briefs for actionable changes (skip versions already briefed -> no duplicate alerts)
    briefs = []
    for ch in result.actionable:
        content_hash = ch.record.content_hash if ch.record else ch.previous["current_hash"] + ":removed"
        if baseline_only or memento.is_reviewed(ch.item_id, content_hash):
            continue
        context = memento.related_context(ch.title)
        brief = generate_brief(ch, llm, context)
        brief["item_id"] = ch.item_id
        memento.save_brief(ch.item_id, content_hash, ch.change_type, brief, llm.provider, llm.model, run_id)
        briefs.append(brief)

    # 5. remember the new state
    for recs in records_by_source.values():
        for rec in recs:
            memento.remember(rec, run_id)
    for rec in result.cosmetic:
        memento.touch_unchanged(rec)
    for ch in result.removed:
        memento.mark_removed(ch.item_id)

    counts = {"pages": len(pages), "records": n_records, **result.counts()}
    memento.finish_run(run_id, **counts)
    md_path, json_path = write_outputs(run_id, mode, counts, briefs, pages, output_dir or OUTPUT_DIR)
    return RunReport(run_id, counts, briefs, [p.to_dict() | {"markdown": p.markdown[:300]} for p in pages],
                     str(md_path), str(json_path))


def write_outputs(run_id, mode, counts, briefs, pages, out_dir=OUTPUT_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    order = {"high": 0, "medium": 1, "low": 2}
    briefs = sorted(briefs, key=lambda b: order.get(str(b["operational_relevance"].get("level")).lower(), 3))
    md = [f"# HealthPolicy AI — Policy Update Digest (run {run_id})", "",
          f"Mode: `{mode}` · Generated: {stamp}", "",
          "| Pages | Records | New | Changed | Removed | Unchanged |", "|---|---|---|---|---|---|",
          f"| {counts['pages']} | {counts['records']} | {counts['new']} | {counts['changed']} | {counts['removed']} | {counts['unchanged']} |", ""]
    errs = [p for p in pages if p.status != "ok"]
    if errs:
        md += ["**Sources that failed this run:** " + ", ".join(f"{p.source_id} ({p.error})" for p in errs), ""]
    md += [render_markdown(b) + "\n---\n" for b in briefs] or ["_No new or changed policies detected._"]
    md_path = out_dir / f"digest_run{run_id}_{stamp}.md"
    json_path = out_dir / f"briefs_run{run_id}_{stamp}.json"
    md_path.write_text("\n".join(md), encoding="utf-8")
    json_path.write_text(json.dumps({"run_id": run_id, "mode": mode, "counts": counts, "briefs": briefs},
                                    indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path
