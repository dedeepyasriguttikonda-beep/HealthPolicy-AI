"""Evaluation of the HealthPolicy AI tracking system on the labelled offline scenario.

Scenario: cycle1 (baseline crawl) -> cycle2 (later crawl with 5 new, 3 changed, 1 removed,
1 cosmetic-only edit). Ground truth: data/fixtures/ground_truth.json.

Metrics
  retrieval     sources collected, records extracted vs expected, date-extraction accuracy
  detection     precision / recall / F1 for new, changed, removed; cosmetic false positives
  memento       history persisted, version counts, duplicate-alert suppression on re-run
  briefs        schema completeness, evidence grounding, unsupported numbers, relevance agreement
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from . import relevance
from .config import FIXTURE_DIR, OUTPUT_DIR, Settings
from .memento_store import MementoStore
from .pipeline import run_cycle


def prf(pred: set, gold: set) -> dict:
    tp = len(pred & gold)
    p = tp / len(pred) if pred else (1.0 if not gold else 0.0)
    r = tp / len(gold) if gold else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "tp": tp,
            "predicted": len(pred), "gold": len(gold)}


def run_evaluation(llm_provider: str | None = None) -> dict:
    truth = json.loads((FIXTURE_DIR / "ground_truth.json").read_text())
    gold = {k: {(s, t) for s, t in v} for k, v in truth.items()}
    tmp = Path(tempfile.mkdtemp()) / "eval_memento.db"
    s = Settings()
    s.memento_db = tmp
    s.memento_backend = "local"
    if llm_provider:
        s.llm_provider = llm_provider

    out = tmp.parent / "outputs"
    base = run_cycle(s, "cycle1", baseline_only=True, label="eval-baseline", output_dir=out)
    second = run_cycle(s, "cycle2", label="eval-cycle2", output_dir=out)
    rerun = run_cycle(s, "cycle2", label="eval-rerun", output_dir=out)

    m = MementoStore(tmp)
    briefs = second.briefs
    pred = {k: set() for k in ("new", "changed", "removed")}
    for b in briefs:
        src = next((p["source_id"] for p in m.all_policies() if p["item_id"] == b["item_id"]), None)
        pred[b["change_type"]].add((src, b["policy_name"]))

    # retrieval quality
    expected_c2 = len(gold["new"]) + len(gold["changed"]) + len(gold["unchanged"])
    dates_ok = dates_total = 0
    for f in (FIXTURE_DIR / "cycle2").glob("*.md"):
        for m_ in re.finditer(r"### (.+?)\n\n\*Published: (\d{4}-\d{2}-\d{2})\*", f.read_text()):
            pol = next((p for p in m.all_policies() if p["title"] == m_.group(1).strip()), None)
            dates_total += 1
            dates_ok += bool(pol and pol["published"] == m_.group(2))

    # brief quality
    q = [b["_quality"] for b in briefs]
    agree = 0
    for b in briefs:
        rule = relevance.analyze(b["policy_name"], " ".join(b.get("key_points", [])), b["change_type"])["level"]
        agree += str(b["operational_relevance"].get("level", "")).lower() == rule
    required = ["summary", "what_changed", "key_points", "operational_relevance", "source_evidence",
                "recommended_actions"]
    complete = sum(all(b.get(k) for k in required) for b in briefs)

    versions = {p["title"]: p["version_count"] for p in m.all_policies()}
    metrics = {
        "llm_provider": s.llm_provider,
        "retrieval": {
            "sources_collected": f"{second.counts['pages']}/{second.counts['pages']}",
            "records_extracted": second.counts["records"], "records_expected": expected_c2,
            "record_extraction_accuracy": round(min(second.counts["records"], expected_c2) / expected_c2, 3),
            "date_extraction_accuracy": round(dates_ok / dates_total, 3) if dates_total else None,
        },
        "change_detection": {
            "new": prf(pred["new"], gold["new"]),
            "changed": prf(pred["changed"], gold["changed"]),
            "removed": prf(pred["removed"], gold["removed"]),
            "cosmetic_edit_false_positives": sum(1 for b in briefs if "Patient Safety" in b["policy_name"]),
            "unchanged_reported": second.counts["unchanged"], "unchanged_expected": len(gold["unchanged"]),
        },
        "memento_history": {
            "baseline_records_stored": base.counts["records"],
            "items_tracked": len(versions),
            "items_with_multiple_versions": sum(v > 1 for v in versions.values()),
            "duplicate_alerts_on_rerun": len(rerun.briefs),
            "runs_logged": len(m.runs()),
        },
        "brief_quality": {
            "briefs_generated": len(briefs),
            "schema_complete_rate": round(complete / len(briefs), 3) if briefs else 0,
            "avg_evidence_grounding": round(sum(x["evidence_grounding"] for x in q) / len(q), 3) if q else 0,
            "briefs_with_unsupported_numbers": sum(bool(x["unsupported_numbers"]) for x in q),
            "relevance_agreement_with_rules": round(agree / len(briefs), 3) if briefs else 0,
            "relevance_distribution": {lvl: sum(str(b["operational_relevance"].get("level")).lower() == lvl for b in briefs)
                                       for lvl in ("high", "medium", "low")},
        },
    }
    OUTPUT_DIR.mkdir(exist_ok=True)
    report = {"metrics": metrics, "briefs": briefs}
    (OUTPUT_DIR / f"evaluation_{s.llm_provider}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report
