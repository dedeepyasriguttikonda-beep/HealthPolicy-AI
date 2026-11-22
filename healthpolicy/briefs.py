"""Policy Update Brief: design, LLM generation, validation and rendering."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .change_detector import Change, sentences
from .llm import LLMClient
from . import relevance

BRIEF_FIELDS = {
    "policy_name": str, "issuing_authority": str, "source_name": str, "source_url": str, "region": str,
    "category": str, "change_type": str, "published_or_effective_date": str, "summary": str,
    "what_changed": list, "key_points": list, "affected_stakeholders": list, "operational_relevance": dict,
    "recommended_actions": list, "deadlines": list, "source_evidence": list, "confidence": (int, float),
    "caveats": str,
}

SYSTEM_PROMPT = """You are HealthPolicy AI, an analyst who writes policy update briefs for healthcare
organizations (hospitals, clinics, insurers, labs). Rules:
1. Use ONLY the source text provided. Never invent numbers, dates, programs or requirements.
2. If something is not stated in the source, write "Not stated in source".
3. "source_evidence" must contain short sentences copied exactly from the source text.
4. Operational relevance must explain the practical impact on healthcare operations
   (billing, compliance, clinical, IT/data, supply chain, workforce, finance) and rate it high / medium / low.
5. This is informational, not legal advice. Be concise and factual.
Return ONE JSON object only, matching the requested schema."""

SCHEMA_HINT = {
    "policy_name": "string", "issuing_authority": "string", "source_name": "string", "source_url": "string",
    "region": "string", "category": "string", "change_type": "new | changed | removed",
    "published_or_effective_date": "YYYY-MM-DD or 'Not stated in source'",
    "summary": "2-3 sentence plain-language summary",
    "what_changed": ["bullet: the specific change compared with the previous version (for new items: what is introduced)"],
    "key_points": ["3-5 bullets"],
    "affected_stakeholders": ["e.g. Hospitals", "Insurers / Payers"],
    "operational_relevance": {"level": "high|medium|low", "areas": ["e.g. Billing & Reimbursement"],
                              "explanation": "2-3 sentences on practical operational impact"},
    "recommended_actions": ["2-4 concrete next steps for a healthcare organization"],
    "deadlines": ["deadlines / time limits stated in source, else empty list"],
    "source_evidence": ["exact sentences from the source supporting the brief"],
    "confidence": "0.0-1.0", "caveats": "limitations, e.g. draft status, missing details",
}


def build_prompt(ch: Change, history_context: str = "") -> str:
    rec = ch.record
    meta = rec.to_dict() if rec else ch.previous
    hints = relevance.analyze(ch.title, rec.text if rec else ch.previous["current_text"], ch.change_type)
    parts = [
        f"CHANGE TYPE: {ch.change_type.upper()}",
        f"POLICY TITLE: {ch.title}",
        f"ISSUING AUTHORITY: {meta['authority']}  |  SOURCE: {meta['source_name']}  |  URL: {meta.get('link') or meta['url']}",
        f"REGION: {meta['region']}  |  CATEGORY: {meta['category']}  |  PUBLISHED: {meta.get('published') or 'unknown'}",
    ]
    if ch.change_type == "changed":
        parts += ["\nPREVIOUS VERSION (from Memento history):", ch.previous["current_text"],
                  "\nCURRENT VERSION (just collected):", rec.text,
                  "\nDETECTED DIFFERENCES:",
                  "Added sentences: " + json.dumps(ch.added, ensure_ascii=False),
                  "Removed sentences: " + json.dumps(ch.removed, ensure_ascii=False),
                  "Changed figures (old -> new): " + json.dumps(ch.numbers_changed, ensure_ascii=False)]
    elif ch.change_type == "removed":
        parts += ["\nThis item was previously listed but is NO LONGER on the source page. Last known text:",
                  ch.previous["current_text"]]
    else:
        parts += ["\nSOURCE TEXT:", rec.text]
    if history_context:
        parts += ["\nRELATED HISTORY FROM MEMENTO (context only, do not treat as the source):", history_context[:1500]]
    parts += ["\nRULE-BASED SIGNALS (hints, verify against text): " + json.dumps(hints),
              "\nReturn JSON with exactly these keys:", json.dumps(SCHEMA_HINT, indent=1)]
    return "\n".join(parts)


def offline_brief(ch: Change) -> dict:
    """Deterministic extractive brief used when no LLM key is configured."""
    rec = ch.record
    meta = rec.to_dict() if rec else ch.previous
    text = rec.text if rec else ch.previous["current_text"]
    text = re.sub(r"^\s*(published|date|posted|issued)\s*[:\-]?\s*\S+\s*", "", text, flags=re.I)
    sents = [s for s in sentences(text) if len(s) > 15]
    sig = relevance.analyze(ch.title, text, ch.change_type)
    if ch.change_type == "changed":
        what = [f"Added: {s}" for s in ch.added] + [f"Removed: {s}" for s in ch.removed]
        what += [f"Figure changed: {o or '-'} -> {n or '-'}" for o, n in ch.numbers_changed]
    elif ch.change_type == "removed":
        what = ["The notice is no longer listed on the source page (withdrawn, archived or moved)."]
    else:
        what = [f"New publication: {sents[0]}" if sents else "New publication."]
    return {
        "policy_name": ch.title, "issuing_authority": meta["authority"], "source_name": meta["source_name"],
        "source_url": meta.get("link") or meta["url"], "region": meta["region"], "category": meta["category"],
        "change_type": ch.change_type,
        "published_or_effective_date": meta.get("published") or "Not stated in source",
        "summary": " ".join(sents[:2]) or ch.title,
        "what_changed": what[:6], "key_points": sents[:4],
        "affected_stakeholders": sig["stakeholders"],
        "operational_relevance": {"level": sig["level"], "areas": sig["areas"],
                                  "explanation": f"Rule-based assessment: affects {', '.join(sig['areas'])}."},
        "recommended_actions": [f"Route to the {sig['areas'][0]} team for review.",
                                "Verify details on the official source before acting."],
        "deadlines": sig["deadlines"], "source_evidence": sents[:2], "confidence": 0.5,
        "caveats": "Generated by the offline extractive fallback (no LLM). Run with an LLM provider for full briefs.",
    }


def validate(brief: dict, source_text: str) -> dict:
    """Fill missing keys, coerce types, and measure grounding of evidence + figures."""
    issues = []
    for k, t in BRIEF_FIELDS.items():
        if k not in brief:
            issues.append(f"missing:{k}")
            brief[k] = [] if t is list else {} if t is dict else 0.0 if t == (int, float) else "Not stated in source"
        elif t is list and isinstance(brief[k], str):
            brief[k] = [brief[k]]
    try:
        brief["confidence"] = float(brief["confidence"])
    except (TypeError, ValueError):
        brief["confidence"] = 0.0
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[^\w%.]", " ", str(s).lower())).strip()
    src = norm(source_text)
    ev = brief.get("source_evidence") or []
    grounded = [e for e in ev if norm(e) and norm(e) in src]
    # every number the brief states should appear in the source text
    nums = set(re.findall(r"\d+(?:\.\d+)?%?", json.dumps({k: brief[k] for k in ("summary", "what_changed", "key_points", "deadlines")})))
    src_nums = set(re.findall(r"\d+(?:\.\d+)?%?", source_text))
    unsupported = sorted(n for n in nums if n not in src_nums)
    brief["_quality"] = {
        "schema_issues": issues,
        "evidence_grounding": round(len(grounded) / len(ev), 2) if ev else 0.0,
        "unsupported_numbers": unsupported,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return brief


def generate_brief(ch: Change, llm: LLMClient, history_context: str = "") -> dict:
    src_text = " ".join(filter(None, [ch.previous["current_text"] if ch.previous else "",
                                      ch.record.text if ch.record else "", ch.title]))
    if llm.is_offline:
        brief = offline_brief(ch)
    else:
        try:
            brief = llm.complete_json(SYSTEM_PROMPT, build_prompt(ch, history_context))
            brief["change_type"] = ch.change_type  # authoritative from detector
        except Exception as e:  # keep the pipeline running; record why
            brief = offline_brief(ch)
            brief["caveats"] = f"LLM unavailable ({e}); extractive fallback used."
    return validate(brief, src_text)


def render_markdown(brief: dict) -> str:
    rel = brief.get("operational_relevance", {})
    badge = {"high": "🔴 HIGH", "medium": "🟠 MEDIUM", "low": "🟢 LOW"}.get(str(rel.get("level", "")).lower(), "—")
    bl = lambda xs: "\n".join(f"- {x}" for x in xs) if xs else "- Not stated in source"
    return f"""## {brief['policy_name']}
**Change:** {brief['change_type'].upper()} · **Authority:** {brief['issuing_authority']} · **Region:** {brief['region']} · **Category:** {brief['category']}
**Date:** {brief['published_or_effective_date']} · **Operational relevance:** {badge} ({', '.join(rel.get('areas', []))})
**Source:** {brief['source_name']} — {brief['source_url']}

**Summary.** {brief['summary']}

**What changed**
{bl(brief['what_changed'])}

**Key points**
{bl(brief['key_points'])}

**Why it matters operationally.** {rel.get('explanation', '')}

**Affected stakeholders:** {', '.join(brief['affected_stakeholders'])}

**Recommended actions**
{bl(brief['recommended_actions'])}

**Deadlines:** {', '.join(brief['deadlines']) or 'None stated'}

**Evidence from source**
{bl(['"' + e + '"' for e in brief['source_evidence']])}

*Confidence: {brief['confidence']:.2f} · {brief['caveats']}*
"""
