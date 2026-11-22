"""HealthPolicy AI command line.

Examples
  python run.py track                         # live: Firecrawl + LLM (needs API keys in .env)
  python run.py track --offline cycle1        # offline demo, first crawl (baseline)
  python run.py track --offline cycle2        # offline demo, later crawl -> detects changes
  python run.py collect                       # Deliverable 1: collect + preprocess only, save records
  python run.py history                       # show Memento history
  python run.py evaluate                      # run the evaluation suite on the offline scenario
  python run.py reset                         # clear Memento history
"""
import argparse
import json
import logging
import sys

from healthpolicy.config import DATA_DIR, OUTPUT_DIR, Settings, load_sources
from healthpolicy.memento_store import MementoStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def cmd_track(a):
    from healthpolicy.pipeline import run_cycle

    s = Settings()
    if a.llm:
        s.llm_provider = a.llm
    r = run_cycle(s, a.offline, a.sources, a.baseline_only, a.label or "")
    print(json.dumps(r.counts, indent=2))
    print(f"Briefs generated: {len(r.briefs)}\nDigest: {r.output_md}\nJSON:   {r.output_json}")


def cmd_collect(a):
    from healthpolicy.collector import FirecrawlCollector, OfflineCollector, collect
    from healthpolicy.preprocess import to_records

    s = Settings()
    col = OfflineCollector(a.offline) if a.offline else FirecrawlCollector(s)
    pages = collect(load_sources(), col)
    rows = []
    for p in pages:
        recs = to_records(p)
        rows.append({"source": p.source_id, "category": p.category, "region": p.region, "status": p.status,
                     "chars": len(p.markdown), "records": len(recs), "error": p.error})
        out = DATA_DIR / "collected" / f"{p.source_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"page": p.to_dict(), "records": [r.to_dict() for r in recs]}, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "collection_summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    for r in rows:
        print(f"{r['source']:<16} {r['category']:<24} {r['region']:<6} {r['status']:<5} {r['chars']:>6} chars {r['records']:>3} records")


def cmd_history(a):
    m = MementoStore(Settings().memento_db)
    for r in m.runs():
        print(f"run {r['run_id']:>3} {r['mode']:<16} new={r['new']} changed={r['changed']} removed={r['removed']} unchanged={r['unchanged']}")
    print()
    for p in m.all_policies()[: a.limit]:
        print(f"[{p['status']:<7}] v{p['version_count']} {p['authority']:<6} {p['title'][:80]}")


def cmd_evaluate(a):
    from healthpolicy.evaluate import run_evaluation

    report = run_evaluation(llm_provider=a.llm)
    print(json.dumps(report["metrics"], indent=2))


def cmd_reset(a):
    m = MementoStore(Settings().memento_db)
    m.reset()
    print("Memento history cleared.")


def main(argv=None):
    p = argparse.ArgumentParser(description="HealthPolicy AI - healthcare policy tracker")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("track")
    t.add_argument("--offline", metavar="CYCLE", help="use data/fixtures/<CYCLE> instead of Firecrawl")
    t.add_argument("--sources", nargs="*", help="limit to these source ids")
    t.add_argument("--llm", choices=["gemini", "openai", "groq", "offline"])
    t.add_argument("--baseline-only", action="store_true", help="store history without generating briefs")
    t.add_argument("--label")
    t.set_defaults(f=cmd_track)
    c = sub.add_parser("collect")
    c.add_argument("--offline", metavar="CYCLE")
    c.set_defaults(f=cmd_collect)
    h = sub.add_parser("history")
    h.add_argument("--limit", type=int, default=50)
    h.set_defaults(f=cmd_history)
    e = sub.add_parser("evaluate")
    e.add_argument("--llm", choices=["gemini", "openai", "groq", "offline"], default=None)
    e.set_defaults(f=cmd_evaluate)
    sub.add_parser("reset").set_defaults(f=cmd_reset)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    sys.exit(main())
