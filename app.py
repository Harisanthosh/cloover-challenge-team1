from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import streamlit as st
from dotenv import load_dotenv

from core import DataEnricher, KBManager, SalesCoach
from core.data_enricher import EnrichmentResult, QualityReport
from core.voice_handler import VoiceHandler


APP_TITLE = "SolarSage Coach – Voice Training for Cloover Installers"
MISSION_TEXT = (
    "Powering Europe's energy transition. We help solar, heat pump, and wallbox installers sell, finance, and manage clean energy projects — and we help homeowners make the switch to renewables."
)
PILLAR_TEMPLATE = {
    "Pillar 0 — Market & regulatory context": {
        "summary": "Energy prices, subsidies KfW/BAFA, regulations GEG/EEG/GMG, why now, nearby MaStR installs.",
    },
    "Pillar 1 — The compelling offer": {
        "summary": "2–3 personalised packages: Starter / Recommended / Full Ambition with what to buy, why it fits, savings, payback.",
    },
    "Pillar 2 — The financing strategy": {
        "summary": "Cash / partial / 100% Cloover-financed, monthly costs after subsidies, side-by-side table.",
    },
}


load_dotenv()
st.set_page_config(page_title=APP_TITLE, page_icon="☀️", layout="wide")


@st.cache_resource
def get_services():
    return {
        "enricher": DataEnricher(),
        "kb": KBManager(),
        "coach": SalesCoach(),
        "voice": VoiceHandler(),
    }


services = get_services()
enricher: DataEnricher = services["enricher"]
kb: KBManager = services["kb"]
coach: SalesCoach = services["coach"]
voice: VoiceHandler = services["voice"]


if "enrichment_result" not in st.session_state:
    st.session_state["enrichment_result"] = None
if "briefing" not in st.session_state:
    st.session_state["briefing"] = ""
if "selected_session" not in st.session_state:
    st.session_state["selected_session"] = None
if "voice_session" not in st.session_state:
    st.session_state["voice_session"] = None
if "voice_reply" not in st.session_state:
    st.session_state["voice_reply"] = ""
if "voice_transcript_text" not in st.session_state:
    st.session_state["voice_transcript_text"] = ""
if "voice_audio_path" not in st.session_state:
    st.session_state["voice_audio_path"] = None
if "roleplay_input" not in st.session_state:
    st.session_state["roleplay_input"] = ""


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


def current_result_object() -> EnrichmentResult | None:
    result_data = st.session_state.get("enrichment_result")
    if not result_data:
        return None
    return EnrichmentResult(
        postal_code=result_data["postal_code"],
        product_interest=result_data["product_interest"],
        source_data=result_data["source_data"],
        enriched_data=result_data["enriched_data"],
        quality_report=QualityReport(**result_data["quality_report"]),
        fetched_at=result_data["fetched_at"],
        cached=result_data.get("cached", False),
    )


def kb_payload_from_result(result: EnrichmentResult) -> Dict[str, Any]:
    payload = result.model_dump()
    payload["quality_report"] = result.quality_report.model_dump()
    payload["mission"] = MISSION_TEXT
    payload["regulations"] = kb.load_latest()["regulations"]
    payload["pillars"] = PILLAR_TEMPLATE
    payload["kb_json"] = result.enriched_data
    return payload


def save_voice_session_md(session, quality_score: float) -> str:
    kb.base_dir.mkdir(parents=True, exist_ok=True)
    session_id = f"voice_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    path = kb.base_dir / f"{session_id}.md"
    path.write_text(voice.transcript_markdown(session) + f"\n\n- Quality score: {quality_score}\n", encoding="utf-8")
    return str(path)


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


tab_input, tab_validate, tab_kb, tab_voice, tab_output = st.tabs(
    ["Input", "Validate & Enrich", "KB", "Voice Coach Roleplay", "Output"]
)

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
        result = current_result_object()
        if not result:
            st.error("Run validation and enrichment first.")
        else:
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

with tab_voice:
    st.subheader("Voice Coach Roleplay")
    result = current_result_object()
    if not result:
        st.info("Run Validate & Enrich first so voice coaching can stay grounded.")
    else:
        if st.button("Start Training Session", type="primary") or st.session_state.get("voice_session") is None:
            st.session_state["voice_session"] = voice.create_session(
                postal_code=result.postal_code,
                product_interest=result.product_interest,
                quality_score=result.quality_report.overall_score,
                mission_text=MISSION_TEXT,
                pillar_summary=PILLAR_TEMPLATE,
            )
            st.session_state["voice_transcript_text"] = ""
            st.session_state["voice_reply"] = ""
            st.session_state["voice_audio_path"] = None
            st.success("Training session started.")

        v_session = st.session_state["voice_session"]
        st.markdown("### Live transcript")
        transcript_box = st.container(border=True)
        with transcript_box:
            st.write(voice.render_transcript(v_session.transcript) or "No turns yet.")

        st.markdown("### Ask the coach")
        user_turn = st.text_area(
            "Speak naturally here for the demo; this is the push-to-talk fallback.",
            key="roleplay_input",
            height=120,
            placeholder="For example: I’d lead with savings, but I’m not sure how to handle financing objections.",
        )

        cols = st.columns([1, 1, 1])
        with cols[0]:
            send_clicked = st.button("Send to Coach")
        with cols[1]:
            stop_clicked = st.button("Stop Session")
        with cols[2]:
            tts_clicked = st.button("Play Coach Voice")

        if send_clicked:
            if not user_turn.strip():
                st.warning("Enter a line for the installer first.")
            else:
                payload = kb_payload_from_result(result)
                reply = coach.generate_roleplay_reply(payload, user_turn)
                voice.add_user_turn(v_session, user_turn)
                voice.add_coach_turn(v_session, reply)
                st.session_state["voice_reply"] = reply
                st.session_state["voice_transcript_text"] = voice.render_transcript(v_session.transcript)
                voice_path = None
                try:
                    voice_path = voice.synthesize_tts(reply)
                except Exception as exc:
                    st.warning(f"TTS fallback unavailable: {exc}")
                st.session_state["voice_audio_path"] = voice_path
                st.success("Coach reply generated.")

        if stop_clicked and v_session:
            v_session.status = "stopped"
            st.success("Training session stopped.")
            try:
                save_path = save_voice_session_md(v_session, result.quality_report.overall_score)
                st.info(f"Voice transcript saved: {save_path}")
            except Exception as exc:
                st.warning(str(exc))

        st.markdown("### Coach says")
        if st.session_state.get("voice_reply"):
            st.markdown(st.session_state["voice_reply"])
        else:
            st.caption("Waiting for the first turn.")

        st.markdown("### Three-pillar summary")
        pillar_cols = st.columns(3)
        for idx, (pillar_name, pillar_value) in enumerate(PILLAR_TEMPLATE.items()):
            with pillar_cols[idx]:
                st.markdown(f"**{pillar_name}**")
                st.write(pillar_value["summary"])

        if st.session_state.get("voice_audio_path"):
            st.audio(st.session_state["voice_audio_path"])

        if v_session and v_session.transcript:
            transcript_md = voice.transcript_markdown(v_session)
            st.download_button(
                "Download session transcript as markdown",
                data=transcript_md,
                file_name=f"{v_session.session_id}.md",
                mime="text/markdown",
            )

with tab_output:
    st.subheader("Generate Sales Coach Briefing")
    if st.button("Generate Sales Coach Briefing", type="primary"):
        result = current_result_object()
        if not result:
            st.error("Run Validate & Enrich first.")
        else:
            record = kb.save_enrichment(result, extra_notes="Auto-saved during briefing generation.")
            kb_payload = kb_payload_from_result(result)
            briefing = coach.generate_briefing(kb_payload, postal_code, product_interest)
            st.session_state["briefing"] = briefing
            st.success(f"Generated briefing from quality-checked KB: {record.session_id}")

    if st.session_state.get("briefing"):
        st.markdown(st.session_state["briefing"])

st.markdown("---")
st.caption("Voice-waveform animation placeholder: wire in ElevenLabs realtime WebSocket when demo hardware is ready.")

