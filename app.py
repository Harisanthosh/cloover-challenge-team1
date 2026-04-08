from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import streamlit as st
from dotenv import load_dotenv

from core import DataEnricher, KBManager, SalesCoach


APP_TITLE = "SolarSage Coach – AI Sales Co-Pilot for Cloover Installers"


load_dotenv()
st.set_page_config(page_title=APP_TITLE, page_icon="☀️", layout="wide")


@st.cache_resource
def get_services():
    return {
        "enricher": DataEnricher(),
        "kb": KBManager(),
        "coach": SalesCoach(),
    }


services = get_services()
enricher: DataEnricher = services["enricher"]
kb: KBManager = services["kb"]
coach: SalesCoach = services["coach"]


if "enrichment_result" not in st.session_state:
    st.session_state["enrichment_result"] = None
if "briefing" not in st.session_state:
    st.session_state["briefing"] = ""
if "selected_session" not in st.session_state:
    st.session_state["selected_session"] = None


def quality_badge(score: float) -> str:
    if score >= 90:
        return "🟢 Excellent"
    if score >= 75:
        return "🟡 Good"
    return "🔴 Needs attention"


def parse_blocks(raw: str) -> Dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {"raw_input": raw}


def render_quality(report: Dict[str, Any]) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Overall", f"{report.get('overall_score', 0):.1f}", quality_badge(report.get("overall_score", 0)))
    c2.metric("Completeness", f"{report.get('completeness_score', 0):.1f}")
    c3.metric("Freshness", f"{report.get('freshness_score', 0):.1f}")
    c4.metric("Sanity", f"{report.get('sanity_score', 0):.1f}")
    c5.metric("Consistency", f"{report.get('consistency_score', 0):.1f}")


st.title(APP_TITLE)
st.caption("Gather → Validate Quality → Enrich → Save to KB → Then use LLM")

with st.sidebar:
    st.header("Inputs")
    postal_code = st.text_input("Postal code", placeholder="e.g. 10115")
    product_interest = st.selectbox("Product interest", ["solar", "heat-pump", "wallbox"], index=0)
    cloover_blocks_raw = st.text_area("Optional Cloover blocks JSON", height=180, placeholder='{"customer": {...}}')
    st.markdown("---")
    st.subheader("History")
    history = kb.load_history(limit=10)
    if history:
        for item in history:
            label = f"{kb.render_quality_badge(item.get('quality_score', 0))} {item['session_id']} — {item.get('quality_score', 0):.1f}"
            if st.button(label, key=f"history_{item['session_id']}"):
                st.session_state["selected_session"] = item["session_id"]
    else:
        st.info("No saved KB sessions yet.")


tab_input, tab_validate, tab_kb, tab_output = st.tabs(["Input", "Validate & Enrich", "KB", "Output"])

with tab_input:
    st.subheader("Input capture")
    st.write("Start with postal code and product. Cloover blocks are optional and are validated before use.")
    st.json({"postal_code": postal_code or "", "product_interest": product_interest, "has_cloover_blocks": bool(cloover_blocks_raw.strip())})

    if st.button("Fetch Cloover Blocks"):
        api_key = os.getenv("CLOOVER_API_KEY")
        if not api_key:
            st.warning("CLOOVER_API_KEY is not set. Using placeholder/mock fetch only.")
        st.success("Cloover block fetch is documented as a placeholder in this build.")

with tab_validate:
    st.subheader("Validate & Enrich Data")
    if st.button("Validate & Enrich Data", type="primary"):
        if not postal_code.strip():
            st.error("Postal code is required.")
        else:
            blocks = parse_blocks(cloover_blocks_raw)
            with st.spinner("Running quality checks and enrichment..."):
                result = enricher.validate_and_enrich(postal_code, product_interest, blocks)
                st.session_state["enrichment_result"] = result.model_dump()
            st.success(f"Enriched & Quality-Checked – score {result.quality_report.overall_score}/100")

    result_data = st.session_state.get("enrichment_result")
    if result_data:
        render_quality(result_data["quality_report"])
        cols = st.columns(2)
        with cols[0]:
            st.subheader("Enriched JSON")
            st.json(result_data["enriched_data"])
        with cols[1]:
            st.subheader("Quality Report")
            st.json(result_data["quality_report"])
            if result_data["quality_report"].get("warnings"):
                st.warning("\n".join(result_data["quality_report"]["warnings"]))

with tab_kb:
    st.subheader("Knowledge Base")
    latest = kb.load_latest()
    st.markdown("### Regulations Knowledge")
    st.code(latest["regulations"][:4000])

    if st.button("Update & Quality-Check Knowledge Base", type="primary"):
        result_data = st.session_state.get("enrichment_result")
        if not result_data:
            st.error("Run validation and enrichment first.")
        else:
            from core.data_enricher import EnrichmentResult, QualityReport

            result = EnrichmentResult(
                postal_code=result_data["postal_code"],
                product_interest=result_data["product_interest"],
                source_data=result_data["source_data"],
                enriched_data=result_data["enriched_data"],
                quality_report=QualityReport(**result_data["quality_report"]),
                fetched_at=result_data["fetched_at"],
                cached=result_data.get("cached", False),
            )
            record = kb.save_enrichment(result, extra_notes="Saved from Streamlit KB update flow.")
            st.success(f"Saved {record.session_id} with quality score {record.quality_score}/100")

    if st.session_state.get("selected_session"):
        sid = st.session_state["selected_session"]
        try:
            st.markdown(f"### Selected session: {sid}")
            st.code(kb.read_session_markdown(sid))
        except Exception as exc:
            st.error(str(exc))

    st.markdown("### Download all KB as ZIP")
    zip_bytes = kb.create_zip_bundle()
    st.download_button("Download all KB as ZIP", data=zip_bytes, file_name="solar_sage_kb.zip", mime="application/zip")

with tab_output:
    st.subheader("Generate Sales Coach Briefing")
    if st.button("Generate Sales Coach Briefing", type="primary"):
        result_data = st.session_state.get("enrichment_result")
        if not result_data:
            st.error("Run Validate & Enrich first.")
        else:
            from core.data_enricher import EnrichmentResult, QualityReport

            result = EnrichmentResult(
                postal_code=result_data["postal_code"],
                product_interest=result_data["product_interest"],
                source_data=result_data["source_data"],
                enriched_data=result_data["enriched_data"],
                quality_report=QualityReport(**result_data["quality_report"]),
                fetched_at=result_data["fetched_at"],
                cached=result_data.get("cached", False),
            )
            record = kb.save_enrichment(result, extra_notes="Auto-saved during briefing generation.")
            kb_payload = result.model_dump()
            kb_payload["quality_report"] = result.quality_report.model_dump()
            kb_payload["regulations"] = latest["regulations"]
            briefing = coach.generate_briefing(kb_payload, postal_code, product_interest)
            st.session_state["briefing"] = briefing
            st.success(f"Generated briefing from quality-checked KB: {record.session_id}")

    if st.session_state.get("briefing"):
        st.markdown(st.session_state["briefing"])

st.markdown("---")
st.caption("Voice-note placeholder: add TTS or recording integration later.")

