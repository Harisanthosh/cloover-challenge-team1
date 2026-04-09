from __future__ import annotations

import os
from typing import Any, Dict, Optional

from langchain_core.prompts import ChatPromptTemplate


class SalesCoach:
    """Grounded sales coach that only reasons from quality-checked KB data."""

    def __init__(self):
        self.provider = self._detect_provider()
        self.model = self._build_model()
        self.last_response_mode = "unknown"
        self.last_model_error = ""

    def _refresh_model(self) -> None:
        self.provider = self._detect_provider()
        self.model = self._build_model()
        self.last_model_error = ""

    def _get_first_env(self, *names: str) -> str | None:
        for name in names:
            value = os.getenv(name)
            if value:
                return value
        return None

    def _detect_provider(self) -> str:
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        if self._get_first_env("Z_AI_API_KEY", "ZAI_API_KEY"):
            return "featherless"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        return "offline"

    def _anthropic_model(self) -> str:
        return self._get_first_env("ANTHROPIC_MODEL", "CLAUDE_MODEL") or "claude-sonnet-4-6"

    def _openai_compatible_base_url(self) -> str:
        return self._get_first_env("Z_AI_BASE_URL", "ZAI_BASE_URL") or "https://api.featherless.ai/v1"

    def _openai_compatible_model(self) -> str:
        return self._get_first_env("Z_AI_MODEL", "ZAI_MODEL") or "zai-org/GLM-5.1"

    def _build_model(self):
        if self.provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(
                    model=self._anthropic_model(),
                    temperature=0.2,
                    api_key=os.getenv("ANTHROPIC_API_KEY"),
                )
            except Exception:
                return None
        if self.provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
            except Exception:
                return None
        if self.provider == "featherless":
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=self._openai_compatible_model(),
                    temperature=0.2,
                    api_key=self._get_first_env("Z_AI_API_KEY", "ZAI_API_KEY"),
                    base_url=self._openai_compatible_base_url(),
                )
            except Exception:
                return None
        if self.provider == "openai":
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    temperature=0.2,
                    api_key=os.getenv("OPENAI_API_KEY"),
                )
            except Exception:
                return None
        return None

    def generate_briefing(self, kb_payload: Dict[str, Any], postal_code: str, product_interest: str) -> str:
        self._refresh_model()
        quality = kb_payload.get("quality_report", {})
        enriched = kb_payload.get("enriched_data", {})
        regulations = kb_payload.get("regulations", "")
        mission = kb_payload.get(
            "mission",
            "Powering Europe's energy transition. We help solar, heat pump, and wallbox installers sell, finance, and manage clean energy projects — and we help homeowners make the switch to renewables.",
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are Cloover AI Sales Coach, a grounded sales assistant. Use ONLY the provided quality-checked KB data. "
                    "Never hallucinate numbers. If a number is not present, say it is unavailable. "
                    "Always cite the quality score and keep the exact 3-pillar output format: Pillar 0 — Market & regulatory context, Pillar 1 — The compelling offer, Pillar 2 — The financing strategy. "
                    "Include Cloover's mission and stay firmly grounded in the knowledge base.",
                ),
                (
                    "user",
                    "Postal code: {postal_code}\nProduct: {product_interest}\nQuality score: {quality_score}\nMission: {mission}\nRegulations: {regulations}\nKB JSON: {kb_json}",
                ),
            ]
        )

        if self.model is None:
            self.last_response_mode = "offline"
            return self._offline_briefing(kb_payload, postal_code, product_interest)

        chain = prompt | self.model
        try:
            response = chain.invoke(
                {
                    "postal_code": postal_code,
                    "product_interest": product_interest,
                    "quality_score": quality.get("overall_score", "unknown"),
                    "mission": mission,
                    "regulations": regulations[:4000],
                    "kb_json": str(enriched)[:12000],
                }
            )
            self.last_response_mode = self.provider
            self.last_model_error = ""
            return getattr(response, "content", str(response))
        except Exception as exc:
            self.last_model_error = str(exc)
            if self._is_auth_error(exc):
                self.last_response_mode = "offline"
                return self._offline_briefing(kb_payload, postal_code, product_interest)
            raise

    def generate_roleplay_reply(
        self,
        roleplay_payload: Dict[str, Any],
        user_text: str,
        provider_override: Optional[str] = None,
    ) -> str:
        """Generate a conversational reply for the voice roleplay tab."""
        if provider_override is None:
            self._refresh_model()
        quality = roleplay_payload.get("quality_report", {})
        mission = roleplay_payload.get(
            "mission",
            "Powering Europe's energy transition. We help solar, heat pump, and wallbox installers sell, finance, and manage clean energy projects — and we help homeowners make the switch to renewables.",
        )
        pillars = roleplay_payload.get("pillars", {})
        kb_json = roleplay_payload.get("kb_json", {})

        model = self.model if provider_override is None else self._build_model_for(provider_override)
        if model is None:
            self.last_response_mode = "offline"
            return self._offline_roleplay_reply(quality, pillars, user_text)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are Cloover's elite sales coach for home-energy installers. Be commercially sharp, energetic, direct, and practical. "
                    "You are coaching a rep live before or during a homeowner call. Use the KB JSON and mission as ground truth, but do not give meta commentary like 'stay grounded in the three pillars' unless directly asked. "
                    "Every answer must do four things: 1) diagnose the selling mistake or gap, 2) give exact words the rep should say next, 3) explain why that wording works, 4) end with one coaching question that keeps the roleplay moving. "
                    "When there is an objection, handle it head-on with confidence, clarity, and empathy. Prefer concrete talk tracks over abstract advice. Sound like a high-performance objection-handling trainer, not a generic assistant.",
                ),
                (
                    "user",
                    "MISSION:\n{mission}\n\nQUALITY SCORE:\n{quality_score}\n\nPILLARS:\n{pillars}\n\nKB JSON:\n{kb_json}\n\nUSER SAYING:\n{user_text}\n\nReturn a live coaching reply in this structure:\nDiagnosis:\nWhat to say:\nWhy it works:\nNext question:",
                ),
            ]
        )
        chain = prompt | model
        try:
            response = chain.invoke(
                {
                    "mission": mission,
                    "quality_score": quality.get("overall_score", "unknown"),
                    "pillars": pillars,
                    "kb_json": kb_json,
                    "user_text": user_text,
                }
            )
            self.last_response_mode = provider_override or self.provider
            self.last_model_error = ""
            return getattr(response, "content", str(response))
        except Exception as exc:
            self.last_model_error = str(exc)
            if self._is_auth_error(exc):
                self.last_response_mode = "offline"
                return self._offline_roleplay_reply(quality, pillars, user_text)
            raise

    def _build_model_for(self, provider: str):
        if provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(
                    model=self._anthropic_model(),
                    temperature=0.2,
                    api_key=os.getenv("ANTHROPIC_API_KEY"),
                )
            except Exception:
                return None
        if provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
            except Exception:
                return None
        if provider in {"featherless", "z_ai"}:
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=self._openai_compatible_model(),
                    temperature=0.2,
                    api_key=self._get_first_env("Z_AI_API_KEY", "ZAI_API_KEY"),
                    base_url=self._openai_compatible_base_url(),
                )
            except Exception:
                return None
        if provider == "openai":
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    temperature=0.2,
                    api_key=os.getenv("OPENAI_API_KEY"),
                )
            except Exception:
                return None
        return None

    def _is_auth_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            token in message
            for token in [
                "401",
                "authenticationerror",
                "token expired",
                "incorrect api key",
                "incorrect",
                "invalid x-api-key",
                "permission_error",
                "authentication",
            ]
        )

    def _offline_briefing(self, kb_payload: Dict[str, Any], postal_code: str, product_interest: str) -> str:
        q = kb_payload.get("quality_report", {})
        e = kb_payload.get("enriched_data", {})
        solar = e.get("solar", {})
        market = e.get("market", {})
        mission = kb_payload.get("mission", "Cloover mission available in KB.")
        return (
            f"## Pillar 0 — Market & regulatory context\n"
            f"- Postal code: {postal_code}\n"
            f"- Product: {product_interest}\n"
            f"- Quality score: {q.get('overall_score', 'n/a')}/100\n"
            f"- Mission: {mission}\n"
            f"- Grid price assumption: {market.get('grid_price_assumption_eur_kwh', 'n/a')} EUR/kWh\n"
            f"- Solar yield estimate: {solar.get('yield_kwh_kwp_year', 'n/a')} kWh/kWp/year\n\n"
            f"## Pillar 1 — The compelling offer\n"
            f"- Starter: conservative, low-commitment option\n"
            f"- Recommended: balanced savings and payback\n"
            f"- Full Ambition: maximum self-consumption and resilience\n\n"
            f"## Pillar 2 — The financing strategy\n"
            f"- Financing: align monthly payment to current energy spend where possible.\n"
            f"- Story: 'We used quality-checked open data with score {q.get('overall_score', 'n/a')}/100 and tailored the recommendation to {product_interest}.'"
        )

    def _offline_roleplay_reply(self, quality: Dict[str, Any], pillars: Dict[str, Any], user_text: str) -> str:
        pillar_zero = pillars.get("Pillar 0 — Market & regulatory context", {}).get("summary", "market context")
        pillar_one = pillars.get("Pillar 1 — The compelling offer", {}).get("summary", "the offer")
        pillar_two = pillars.get("Pillar 2 — The financing strategy", {}).get("summary", "the financing path")
        return (
            f"Diagnosis:\nYou're starting in the right place with savings, but you're losing control when financing comes up because you don't yet have a clean money script. The quality-checked context is {quality.get('overall_score', 'n/a')}/100, so you can speak confidently.\n\n"
            f"What to say:\n'Totally fair question. Most homeowners don't buy this because it's cheap upfront, they buy it because it lowers what they pay every month and protects them from rising energy costs. Let me show you the option where the monthly payment stays comfortable and the system still makes financial sense.'\n\n"
            f"Why it works:\nIt acknowledges the concern, reframes financing from debt into cash-flow management, and moves the customer back to outcome instead of price pressure. Use {pillar_zero}, connect it to {pillar_one}, then land it with {pillar_two}.\n\n"
            f"Next question:\nIf the homeowner says, 'I still don't want another monthly payment,' what would you say next in one sentence?"
        )
