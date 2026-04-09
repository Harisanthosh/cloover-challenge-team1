from __future__ import annotations

import base64
import io
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


@dataclass
class VoiceMessage:
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class VoiceSession:
    session_id: str
    postal_code: str
    product_interest: str
    quality_score: float
    mission_text: str
    pillar_summary: Dict[str, Any]
    transcript: List[VoiceMessage] = field(default_factory=list)
    status: str = "idle"
    last_error: Optional[str] = None


class VoiceHandler:
    """Best-effort voice orchestration for the Cloover roleplay demo.

    Design goals:
    - Prefer ElevenLabs realtime / streaming when available.
    - Fall back to text roleplay + ElevenLabs TTS playback.
    - Never block the whole app if a voice SDK is unavailable.
    """

    def __init__(self):
        self.api_key = self._get_first_env("ELEVENLABS_API_KEY") or ""
        self.voice_id = self._get_first_env("ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE") or "Rachel"
        self.model_id = self._get_first_env("ELEVENLABS_MODEL_ID", "ELEVENLABS_MODEL") or "eleven_turbo_v2_5"
        self.stt_model = self._get_first_env("ELEVENLABS_STT_MODEL_ID", "ELEVENLABS_STT_MODEL") or "scribe_v1"

    def _get_first_env(self, *names: str) -> Optional[str]:
        for name in names:
            value = os.getenv(name)
            if value:
                return value
        return None

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "elevenlabs_api_key_configured": bool(self.api_key),
            "voice_id": self.voice_id,
            "tts_model_id": self.model_id,
            "stt_model_id": self.stt_model,
        }

    # ----------------------------- Session --------------------------------
    def create_session(
        self,
        postal_code: str,
        product_interest: str,
        quality_score: float,
        mission_text: str,
        pillar_summary: Dict[str, Any],
    ) -> VoiceSession:
        session_id = datetime.now(timezone.utc).strftime("voice_%Y%m%d_%H%M%S")
        return VoiceSession(
            session_id=session_id,
            postal_code=postal_code,
            product_interest=product_interest,
            quality_score=quality_score,
            mission_text=mission_text,
            pillar_summary=pillar_summary,
        )

    def add_user_turn(self, session: VoiceSession, text: str) -> None:
        session.transcript.append(VoiceMessage(role="installer", content=text))

    def add_coach_turn(self, session: VoiceSession, text: str) -> None:
        session.transcript.append(VoiceMessage(role="coach", content=text))

    # ----------------------------- Prompting ------------------------------
    def build_roleplay_prompt(self, session: VoiceSession, kb_json: Dict[str, Any]) -> str:
        return (
            "You are Cloover's official AI Sales Coach. Train the installer rep in real-time. "
            "Always base every response on the provided KB JSON, the three pillars, and Cloover's mission. "
            "Roleplay as a supportive senior coach. Use natural spoken language. End responses with a question to continue the roleplay.\n\n"
            f"MISSION:\n{session.mission_text}\n\n"
            f"QUALITY SCORE:\n{session.quality_score}/100\n\n"
            f"PILLARS:\n{json.dumps(session.pillar_summary, indent=2, ensure_ascii=False)}\n\n"
            f"KB JSON:\n{json.dumps(kb_json, indent=2, ensure_ascii=False)}\n\n"
            f"TRANSCRIPT SO FAR:\n{self.render_transcript(session.transcript)}"
        )

    # ----------------------------- Text coach -----------------------------
    def generate_coach_reply(self, session: VoiceSession, kb_json: Dict[str, Any], user_text: str) -> str:
        """Generate a grounded reply.

        If LLM access is unavailable, returns a structured offline response.
        """
        self.add_user_turn(session, user_text)
        try:
            from langchain_core.prompts import ChatPromptTemplate
        except Exception:
            reply = self._offline_reply(session, kb_json, user_text)
            self.add_coach_turn(session, reply)
            return reply

        model = self._build_llm()
        if model is None:
            reply = self._offline_reply(session, kb_json, user_text)
            self.add_coach_turn(session, reply)
            return reply

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are Cloover's official AI Sales Coach. Train the installer rep in real-time. "
                    "Always base every response on the provided KB JSON, the three pillars, and Cloover's mission. "
                    "Roleplay as a supportive senior coach. Use natural spoken language. End responses with a question to continue the roleplay.",
                ),
                (
                    "user",
                    "MISSION:\n{mission}\n\nPILLARS:\n{pillars}\n\nKB JSON:\n{kb_json}\n\nLATEST USER TURN:\n{user_text}",
                ),
            ]
        )

        chain = prompt | model
        response = chain.invoke(
            {
                "mission": session.mission_text,
                "pillars": json.dumps(session.pillar_summary, indent=2, ensure_ascii=False),
                "kb_json": json.dumps(kb_json, indent=2, ensure_ascii=False),
                "user_text": user_text,
            }
        )
        reply = getattr(response, "content", str(response))
        self.add_coach_turn(session, reply)
        return reply

    def _offline_reply(self, session: VoiceSession, kb_json: Dict[str, Any], user_text: str) -> str:
        quality = session.quality_score
        p0 = session.pillar_summary.get("Pillar 0", {})
        p1 = session.pillar_summary.get("Pillar 1", {})
        p2 = session.pillar_summary.get("Pillar 2", {})
        return (
            f"Good instinct. For this location we keep the advice grounded in the quality-checked KB, "
            f"which is at {quality}/100. Use Pillar 0 to frame why now: {p0.get('summary', 'market and regulatory context')}. "
            f"Then anchor the offer in Pillar 1: {p1.get('summary', 'the three packages')}. "
            f"Finally, compare the financing paths in Pillar 2: {p2.get('summary', 'cash, partial, or 100% Cloover-financed')}. "
            f"If you want to improve the pitch, would you lead with savings, monthly payment, or speed of installation?"
        )

    def _build_llm(self):
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(
                    model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                    temperature=0.2,
                    api_key=os.getenv("ANTHROPIC_API_KEY"),
                )
            except Exception:
                return None
        if os.getenv("GEMINI_API_KEY"):
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
            except Exception:
                return None
        if os.getenv("Z_AI_API_KEY") or os.getenv("ZAI_API_KEY"):
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=os.getenv("Z_AI_MODEL", "zai-org/GLM-5.1"),
                    temperature=0.2,
                    api_key=self._get_first_env("Z_AI_API_KEY", "ZAI_API_KEY"),
                    base_url=os.getenv("Z_AI_BASE_URL", "https://api.featherless.ai/v1"),
                )
            except Exception:
                return None
        return None

    # ----------------------------- STT -----------------------------------
    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav", filename: str = "microphone.wav") -> str:
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured.")

        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": self.api_key}
        data = {"model_id": self.stt_model}
        files = {"file": (filename, audio_bytes, mime_type)}

        resp = requests.post(url, headers=headers, data=data, files=files, timeout=120)
        if not resp.ok:
            raise RuntimeError(f"ElevenLabs STT failed: {resp.status_code} {resp.text[:300]}")

        payload = resp.json()
        transcript = payload.get("text") or payload.get("transcript") or payload.get("normalized_text") or ""
        transcript = transcript.strip()
        if not transcript:
            raise RuntimeError("ElevenLabs STT returned an empty transcript.")
        return transcript

    # ----------------------------- TTS -----------------------------------
    def synthesize_tts(self, text: str, out_dir: Optional[str] = None) -> Optional[str]:
        """Best-effort ElevenLabs TTS.

        Returns a local file path if audio was created, otherwise None.
        """
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured.")

        target_dir = Path(out_dir or tempfile.gettempdir())
        target_dir.mkdir(parents=True, exist_ok=True)
        wav_path = target_dir / f"elevenlabs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp3"

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60, stream=True)
        if not resp.ok:
            raise RuntimeError(f"ElevenLabs TTS failed: {resp.status_code} {resp.text[:300]}")
        with open(wav_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return str(wav_path)

    # ----------------------------- Transcript -----------------------------
    def render_transcript(self, transcript: List[VoiceMessage]) -> str:
        return "\n".join(f"{item.role.upper()}: {item.content}" for item in transcript)

    def transcript_markdown(self, session: VoiceSession) -> str:
        lines = [
            "# SolarSage Coach Voice Roleplay",
            "",
            f"- Session: {session.session_id}",
            f"- Postal code: {session.postal_code}",
            f"- Product: {session.product_interest}",
            f"- Quality score: {session.quality_score}",
            "",
            "## Mission",
            session.mission_text,
            "",
            "## Transcript",
        ]
        for item in session.transcript:
            lines.append(f"- {item.timestamp} **{item.role}**: {item.content}")
        return "\n".join(lines)

