from __future__ import annotations

import os
from typing import Any, Dict, Optional

from langchain_core.prompts import ChatPromptTemplate


class SalesCoach:
    """Grounded sales coach that only reasons from quality-checked KB data."""

    def __init__(self):
        self.provider = self._detect_provider()
        self.model = self._build_model()

    def _detect_provider(self) -> str:
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        if os.getenv("Z_AI_API_KEY"):
            return "z_ai"
        return "offline"

    def _build_model(self):
        if self.provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
            except Exception:
                return None
        if self.provider == "z_ai":
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model="glm-4.5",
                    temperature=0.2,
                    api_key=os.getenv("Z_AI_API_KEY"),
                    base_url="https://api.z.ai/api/paas/v4/",
                )
            except Exception:
                return None
        return None

    def generate_briefing(self, kb_payload: Dict[str, Any], postal_code: str, product_interest: str) -> str:
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
                    "You are SolarSage Coach, a grounded sales assistant. Use ONLY the provided quality-checked KB data. "
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
            return self._offline_briefing(kb_payload, postal_code, product_interest)

        chain = prompt | self.model
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
        return getattr(response, "content", str(response))

    def generate_roleplay_reply(
        self,
        roleplay_payload: Dict[str, Any],
        user_text: str,
        provider_override: Optional[str] = None,
    ) -> str:
        """Generate a conversational reply for the voice roleplay tab."""
        quality = roleplay_payload.get("quality_report", {})
        mission = roleplay_payload.get(
            "mission",
            "Powering Europe's energy transition. We help solar, heat pump, and wallbox installers sell, finance, and manage clean energy projects — and we help homeowners make the switch to renewables.",
        )
        pillars = roleplay_payload.get("pillars", {})
        kb_json = roleplay_payload.get("kb_json", {})

        model = self.model if provider_override is None else self._build_model_for(provider_override)
        if model is None:
            return self._offline_roleplay_reply(quality, pillars, user_text)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are Cloover's official AI Sales Coach. Train the installer rep in real-time. Always base every response on the provided KB JSON, the three pillars, and Cloover's mission. Roleplay as a supportive senior coach. Use natural spoken language. End responses with a question to continue the roleplay.",
                ),
                (
                    "user",
                    "MISSION:\n{mission}\n\nQUALITY SCORE:\n{quality_score}\n\nPILLARS:\n{pillars}\n\nKB JSON:\n{kb_json}\n\nUSER SAYING:\n{user_text}",
                ),
            ]
        )
        chain = prompt | model
        response = chain.invoke(
            {
                "mission": mission,
                "quality_score": quality.get("overall_score", "unknown"),
                "pillars": pillars,
                "kb_json": kb_json,
                "user_text": user_text,
            }
        )
        return getattr(response, "content", str(response))

    def _build_model_for(self, provider: str):
        if provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
            except Exception:
                return None
        if provider == "z_ai":
            try:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model="glm-4.5",
                    temperature=0.2,
                    api_key=os.getenv("Z_AI_API_KEY"),
                    base_url="https://api.z.ai/api/paas/v4/",
                )
            except Exception:
                return None
        return None

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
        return (
            f"I’d keep that grounded in the KB and the three pillars. Quality score is {quality.get('overall_score', 'n/a')}/100, "
            f"so we can confidently frame the pitch around Pillar 0 for context, Pillar 1 for the offer, and Pillar 2 for financing. "
            f"Based on what you just said — '{user_text}' — what part of the pitch do you want to sharpen next?"
        )
