from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from core import DataEnricher, KBManager, SalesCoach
from core.data_enricher import EnrichmentResult, QualityReport
from core.voice_handler import VoiceHandler


APP_TITLE = "Cloover AI Sales Coach – Voice Training for Cloover Installers"
ELEVENLABS_TALK_TO_URL = (
    "https://elevenlabs.io/app/talk-to?agent_id=agent_6201knrhdf18fvvtzxbjk0d57c2b"
    "&branch_id=agtbrch_3901knrhdfwffq5rst0ndg6v3e38"
)
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


load_dotenv(override=True)
st.set_page_config(page_title=APP_TITLE, page_icon="☀️", layout="wide")


def _service_env_fingerprint() -> tuple[str, ...]:
    return (
        os.getenv("ANTHROPIC_API_KEY", ""),
        os.getenv("ANTHROPIC_MODEL", ""),
        os.getenv("GEMINI_API_KEY", ""),
        os.getenv("Z_AI_API_KEY", ""),
        os.getenv("Z_AI_BASE_URL", ""),
        os.getenv("Z_AI_MODEL", ""),
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("ELEVENLABS_API_KEY", ""),
        os.getenv("ELEVENLABS_VOICE_ID", ""),
        os.getenv("ELEVENLABS_MODEL_ID", ""),
    )


@st.cache_resource
def get_services(_env_fingerprint: tuple[str, ...]):
    return {
        "enricher": DataEnricher(),
        "kb": KBManager(),
        "coach": SalesCoach(),
        "voice": VoiceHandler(),
    }


services = get_services(_service_env_fingerprint())
enricher: DataEnricher = services["enricher"]
kb: KBManager = services["kb"]
coach: SalesCoach = services["coach"]
voice: VoiceHandler = services["voice"]


if "enrichment_result" not in st.session_state:
    st.session_state["enrichment_result"] = None
if "enrichment_result_internal" not in st.session_state:
    st.session_state["enrichment_result_internal"] = None
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
if "voice_last_error" not in st.session_state:
    st.session_state["voice_last_error"] = ""
if "coach_response_mode" not in st.session_state:
    st.session_state["coach_response_mode"] = ""
if "voice_last_mic_transcript" not in st.session_state:
    st.session_state["voice_last_mic_transcript"] = ""
if "voice_last_audio_digest" not in st.session_state:
    st.session_state["voice_last_audio_digest"] = ""
if "voice_auto_send_mic" not in st.session_state:
    st.session_state["voice_auto_send_mic"] = True


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
    result_data = st.session_state.get("enrichment_result_internal")
    if not result_data:
        legacy = st.session_state.get("enrichment_result")
        if legacy and isinstance(legacy, dict) and "postal_code" in legacy and "enriched_data" in legacy:
            result_data = legacy
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


def current_result_spec() -> Dict[str, Any] | None:
    result_data = st.session_state.get("enrichment_result")
    if result_data and isinstance(result_data, dict) and "metadata" in result_data and "input_parameters" in result_data:
        return result_data
    result = current_result_object()
    if result is None:
        return None
    return enricher.format_to_io_spec(result)


def latest_coach_reply(session) -> str:
    if st.session_state.get("voice_reply"):
        return st.session_state["voice_reply"]
    if session:
        for item in reversed(session.transcript):
            if item.role == "coach":
                return item.content
    return ""


def render_autoplay_audio(audio_path: str | None) -> None:
    if not audio_path:
        return
    path = Path(audio_path)
    if not path.exists():
        return
    suffix = path.suffix.lower()
    mime_type = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    st.markdown(
        (
            f'<audio autoplay controls style="width: 100%;">'
            f'<source src="data:{mime_type};base64,{encoded}" type="{mime_type}">' 
            "Your browser does not support audio playback."
            "</audio>"
        ),
        unsafe_allow_html=True,
    )


def render_talk_live_embed() -> None:
        st.markdown("### Talk Live to GridCoach")
        st.caption("This GridCoach agent page blocks third-party framing, so it cannot be embedded directly inside Streamlit.")
        st.link_button("Open GridCoach live coach", ELEVENLABS_TALK_TO_URL, use_container_width=True)

        components.html(
                f"""
                <div style=\"border:1px solid rgba(49,51,63,0.2); border-radius:12px; padding:18px; background:#fafafa;\">
                    <div style=\"font-family:system-ui,sans-serif; color:#111827;\">
                        <h3 style=\"margin:0 0 10px 0; font-size:1.05rem;\">ElevenLabs live coach</h3>
                        <p style=\"margin:0 0 12px 0; line-height:1.5;\">
                            GridCoach sends <code>X-Frame-Options: SAMEORIGIN</code> and a <code>frame-ancestors</code>
                            policy that blocks embedding this URL in third-party apps. Use the button below to launch the live
                            talk page in a new tab without browser CORS or frame errors.
                        </p>
                        <a href=\"{ELEVENLABS_TALK_TO_URL}\" target=\"_blank\" rel=\"noopener noreferrer\"
                             style=\"display:inline-block; padding:10px 16px; border-radius:999px; background:#111827; color:white; text-decoration:none; font-weight:600;\">
                            Launch GridCoach Talk-to Agent
                        </a>
                    </div>
                </div>
                """,
                height=220,
        )


def handle_roleplay_turn(v_session, result: EnrichmentResult, user_turn: str) -> None:
    payload = kb_payload_from_result(result)
    reply = coach.generate_roleplay_reply(payload, user_turn)
    voice.add_user_turn(v_session, user_turn)
    voice.add_coach_turn(v_session, reply)
    st.session_state["voice_reply"] = reply
    st.session_state["voice_transcript_text"] = voice.render_transcript(v_session.transcript)
    st.session_state["coach_response_mode"] = getattr(coach, "last_response_mode", "unknown")
    st.session_state["voice_last_error"] = getattr(coach, "last_model_error", "")

    voice_path = None
    try:
        voice_path = voice.synthesize_tts(reply)
    except Exception as exc:
        if st.session_state.get("voice_last_error"):
            st.session_state["voice_last_error"] = f"{st.session_state['voice_last_error']} | TTS: {exc}"
        else:
            st.session_state["voice_last_error"] = f"TTS: {exc}"
        st.warning(f"Coach audio unavailable: {exc}")
    st.session_state["voice_audio_path"] = voice_path


def fallback_voice_opener(result: EnrichmentResult) -> str:
    return (
        "Coach opener:\n"
        f"You're walking into a {result.product_interest} conversation in {result.postal_code}. Open with confidence and lead the homeowner from urgency to fit to financing.\n\n"
        "What to say first:\n"
        "'Thanks for having me over. I want to show you the cleanest path to lower energy costs, use the available incentives properly, and choose a setup that actually fits how you live.'\n\n"
        "What to focus on:\n"
        "1. Pillar 0: Why now in this market and regulatory context.\n"
        "2. Pillar 1: Which package best fits the home and why.\n"
        "3. Pillar 2: How to make the monthly economics feel comfortable.\n\n"
        "First question to ask:\n"
        "'Before I show you options, what matters most to you right now: lower bills, energy independence, or keeping the monthly payment predictable?'"
    )


def start_voice_training_session(result: EnrichmentResult) -> None:
    session = voice.create_session(
        postal_code=result.postal_code,
        product_interest=result.product_interest,
        quality_score=result.quality_report.overall_score,
        mission_text=MISSION_TEXT,
        pillar_summary=PILLAR_TEMPLATE,
    )
    st.session_state["voice_session"] = session
    st.session_state["voice_last_error"] = ""
    st.session_state["voice_last_mic_transcript"] = ""
    st.session_state["voice_last_audio_digest"] = ""
    st.session_state["roleplay_input"] = ""

    try:
        opener = coach.generate_roleplay_opener(kb_payload_from_result(result))
    except Exception as exc:
        opener = fallback_voice_opener(result)
        st.session_state["coach_response_mode"] = "offline"
        st.session_state["voice_last_error"] = str(exc)
    else:
        st.session_state["coach_response_mode"] = getattr(coach, "last_response_mode", "unknown")
        st.session_state["voice_last_error"] = getattr(coach, "last_model_error", "")

    voice.add_coach_turn(session, opener)
    st.session_state["voice_reply"] = opener
    st.session_state["voice_transcript_text"] = voice.render_transcript(session.transcript)

    try:
        st.session_state["voice_audio_path"] = voice.synthesize_tts(opener)
    except Exception as exc:
        st.session_state["voice_audio_path"] = None
        if st.session_state.get("voice_last_error"):
            st.session_state["voice_last_error"] = f"{st.session_state['voice_last_error']} | TTS: {exc}"
        else:
            st.session_state["voice_last_error"] = f"TTS: {exc}"


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


tab_input, tab_validate, tab_kb, tab_voice, tab_talk_live = st.tabs(
    ["Input", "Validate & Enrich", "KB", "Voice Coach Roleplay", "Talk Live to Coach"]
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
                st.session_state["enrichment_result_internal"] = result.model_dump()
                st.session_state["enrichment_result"] = enricher.format_to_io_spec(result)
            st.success(f"Enriched & Quality-Checked – score {result.quality_report.overall_score}/100")

    result_data = current_result_spec()
    internal_data = st.session_state.get("enrichment_result_internal")
    if result_data and internal_data:
        render_quality(internal_data["quality_report"])
        cols = st.columns(2)
        with cols[0]:
            st.subheader("Enriched JSON (spec format)")
            st.json(result_data)
            st.download_button(
                "Download spec JSON",
                data=json.dumps(result_data, indent=2),
                file_name="validated_enriched_output.json",
                mime="application/json",
            )
        with cols[1]:
            st.subheader("Quality Report")
            st.json(internal_data["quality_report"])
            if internal_data["quality_report"].get("warnings"):
                st.warning("\n".join(internal_data["quality_report"]["warnings"]))

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
    st.download_button("Download all KB as ZIP", data=zip_bytes, file_name="cloover_ai_sales_coach_kb.zip", mime="application/zip")

with tab_voice:
    st.subheader("Voice Coach Roleplay")
    result = current_result_object()
    if not result:
        st.info("Run Validate & Enrich first so voice coaching can stay grounded.")
    else:
        diagnostics = voice.diagnostics()
        if diagnostics["elevenlabs_api_key_configured"]:
            st.caption(
                f"ElevenLabs ready: voice={diagnostics['voice_id']} | tts_model={diagnostics['tts_model_id']} | stt_model={diagnostics['stt_model_id']}"
            )
        else:
            st.warning("ELEVENLABS_API_KEY is not configured, so microphone transcription and coach voice playback will not work.")
        st.caption(f"Coach provider detected: {coach.provider}")

        start_session_clicked = st.button("Start Training Session", type="primary")
        if start_session_clicked or st.session_state.get("voice_session") is None:
            start_voice_training_session(result)
            if start_session_clicked:
                st.success("Training session started.")
            else:
                st.caption("Coach session primed with an opening talk track.")

        v_session = st.session_state["voice_session"]
        st.markdown("### Live transcript")
        transcript_box = st.container(border=True)
        with transcript_box:
            st.write(st.session_state.get("voice_transcript_text") or voice.render_transcript(v_session.transcript) or "No turns yet.")

        st.markdown("### Use your microphone")
        mic_audio = st.audio_input("Record a turn as the installer")
        auto_send_mic = st.toggle("Auto-send each new recording to the coach", key="voice_auto_send_mic")
        mic_cols = st.columns([1, 2])
        with mic_cols[0]:
            mic_send_clicked = st.button("Transcribe Mic to Coach")
        with mic_cols[1]:
            if mic_audio is not None:
                st.audio(mic_audio)

        mic_bytes = mic_audio.getvalue() if mic_audio is not None else None
        mic_digest = hashlib.sha1(mic_bytes).hexdigest() if mic_bytes else ""

        def process_mic_turn() -> None:
            transcript = voice.transcribe_audio(
                mic_bytes,
                mime_type=getattr(mic_audio, "type", "audio/wav") or "audio/wav",
                filename=getattr(mic_audio, "name", "microphone.wav"),
            )
            st.session_state["voice_last_mic_transcript"] = transcript
            handle_roleplay_turn(v_session, result, transcript)
            st.session_state["voice_last_audio_digest"] = mic_digest

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
                try:
                    handle_roleplay_turn(v_session, result, user_turn)
                    st.success("Coach reply generated.")
                except Exception as exc:
                    st.session_state["voice_last_error"] = str(exc)
                    st.error(f"Roleplay generation failed: {exc}")

        if mic_send_clicked:
            if mic_audio is None:
                st.warning("Record a microphone turn first.")
            else:
                try:
                    process_mic_turn()
                    st.success("Microphone turn transcribed and sent to coach.")
                except Exception as exc:
                    st.session_state["voice_last_error"] = str(exc)
                    st.error(f"Microphone processing failed: {exc}")

        if auto_send_mic and mic_audio is not None and mic_digest and mic_digest != st.session_state.get("voice_last_audio_digest"):
            try:
                process_mic_turn()
                st.success("Latest microphone recording sent to coach automatically.")
            except Exception as exc:
                st.session_state["voice_last_error"] = str(exc)
                st.error(f"Automatic microphone processing failed: {exc}")

        if stop_clicked and v_session:
            v_session.status = "stopped"
            st.success("Training session stopped.")
            try:
                save_path = save_voice_session_md(v_session, result.quality_report.overall_score)
                st.info(f"Voice transcript saved: {save_path}")
            except Exception as exc:
                st.warning(str(exc))

        st.markdown("### Coach says")
        coach_reply = latest_coach_reply(v_session)
        if coach_reply:
            st.markdown(coach_reply)
        else:
            st.caption("Waiting for the first turn.")

        if st.session_state.get("coach_response_mode"):
            st.caption(f"Coach reply source: {st.session_state['coach_response_mode']}")

        if st.session_state.get("voice_last_mic_transcript"):
            st.markdown("### Last microphone transcript")
            st.code(st.session_state["voice_last_mic_transcript"])

        if st.session_state.get("voice_last_error"):
            st.caption(f"Last voice error: {st.session_state['voice_last_error']}")

        st.markdown("### Three-pillar summary")
        pillar_cols = st.columns(3)
        for idx, (pillar_name, pillar_value) in enumerate(PILLAR_TEMPLATE.items()):
            with pillar_cols[idx]:
                st.markdown(f"**{pillar_name}**")
                st.write(pillar_value["summary"])

        if tts_clicked:
            if coach_reply:
                try:
                    st.session_state["voice_audio_path"] = voice.synthesize_tts(coach_reply)
                    st.session_state["voice_last_error"] = ""
                    st.success("Coach voice generated.")
                except Exception as exc:
                    st.session_state["voice_last_error"] = str(exc)
                    st.error(f"Coach voice generation failed: {exc}")
            else:
                st.warning("Generate a coach reply first.")

        if st.session_state.get("voice_audio_path"):
            render_autoplay_audio(st.session_state["voice_audio_path"])
            st.audio(st.session_state["voice_audio_path"])

        if v_session and v_session.transcript:
            transcript_md = voice.transcript_markdown(v_session)
            st.download_button(
                "Download session transcript as markdown",
                data=transcript_md,
                file_name=f"{v_session.session_id}.md",
                mime="text/markdown",
            )

with tab_talk_live:
    render_talk_live_embed()
    st.markdown("---")
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

