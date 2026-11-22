"""Generate SYNTHETIC offline demo snapshots (cycle1 = first crawl, cycle2 = later crawl).

These files are NOT real announcements. They imitate the *shape* of the markdown that
Firecrawl returns for a newsroom / notices page so the whole pipeline (preprocessing,
Memento history, change detection, LLM briefs, evaluation) can be run and tested
without API keys or internet access. Real runs use live Firecrawl output instead.

Ground truth for evaluation is written to data/fixtures/ground_truth.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "fixtures"
HEADER = "> SYNTHETIC DEMO SNAPSHOT - fictional content for offline testing only.\n\n"

# Each item: (title, date, body)
C1 = {
    "cms_newsroom": ("CMS Newsroom", [
        ("Proposed Physician Fee Schedule Update for Next Calendar Year", "2026-07-10",
         "The proposed rule updates the conversion factor by 2.1% and expands telehealth billing codes for behavioral health. Comments are accepted for 60 days."),
        ("Hospital Price Transparency Enforcement Reminder", "2026-06-28",
         "Hospitals must post machine-readable files of standard charges. Civil monetary penalties apply for non-compliance after a 90-day corrective action period."),
        ("Medicare Advantage Star Ratings Methodology Notice", "2026-06-15",
         "CMS clarifies the cut-point methodology used for Star Ratings. No change to measure weights this cycle."),
    ]),
    "fda_press": ("FDA Press Announcements", [
        ("FDA Issues Draft Guidance on AI-Enabled Medical Device Software", "2026-07-02",
         "The draft guidance describes premarket submission content for AI-enabled device software functions, including a predetermined change control plan."),
        ("FDA Announces Recall Classification for Infusion Pump Model", "2026-06-20",
         "A Class II recall was announced for one infusion pump model due to a software alarm defect. Facilities should apply the vendor patch."),
        ("FDA Updates Drug Shortage List", "2026-06-11",
         "Two sterile injectable products were added to the shortage list. Alternative suppliers are listed on the shortage database."),
    ]),
    "hhs_press": ("HHS Press Room", [
        ("HHS Proposes Update to HIPAA Security Rule", "2026-06-30",
         "The proposal would require multi-factor authentication, annual compliance audits and encryption of ePHI at rest for covered entities."),
        ("HHS Announces Rural Health Workforce Grants", "2026-06-18",
         "Grants of up to $1.5 million are available to rural hospitals for nurse recruitment and retention programs. Applications close in 45 days."),
    ]),
    "mohfw_notices": ("MoHFW - What's New", [
        ("Advisory on Heat-Related Illness Preparedness for Health Facilities", "2026-05-20",
         "States are advised to ensure cooling arrangements, ORS stock and dedicated heat-stroke beds in district hospitals."),
        ("Draft Guidelines for Telemedicine Practice - Public Consultation", "2026-06-25",
         "The draft revises consent, prescription and record-keeping norms for teleconsultations. Comments invited within 30 days."),
        ("Revised Indian Public Health Standards for Sub-District Hospitals", "2026-06-05",
         "The revised IPHS specify minimum staffing, diagnostic services and infection control requirements for sub-district hospitals."),
    ]),
    "nha_pmjay": ("NHA - PM-JAY / ABDM", [
        ("Revision of Health Benefit Package Rates under AB PM-JAY", "2026-06-22",
         "Package rates for 120 procedures in oncology and cardiology are revised. Empanelled hospitals must update pre-authorisation requests from the effective date."),
        ("ABDM Health Facility Registry Mandatory Linking Circular", "2026-06-08",
         "All empanelled hospitals must register in the Health Facility Registry and link records to ABHA IDs within 90 days."),
    ]),
    "cdsco_notices": ("CDSCO - Notices", [
        ("Notice on Licensing of Class B Medical Devices", "2026-06-27",
         "Manufacturers and importers of Class B medical devices must hold a licence under the Medical Devices Rules. Applications via the online portal."),
        ("Alert on Not-of-Standard-Quality Drug Samples", "2026-06-14",
         "The monthly list of not-of-standard-quality samples is published. Hospitals should quarantine listed batches."),
    ]),
    "irdai_circulars": ("IRDAI - Circulars", [
        ("Master Circular on Health Insurance Products", "2026-06-12",
         "Insurers must settle cashless authorisation requests within one hour and final discharge authorisation within three hours."),
        ("Circular on Standard Claim Form for Hospitals", "2026-05-30",
         "A standardised claim form is prescribed for all network hospitals to reduce claim rejection due to missing data."),
    ]),
    "who_news": ("WHO News Releases", [
        ("WHO Releases Updated Guidance on Antimicrobial Stewardship in Hospitals", "2026-06-24",
         "The guidance recommends hospital stewardship committees, prescribing audits and restricted-use lists for reserve antibiotics."),
        ("WHO Publishes Global Report on Patient Safety", "2026-06-03",
         "The report summarises medication-error and healthcare-associated infection indicators across member states."),
    ]),
}

# cycle2 = later crawl. Edits to cycle1 + new items + one removal.
C2 = json.loads(json.dumps(C1))  # deep copy
truth = {"new": [], "changed": [], "removed": [], "unchanged": []}

def items(src):
    return C2[src][1]

# --- CHANGED items (substantive) ---
cms = items("cms_newsroom")
cms[0][1] = "2026-07-24"
cms[0][2] = ("FINAL RULE: The physician fee schedule conversion factor is updated by 2.8% (up from 2.1% proposed). "
             "Telehealth billing codes for behavioral health are made permanent and audio-only visits are covered. Effective 1 January.")
truth["changed"].append(("cms_newsroom", cms[0][0]))

nha = items("nha_pmjay")
nha[0][2] = ("Package rates for 120 procedures in oncology and cardiology are revised; rates for 35 dialysis packages are added. "
             "Empanelled hospitals must update pre-authorisation requests from 1 August, and claims at old rates will be rejected after 30 days.")
truth["changed"].append(("nha_pmjay", nha[0][0]))

irdai = items("irdai_circulars")
irdai[0][2] = ("Insurers must settle cashless authorisation requests within one hour and final discharge authorisation within three hours. "
               "Any delay beyond three hours must be borne by the insurer from shareholder funds; a penalty framework applies from the next quarter.")
truth["changed"].append(("irdai_circulars", irdai[0][0]))

# --- COSMETIC change (should be ignored as not meaningful) ---
who = items("who_news")
who[1][2] = "The report  summarises medication-error and healthcare-associated   infection indicators across member states."

# --- NEW items ---
new_items = {
    "fda_press": ("FDA Finalizes Rule on Laboratory Developed Tests Oversight Phase-In", "2026-07-18",
                  "Laboratories offering LDTs must comply with medical device reporting and complaint-handling requirements in phase one, beginning in 12 months."),
    "hhs_press": ("HHS Finalizes Information Blocking Disincentives for Providers", "2026-07-15",
                  "Providers found to have committed information blocking face disincentives under Medicare programs, including reduced MIPS scores."),
    "mohfw_notices": ("Notification on Mandatory Reporting of Notifiable Diseases by Private Hospitals", "2026-07-12",
                      "Private hospitals and laboratories must report listed notifiable diseases on the IHIP portal within 24 hours of diagnosis."),
    "cdsco_notices": ("Draft Notification on Revised Schedule M Compliance Timeline", "2026-07-08",
                      "Small and medium drug manufacturers get an extended deadline of six months to comply with revised Good Manufacturing Practices."),
    "who_news": ("WHO Issues Interim Recommendations on Avian Influenza Preparedness", "2026-07-20",
                 "Health facilities should strengthen surveillance, isolation capacity and PPE stockpiles for suspected human cases."),
}
for src, it in new_items.items():
    C2[src][1].insert(0, list(it))
    truth["new"].append((src, it[0]))

# --- REMOVED item ---
removed = C2["fda_press"][1].pop()  # drug shortage list item drops off the page
truth["removed"].append(("fda_press", removed[0]))

changed_titles = {t for _, t in truth["changed"]}
new_titles = {t for _, t in truth["new"]}
for src, (_, its) in C2.items():
    for it in its:
        if it[0] not in changed_titles and it[0] not in new_titles:
            truth["unchanged"].append((src, it[0]))


def render(page_title, its):
    out = [f"# {page_title}\n", HEADER, "## Latest Updates\n"]
    for title, date, body in its:
        out.append(f"### {title}\n\n*Published: {date}*\n\n{body}\n\n[Read more](#)\n")
    out.append("\n---\nSite footer | Accessibility | Contact | Privacy policy\n")
    return "\n".join(out)


for cyc, data in (("cycle1", C1), ("cycle2", C2)):
    d = ROOT / cyc
    d.mkdir(parents=True, exist_ok=True)
    for src, (title, its) in data.items():
        (d / f"{src}.md").write_text(render(title, its), encoding="utf-8")

(ROOT / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
print({k: len(v) for k, v in truth.items()})
