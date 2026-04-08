from __future__ import annotations

import os
from typing import Any, Dict

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
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
        if self.provider == "z_ai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model="glm-4.5",
                temperature=0.2,
                api_key=os.getenv("Z_AI_API_KEY"),
                base_url="https://api.z.ai/api/paas/v4/",
            )
        return None

    def generate_briefing(self, kb_payload: Dict[str, Any], postal_code: str, product_interest: str) -> str:
        quality = kb_payload.get("quality_report", {})
        enriched = kb_payload.get("enriched_data", {})
        regulations = kb_payload.get("regulations", "")

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are SolarSage Coach, a grounded sales assistant. Use ONLY the provided quality-checked KB data. "
                    "Never hallucinate numbers. If a number is not present, say it is unavailable. "
                    "Always cite the quality score and keep the exact 3-pillar output format: Market Context, 3 Packages, Financing Strategy + story script.",
                ),
                (
                    "user",
                    "Postal code: {postal_code}\nProduct: {product_interest}\nQuality score: {quality_score}\nRegulations: {regulations}\nKB JSON: {kb_json}",
                ),
            ]
        )

        if self.model is None:
            return self._offline_response(kb_payload, postal_code, product_interest)

        chain = prompt | self.model
        response = chain.invoke(
            {
                "postal_code": postal_code,
                "product_interest": product_interest,
                "quality_score": quality.get("overall_score", "unknown"),
                "regulations": regulations[:4000],
                "kb_json": str(enriched)[:12000],
            }
        )
        return getattr(response, "content", str(response))

    def _offline_response(self, kb_payload: Dict[str, Any], postal_code: str, product_interest: str) -> str:
        q = kb_payload.get("quality_report", {})
        e = kb_payload.get("enriched_data", {})
        solar = e.get("solar", {})
        market = e.get("market", {})
        return (
            f"## Market Context\n"
            f"- Postal code: {postal_code}\n"
            f"- Product: {product_interest}\n"
            f"- Quality score: {q.get('overall_score', 'n/a')}/100\n"
            f"- Grid price assumption: {market.get('grid_price_assumption_eur_kwh', 'n/a')} EUR/kWh\n"
            f"- Solar yield estimate: {solar.get('yield_kwh_kwp_year', 'n/a')} kWh/kWp/year\n\n"
            f"## 3 Packages\n"
            f"- Starter: conservative, low-commitment option\n"
            f"- Recommended: balanced savings and payback\n"
            f"- Premium: maximum self-consumption and resilience\n\n"
            f"## Financing Strategy + story script\n"
            f"- Financing: align monthly payment to current energy spend where possible.\n"
            f"- Story: "
            f"'For this location, we used quality-checked open data with score {q.get('overall_score', 'n/a')}/100, "
            f"then tailored the recommendation to {product_interest}.'"
        )


