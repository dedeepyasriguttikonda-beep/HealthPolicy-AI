import json

import pytest

from healthpolicy import briefs as B
from healthpolicy.change_detector import detect, similarity
from healthpolicy.collector import RawPage
from healthpolicy.config import Settings
from healthpolicy.memento_store import MementoStore
from healthpolicy.pipeline import run_cycle
from healthpolicy.preprocess import extract_date, to_records


def page(md, sid="src"):
    return RawPage(sid, "Src", "https://example.gov", "regulatory", "IN", "AUTH", "Src", md, "2026-01-01", "offline")


LISTING_MD = """
[Skip to main content](#main) | Accessibility | Screen reader
![logo](logo.png)
# What's New
- [Guidelines for operationalisation of Comprehensive Primary Health Care services](https://x.gov.in/a.pdf) 12/06/2026
- [Advisory to States on preparedness for dengue and chikungunya season](https://x.gov.in/b.pdf) 05/06/2026
- [Home](/)
Copyright © 2026 All rights reserved
"""


def test_listing_page_split_into_records():
    recs = to_records(page(LISTING_MD))
    assert [r.title[:10] for r in recs] == ["Guidelines", "Advisory t"]
    assert recs[0].published == "2026-06-12"  # dd/mm/yyyy on .gov.in sites
    assert recs[0].link.endswith("a.pdf")


def test_heading_page_and_dates():
    md = "# News\n## Latest Updates\n### FDA approves a new rule for devices\n\nJuly 3, 2026 - Body text here.\n"
    recs = to_records(page(md))
    assert len(recs) == 1 and recs[0].published == "2026-07-03"
    assert extract_date("Issued 1 August 2026") == "2026-08-01"


def test_ids_stable_hash_sensitive():
    a = to_records(page("### A long enough policy title\n\nRate is 2.1%."))[0]
    b = to_records(page("### A long enough policy title\n\nRate is 2.8%."))[0]
    assert a.item_id == b.item_id and a.content_hash != b.content_hash
    assert similarity(a.text, b.text) < 0.97


def test_detect_new_changed_removed(tmp_path):
    m = MementoStore(tmp_path / "m.db")
    run = m.start_run("test")
    r1 = to_records(page("### Policy one is here\n\nSay 10 days.\n\n### Policy two is here\n\nKeep."))
    for r in r1:
        m.remember(r, run)
    r2 = to_records(page("### Policy one is here\n\nSay 30 days and penalties apply.\n\n### Policy three is new\n\nNew."))
    res = detect({"src": r2}, m)
    assert [c.title for c in res.new] == ["Policy three is new"]
    assert [c.title for c in res.changed] == ["Policy one is here"]
    assert [c.title for c in res.removed] == ["Policy two is here"]
    assert ("10 days", "30 days") in res.changed[0].numbers_changed


class FakeLLM:
    provider, model, is_offline = "fake", "fake-1", False

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user):
        self.prompts.append(user)
        return {"policy_name": "X", "issuing_authority": "AUTH", "source_name": "Src", "source_url": "u",
                "region": "IN", "category": "regulatory", "change_type": "new",
                "published_or_effective_date": "2026-01-01", "summary": "Limit moves to 99 days.",
                "what_changed": ["a"], "key_points": ["b"], "affected_stakeholders": ["Hospitals"],
                "operational_relevance": {"level": "high", "areas": ["Billing"], "explanation": "e"},
                "recommended_actions": ["c"], "deadlines": [], "source_evidence": ["Say 30 days and penalties apply.", "made up"],
                "confidence": "0.8", "caveats": ""}


def test_llm_brief_prompt_and_validation(tmp_path):
    m = MementoStore(tmp_path / "m.db")
    run = m.start_run("t")
    for r in to_records(page("### Policy one is here\n\nSay 10 days.")):
        m.remember(r, run)
    res = detect({"src": to_records(page("### Policy one is here\n\nSay 30 days and penalties apply."))}, m)
    llm = FakeLLM()
    b = B.generate_brief(res.changed[0], llm)
    p = llm.prompts[0]
    assert "PREVIOUS VERSION" in p and "Say 10 days." in p and "CURRENT VERSION" in p
    assert b["change_type"] == "changed"           # detector overrides model
    assert b["confidence"] == 0.8                   # coerced to float
    assert b["_quality"]["evidence_grounding"] == 0.5  # one real quote, one invented
    assert "99" in b["_quality"]["unsupported_numbers"]  # hallucinated number caught
    assert "## X" in B.render_markdown(b)


def test_end_to_end_offline_no_duplicates(tmp_path):
    s = Settings()
    s.memento_db, s.llm_provider, s.memento_backend = tmp_path / "e.db", "offline", "local"
    first = run_cycle(s, "cycle1", baseline_only=True, output_dir=tmp_path)
    second = run_cycle(s, "cycle2", output_dir=tmp_path)
    third = run_cycle(s, "cycle2", output_dir=tmp_path)
    assert first.counts["new"] == 19 and not first.briefs
    assert (second.counts["new"], second.counts["changed"], second.counts["removed"]) == (5, 3, 1)
    assert third.briefs == [] and third.counts["changed"] == 0
    data = json.loads(open(second.output_json).read())
    assert len(data["briefs"]) == 9
