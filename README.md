# 🩺 HealthPolicy AI — Healthcare Policy Tracker

A Generative-AI application that monitors public healthcare policy sources, detects **new, changed and removed**
policies, remembers what has already been reviewed, and writes **structured policy update briefs** that explain
what changed and why it matters operationally for healthcare organizations.

**Stack:** Firecrawl (collection) · Memento (persistent policy history) · LLM (Gemini / OpenAI / Groq) · Streamlit · Python 3.10+

```
 config/sources.yaml          ┌────────────┐   ┌──────────────┐   ┌───────────────────┐
 (8 official sources) ──────▶ │ Firecrawl  │──▶│ Preprocess   │──▶│ Change detection  │◀──┐
                              │ collector  │   │ clean+split  │   │ new/changed/      │   │
                              └────────────┘   │ into records │   │ removed/unchanged │   │ history
                                               └──────────────┘   └────────┬──────────┘   │
                                                                           ▼              │
                         outputs/digest_*.md   ┌──────────────┐   ┌───────────────────┐   │
                         Streamlit dashboard ◀─│ Validation & │◀──│ LLM update brief  │   │
                                               │ grounding    │   │ generator         │   │
                                               └──────┬───────┘   └───────────────────┘   │
                                                      ▼                                   │
                                               ┌──────────────────────────────────────────┴┐
                                               │ Memento store (SQLite): runs, policies,    │
                                               │ versions, briefs, reviews                  │
                                               └────────────────────────────────────────────┘
```

## Team
| Member | Role / WBS tasks |
|---|---|
| Dedeepya Sri (Leader) | M1 — environment setup, policy sources, Firecrawl pipeline; 2.1 data comparison |
| Tanav Sunkari | M2 — brief design, LLM integration, end-to-end workflow, interface |
| Sharuf Shaik | M3 — evaluation, operational-relevance analysis, final documentation |
| Sumanvitha Mandala | M4 — monitoring pipeline, update briefs, operational relevance |

## Quick start
```bash
python -m venv .venv && .venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                                  # then add FIRECRAWL_API_KEY and GEMINI_API_KEY

# 1. Offline demo (no keys needed) — shows the full workflow on saved snapshots
set LLM_PROVIDER=offline
python run.py reset
python run.py track --offline cycle1 --baseline-only    # first crawl -> builds Memento history
python run.py track --offline cycle2                    # later crawl -> 5 new, 3 changed, 1 removed

# 2. Live tracking with Firecrawl + LLM
python run.py collect                                   # Deliverable 1: collect + preprocess, save records
python run.py track                                     # full cycle; run again later to see only changes

# 3. Dashboard, evaluation, tests
streamlit run app.py
python run.py evaluate --llm gemini                     # or --llm offline
pytest -q
```

## Project layout
| Path | Purpose |
|---|---|
| `config/sources.yaml` | Monitored public sources (CMS, FDA, HHS, MoHFW, NHA/PM-JAY, CDSCO, IRDAI, WHO) with category & region |
| `healthpolicy/collector.py` | Firecrawl collection (`scrape`, markdown, main-content only, retries) + offline snapshot collector |
| `healthpolicy/preprocess.py` | Cleans boilerplate, splits pages into policy records, extracts dates/links, hashes content |
| `healthpolicy/memento_store.py` | **Memento** persistent history: runs, policies, versions, briefs, reviews (+ optional `memento-memory` graph mirror) |
| `healthpolicy/change_detector.py` | New / changed / cosmetic / removed classification, sentence diff, changed-figure diff |
| `healthpolicy/relevance.py` | Rule-based operational areas, stakeholders, urgency, deadlines |
| `healthpolicy/llm.py` | Provider-agnostic LLM client with JSON output |
| `healthpolicy/briefs.py` | Brief schema, grounded prompt, validation (evidence grounding, unsupported numbers), Markdown rendering |
| `healthpolicy/pipeline.py` | End-to-end tracking cycle and digest output |
| `healthpolicy/evaluate.py` | Evaluation suite (retrieval, detection P/R/F1, Memento, brief quality) |
| `app.py` | Streamlit dashboard |
| `data/fixtures/` | **Synthetic** demo snapshots + ground truth for repeatable testing (not real announcements) |
| `docs/` | Deliverable reports 1–4 |
| `outputs/` | Generated digests, briefs (JSON) and evaluation results |

## Deliverables
1. [Healthcare Policy Information Collection Report](docs/01_collection_report.md)
2. [Healthcare Policy Update Brief Generator](docs/02_update_brief_generator.md)
3. [HealthPolicy AI Policy Tracking System](docs/03_policy_tracking_system.md)
4. [Final HealthPolicy AI Project Report](docs/04_final_report.md)

> Disclaimer: briefs are informational summaries of public sources, not legal or regulatory advice. Always verify on the official source.
