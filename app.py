"""HealthPolicy AI - Streamlit policy tracking dashboard.   Run:  streamlit run app.py"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from healthpolicy.briefs import render_markdown
from healthpolicy.config import OUTPUT_DIR, Settings, load_sources
from healthpolicy.memento_store import MementoStore
from healthpolicy.pipeline import run_cycle

st.set_page_config(page_title="HealthPolicy AI", page_icon="🩺", layout="wide")
settings = Settings()

# ---------------- sidebar ----------------
st.sidebar.title("🩺 HealthPolicy AI")
st.sidebar.caption("Healthcare Policy Tracker · Firecrawl + Memento + LLM")
mode = st.sidebar.radio("Collection mode", ["Live (Firecrawl)", "Offline demo snapshots"],
                        index=0 if settings.firecrawl_api_key else 1)
cycle = None
if mode.startswith("Offline"):
    cycle = st.sidebar.selectbox("Snapshot", ["cycle1", "cycle2"],
                                 help="cycle1 = first crawl (baseline), cycle2 = later crawl with changes")
providers = ["gemini", "openai", "groq", "offline"]
settings.llm_provider = st.sidebar.selectbox("LLM provider", providers,
                                             index=providers.index(settings.llm_provider) if settings.llm_provider in providers else 0)
all_sources = load_sources()
chosen = st.sidebar.multiselect("Sources", [s.id for s in all_sources], default=[s.id for s in all_sources])
baseline = st.sidebar.checkbox("Baseline only (store history, no briefs)", value=False)

if st.sidebar.button("▶ Run tracking cycle", type="primary", width="stretch"):
    with st.spinner("Collecting → comparing with Memento → generating briefs..."):
        try:
            rep = run_cycle(settings, cycle, chosen, baseline)
            st.session_state["last_run"] = rep.run_id
            st.sidebar.success(f"Run {rep.run_id}: {rep.counts['new']} new · {rep.counts['changed']} changed · "
                               f"{rep.counts['removed']} removed · {len(rep.briefs)} briefs")
        except Exception as e:
            st.sidebar.error(str(e))

if st.sidebar.button("Reset Memento history", width="stretch"):
    MementoStore(settings.memento_db).reset()
    st.sidebar.warning("History cleared")

memento = MementoStore(settings.memento_db)
tab_briefs, tab_hist, tab_runs, tab_src, tab_eval = st.tabs(
    ["📰 Update briefs", "🗂 Policy history (Memento)", "⏱ Runs", "🌐 Sources", "📊 Evaluation"])

# ---------------- briefs ----------------
with tab_briefs:
    rows = memento.briefs()
    if not rows:
        st.info("No briefs yet. Run a tracking cycle (offline demo: run cycle1, then cycle2).")
    else:
        df = pd.DataFrame([{**r["brief"], "run": r["run_id"], "created": r["created_at"]} for r in rows])
        df["relevance"] = df["operational_relevance"].apply(lambda d: str(d.get("level", "")).lower())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Briefs", len(df))
        c2.metric("High relevance", int((df.relevance == "high").sum()))
        c3.metric("New policies", int((df.change_type == "new").sum()))
        c4.metric("Changed policies", int((df.change_type == "changed").sum()))
        f1, f2, f3, f4 = st.columns(4)
        lv = f1.multiselect("Relevance", ["high", "medium", "low"], default=["high", "medium", "low"])
        rg = f2.multiselect("Region", sorted(df.region.unique()), default=sorted(df.region.unique()))
        ct = f3.multiselect("Change type", ["new", "changed", "removed"], default=["new", "changed", "removed"])
        q = f4.text_input("Search")
        view = df[df.relevance.isin(lv) & df.region.isin(rg) & df.change_type.isin(ct)]
        if q:
            view = view[view.apply(lambda r: q.lower() in json.dumps(r.to_dict(), default=str).lower(), axis=1)]
        order = {"high": 0, "medium": 1, "low": 2}
        view = view.sort_values("relevance", key=lambda s: s.map(order))
        for _, b in view.iterrows():
            icon = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(b.relevance, "⚪")
            with st.expander(f"{icon} [{b.change_type.upper()}] {b.policy_name} — {b.issuing_authority}"):
                st.markdown(render_markdown(b.to_dict()))
                qd = b.get("_quality") or {}
                st.caption(f"Grounding: {qd.get('evidence_grounding')} · Unsupported numbers: {qd.get('unsupported_numbers')}")
        digests = sorted(OUTPUT_DIR.glob("digest_run*.md"))
        if digests:
            st.download_button("⬇ Download latest digest (Markdown)", digests[-1].read_text(encoding="utf-8"),
                               file_name=digests[-1].name)

# ---------------- history ----------------
with tab_hist:
    pol = pd.DataFrame(memento.all_policies())
    if pol.empty:
        st.info("Memento history is empty.")
    else:
        st.dataframe(pol[["status", "authority", "region", "category", "title", "published", "version_count",
                          "first_seen", "last_changed"]], width="stretch", hide_index=True)
        pick = st.selectbox("Version history for", pol.title.tolist())
        item = pol[pol.title == pick].iloc[0]
        for i, v in enumerate(memento.history(item.item_id), 1):
            st.markdown(f"**v{i}** · seen {v['seen_at']} (run {v['run_id']}) · hash `{v['content_hash'][:10]}`")
            st.write(v["text"])

# ---------------- runs ----------------
with tab_runs:
    st.dataframe(pd.DataFrame(memento.runs()), width="stretch", hide_index=True)

# ---------------- sources ----------------
with tab_src:
    st.dataframe(pd.DataFrame([s.__dict__ for s in load_sources(only_enabled=False)]),
                 width="stretch", hide_index=True)
    st.caption("Edit config/sources.yaml to add or disable sources.")

# ---------------- evaluation ----------------
with tab_eval:
    files = sorted(Path(OUTPUT_DIR).glob("evaluation_*.json"))
    if not files:
        st.info("Run `python run.py evaluate` to produce evaluation metrics.")
    for f in files:
        st.subheader(f.stem.replace("_", " ").title())
        st.json(json.loads(f.read_text())["metrics"])
