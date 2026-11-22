"""Rule-based operational-relevance signals.

Used (1) as hints in the LLM prompt, (2) to build briefs in offline mode, and
(3) as an independent check on the LLM's relevance rating during evaluation.
"""
from __future__ import annotations

import re

AREAS = {
    "Billing & Reimbursement": ["reimburse", "payment", "fee schedule", "package rate", "conversion factor", "claim",
                                "billing", "codes", "tariff", "cashless", "pre-authori", "settle"],
    "Regulatory Compliance": ["must", "mandatory", "required", "penalt", "enforcement", "licen", "comply", "compliance",
                              "rule", "notification", "registration", "register"],
    "Clinical Operations": ["clinical", "patient", "beds", "treatment", "antibiotic", "stewardship", "isolation",
                            "infection", "heat-stroke", "prescri", "diagnos", "surveillance"],
    "IT, Data & Privacy": ["hipaa", "epHI", "encryption", "authentication", "information blocking", "abha", "registry",
                           "portal", "software", "records", "data", "telehealth", "telemedicine", "interoperab"],
    "Pharmacy & Supply Chain": ["drug", "shortage", "recall", "batch", "quarantine", "supplier", "device", "ppe",
                                "stockpile", "manufactur", "ors stock"],
    "Workforce & Staffing": ["staffing", "nurse", "workforce", "recruit", "training", "personnel"],
    "Finance & Grants": ["grant", "funding", "$", "₹", "crore", "budget", "shareholder"],
}

STAKEHOLDERS = {
    "Hospitals": ["hospital", "facilit", "empanelled", "provider"],
    "Insurers / Payers": ["insurer", "payer", "medicare advantage", "cashless", "claim"],
    "Laboratories": ["laborator", "ldt", "lab "],
    "Manufacturers & Importers": ["manufactur", "importer", "vendor"],
    "Physicians & Clinicians": ["physician", "clinician", "doctor", "prescri", "telemedicine", "telehealth"],
    "Pharmacies": ["pharmac", "drug shortage", "injectable"],
    "Patients": ["patient", "beneficiar"],
}

HIGH_URGENCY = ["final rule", "mandatory", "must", "penalt", "effective", "within", "deadline", "recall", "rejected",
                "enforcement", "24 hours", "immediately"]
LOW_URGENCY = ["draft", "proposed", "consultation", "comments", "report", "publishes"]
DEADLINE = re.compile(r"(within \d+ (?:hours?|days?|months?)|in \d+ (?:days?|months?)|after \d+ days|"
                      r"from (?:the )?(?:\d{1,2} \w+|\w+ \d{1,2}|effective date)|effective [\w ]{3,20}|"
                      r"\d+[- ]day[\w ]{0,30}period|by \w+ \d{1,2},? \d{4}|beginning in \d+ months)", re.I)


def _hits(text: str, table: dict[str, list[str]]) -> list[str]:
    t = text.lower()
    scored = [(k, sum(t.count(w.lower()) for w in words)) for k, words in table.items()]
    return [k for k, s in sorted(scored, key=lambda x: -x[1]) if s > 0]


def analyze(title: str, text: str, change_type: str = "new") -> dict:
    full = f"{title}. {text}"
    low = full.lower()
    areas = _hits(full, AREAS)[:3]
    stakeholders = _hits(full, STAKEHOLDERS)[:4] or ["Healthcare organizations"]
    hi = sum(w in low for w in HIGH_URGENCY)
    lo = sum(w in low for w in LOW_URGENCY)
    score = hi - lo + (1 if change_type == "changed" else 0)
    level = "high" if score >= 2 else "medium" if score >= 0 else "low"
    deadlines = list(dict.fromkeys(m.group(0).strip() for m in DEADLINE.finditer(full)))[:4]
    return {"level": level, "areas": areas or ["General Awareness"], "stakeholders": stakeholders,
            "deadlines": deadlines, "urgency_score": score}
