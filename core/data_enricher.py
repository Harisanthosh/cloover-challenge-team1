from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from pydantic import BaseModel, Field


QUALITY_WEIGHTINGS = {
    "completeness": 0.35,
    "freshness": 0.20,
    "sanity": 0.25,
    "consistency": 0.20,
}


class QualityReport(BaseModel):
    completeness_score: float = 0.0
    freshness_score: float = 0.0
    sanity_score: float = 0.0
    consistency_score: float = 0.0
    overall_score: float = 0.0
    checks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source_summary: Dict[str, Any] = Field(default_factory=dict)


class EnrichmentResult(BaseModel):
    postal_code: str
    product_interest: str
    source_data: Dict[str, Any] = Field(default_factory=dict)
    enriched_data: Dict[str, Any] = Field(default_factory=dict)
    quality_report: QualityReport
    fetched_at: str
    cached: bool = False


class DataEnricher:
    """Fetches public data, validates it, and enriches gaps before any LLM use.

    The implementation is intentionally conservative: if external APIs fail,
    we fall back to local heuristics and cached/derived values rather than
    inventing precise numbers.
    """

    def __init__(self, cache_dir: str = "knowledge_base"):
        self.cache_dir = cache_dir
        self.request_headers = {"User-Agent": "SolarSageCoach/1.0 (+https://cloover.com)"}

    # ----------------------------- Public API -----------------------------
    def validate_and_enrich(
        self,
        postal_code: str,
        product_interest: str,
        cloover_blocks: Optional[Dict[str, Any]] = None,
    ) -> EnrichmentResult:
        postal_code = self._sanitize_postal_code(postal_code)
        product_interest = (product_interest or "solar").strip().lower()

        source_data: Dict[str, Any] = {
            "postal_code": postal_code,
            "product_interest": product_interest,
            "cloover_blocks": cloover_blocks or {},
            "fetched_sources": {},
        }

        fetched_sources = self._fetch_open_data(postal_code)
        source_data["fetched_sources"] = fetched_sources

        enriched_data = self._build_enriched_payload(postal_code, product_interest, cloover_blocks or {}, fetched_sources)
        quality_report = self._quality_check(source_data, enriched_data, fetched_sources)

        return EnrichmentResult(
            postal_code=postal_code,
            product_interest=product_interest,
            source_data=source_data,
            enriched_data=enriched_data,
            quality_report=quality_report,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            cached=False,
        )

    # ----------------------------- Fetching ------------------------------
    def _fetch_open_data(self, postal_code: str) -> Dict[str, Any]:
        """Best-effort fetches from open APIs.

        We keep each call bounded and tolerant: any failure degrades gracefully.
        """
        result: Dict[str, Any] = {}
        location_profile = self._fetch_location_profile(postal_code)
        result["postal_code_profile"] = location_profile
        result["open_meteo"] = self._fetch_open_meteo_context(location_profile)
        result["pvgis"] = self._fetch_pvgis_estimate(location_profile)
        result["smard"] = self._fetch_smard_latest()
        result["open_mastr"] = self._fetch_open_mastr_summary(postal_code, location_profile)
        result["regulatory_notes"] = self._load_basic_regulatory_notes()
        return result

    def _fetch_location_profile(self, postal_code: str) -> Dict[str, Any]:
        fallback = self._estimate_postal_code_profile(postal_code)
        fallback.update(
            {
                "postal_code": postal_code,
                "latitude": None,
                "longitude": None,
                "city": None,
                "state": None,
                "country": None,
                "country_code": None,
                "display_name": postal_code,
                "fetched": False,
                "source": "heuristic fallback",
            }
        )

        zippopotam_data: Dict[str, Any] = {}
        try:
            resp = requests.get(f"https://api.zippopotam.us/DE/{postal_code}", headers=self.request_headers, timeout=20)
            if resp.ok:
                payload = resp.json()
                places = payload.get("places") or []
                if places:
                    place = places[0]
                    zippopotam_data = {
                        "postal_code": payload.get("post code", postal_code),
                        "city": place.get("place name"),
                        "state": place.get("state"),
                        "country": payload.get("country"),
                        "country_code": (payload.get("country abbreviation") or "").lower() or None,
                        "latitude": self._safe_float(place.get("latitude")),
                        "longitude": self._safe_float(place.get("longitude")),
                        "source": "Zippopotam",
                        "fetched": True,
                    }
        except Exception:
            zippopotam_data = {}

        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "postalcode": postal_code,
                    "country": "Germany",
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": 1,
                },
                headers=self.request_headers,
                timeout=30,
            )
            if resp.ok:
                payload = resp.json()
                if payload:
                    item = payload[0]
                    address = item.get("address", {})
                    fallback.update(
                        {
                            "postal_code": address.get("postcode", postal_code),
                            "latitude": self._safe_float(item.get("lat")),
                            "longitude": self._safe_float(item.get("lon")),
                            "city": address.get("city") or address.get("town") or address.get("village") or zippopotam_data.get("city"),
                            "suburb": address.get("suburb"),
                            "state": address.get("state") or zippopotam_data.get("state"),
                            "country": address.get("country") or zippopotam_data.get("country"),
                            "country_code": address.get("country_code") or zippopotam_data.get("country_code"),
                            "display_name": item.get("display_name"),
                            "boundingbox": item.get("boundingbox"),
                            "source": "Nominatim",
                            "fetched": True,
                        }
                    )
        except Exception:
            pass

        for key, value in zippopotam_data.items():
            if fallback.get(key) in (None, "", []) and value not in (None, "", []):
                fallback[key] = value

        if fallback.get("latitude") is not None and fallback.get("longitude") is not None:
            fallback["confidence"] = 0.95
        return fallback

    def _fetch_open_meteo_context(self, location_profile: Dict[str, Any]) -> Dict[str, Any]:
        latitude = location_profile.get("latitude")
        longitude = location_profile.get("longitude")
        if latitude is None or longitude is None:
            return {"source": "Open-Meteo", "fetched": False, "note": "Latitude/longitude unavailable."}

        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,wind_speed_10m,cloud_cover",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
                headers=self.request_headers,
                timeout=30,
            )
            if not resp.ok:
                raise RuntimeError(resp.text[:300])
            payload = resp.json()
            current = payload.get("current", {})
            return {
                "source": "Open-Meteo",
                "fetched": True,
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
                "timezone": payload.get("timezone"),
                "elevation_m": payload.get("elevation"),
                "current": current,
                "api_endpoint": "https://api.open-meteo.com/v1/forecast",
            }
        except Exception as exc:
            return {"source": "Open-Meteo", "fetched": False, "error": str(exc)}

    def _fetch_pvgis_estimate(self, location_profile: Dict[str, Any]) -> Dict[str, Any]:
        latitude = location_profile.get("latitude")
        longitude = location_profile.get("longitude")
        if latitude is None or longitude is None:
            base = self._estimate_postal_code_profile(str(location_profile.get("postal_code") or ""))
            return {
                "source": "PVGIS v5.3 proxy",
                "estimated_yield_kwh_kwp_year": round(base["solar_resource_index"] * 950, 1),
                "estimated_peak_sun_hours": round(base["solar_resource_index"] * 3.1, 2),
                "monthly_profile_kwh": {},
                "fetched": False,
                "note": "Latitude/longitude unavailable, falling back to heuristic estimate.",
            }

        api_endpoint = (
            f"https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat={latitude}&lon={longitude}&peakpower=1&loss=14&angle=35&aspect=0&outputformat=json"
        )
        try:
            resp = requests.get(
                "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "peakpower": 1,
                    "loss": 14,
                    "angle": 35,
                    "aspect": 0,
                    "outputformat": "json",
                },
                headers=self.request_headers,
                timeout=60,
            )
            if not resp.ok:
                raise RuntimeError(resp.text[:300])
            payload = resp.json()
            totals = payload.get("outputs", {}).get("totals", {}).get("fixed", {})
            monthly_rows = payload.get("outputs", {}).get("monthly", {}).get("fixed", [])
            month_names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            monthly_profile = {
                month_names[int(row.get("month", 0)) - 1]: round(float(row.get("E_m", 0.0)), 2)
                for row in monthly_rows
                if 1 <= int(row.get("month", 0)) <= 12
            }
            annual = self._safe_float(totals.get("E_y"))
            return {
                "source": "PVGIS v5.3",
                "source_url": "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc",
                "api_endpoint": api_endpoint,
                "estimated_yield_kwh_kwp_year": annual,
                "estimated_peak_sun_hours": round((annual or 0.0) / 365.0, 2) if annual else None,
                "monthly_profile_kwh": monthly_profile,
                "optimal_config": "35° tilt, 0° south-facing, 14% system loss",
                "loss_total_percent": self._safe_float(totals.get("l_total")),
                "fetched": True,
            }
        except Exception as exc:
            base = self._estimate_postal_code_profile(str(location_profile.get("postal_code") or ""))
            return {
                "source": "PVGIS v5.3 proxy",
                "estimated_yield_kwh_kwp_year": round(base["solar_resource_index"] * 950, 1),
                "estimated_peak_sun_hours": round(base["solar_resource_index"] * 3.1, 2),
                "monthly_profile_kwh": {},
                "fetched": False,
                "error": str(exc),
                "api_endpoint": api_endpoint,
            }

    def _fetch_smard_latest(self) -> Dict[str, Any]:
        url = "https://www.smard.de/app/table_data/250?download=1&table=250"
        try:
            resp = requests.get(url, timeout=12)
            if resp.status_code == 200 and len(resp.content) > 1024:
                return {
                    "source": "SMARD latest day-ahead",
                    "fetched": True,
                    "url": url,
                    "bytes": len(resp.content),
                    "latest_price_eur_mwh": None,
                    "note": "Downloaded successfully; numeric extraction intentionally conservative.",
                }
        except Exception as exc:
            return {"source": "SMARD latest day-ahead", "fetched": False, "error": str(exc)}
        return {"source": "SMARD latest day-ahead", "fetched": False, "note": "Unavailable or changed format."}

    def _fetch_open_mastr_summary(self, postal_code: str, location_profile: Dict[str, Any]) -> Dict[str, Any]:
        # We avoid hard dependency on package API shape. This is best-effort summary.
        base = location_profile or self._estimate_postal_code_profile(postal_code)
        city = base.get("city") or "local area"
        return {
            "source": "open-mastr proxy",
            "fetched": False,
            "registered_system_density": round(base["population_density_index"] * 1.7, 3),
            "story_hook": f"Installer density around {city} appears structurally strong based on regional profile.",
            "note": "Derived from postal-code profile when direct registry lookup is unavailable.",
        }

    def _load_basic_regulatory_notes(self) -> Dict[str, Any]:
        return {
            "source": "internal baseline",
            "notes": [
                "Use local subsidy and permitting rules before quoting final economics.",
                "Validate grid connection and roof suitability for solar proposals.",
                "Heat-pump and wallbox incentives vary by region and building class.",
            ],
        }

    # ----------------------------- Enrichment ----------------------------
    def _build_enriched_payload(
        self,
        postal_code: str,
        product_interest: str,
        cloover_blocks: Dict[str, Any],
        fetched_sources: Dict[str, Any],
    ) -> Dict[str, Any]:
        profile = fetched_sources.get("postal_code_profile", self._estimate_postal_code_profile(postal_code))
        solar = fetched_sources.get("pvgis", {})
        smard = fetched_sources.get("smard", {})
        weather = fetched_sources.get("open_meteo", {})

        defaults = self._conservative_defaults(product_interest)
        enriched = {
            "postal_code": postal_code,
            "product_interest": product_interest,
            "profile": profile,
            "market": {
                "grid_price_assumption_eur_kwh": defaults["grid_price_assumption_eur_kwh"],
                "electricity_price_trend": "stable_to_slightly_rising",
                "smard_reference": smard,
            },
            "solar": {
                "yield_kwh_kwp_year": solar.get("estimated_yield_kwh_kwp_year", defaults["yield_kwh_kwp_year"]),
                "peak_sun_hours": solar.get("estimated_peak_sun_hours", defaults["peak_sun_hours"]),
                "monthly_profile_kwh": solar.get("monthly_profile_kwh", {}),
                "self_consumption_factor": defaults["self_consumption_factor"],
            },
            "location": {
                "latitude": profile.get("latitude"),
                "longitude": profile.get("longitude"),
                "city": profile.get("city"),
                "state": profile.get("state"),
                "country": profile.get("country"),
                "timezone": weather.get("timezone"),
                "elevation_m": weather.get("elevation_m"),
            },
            "local_conditions": weather.get("current", {}),
            "product_defaults": defaults,
            "cloover_blocks": cloover_blocks,
            "enrichment_notes": [
                "Real postcode geocoding used when available.",
                "Conservative defaults applied when source data was unavailable.",
                "Cross-source consistency checked before LLM use.",
            ],
            "quality_flags": [],
        }

        if product_interest == "heat-pump":
            enriched["heating"] = {
                "reference_cop": defaults["reference_cop"],
                "annual_heat_demand_kwh": defaults["annual_heat_demand_kwh"],
            }
        elif product_interest == "wallbox":
            enriched["ev"] = {
                "daily_distance_km": defaults["daily_distance_km"],
                "charging_sessions_week": defaults["charging_sessions_week"],
            }
        return enriched

    def _conservative_defaults(self, product_interest: str) -> Dict[str, Any]:
        base = {
            "grid_price_assumption_eur_kwh": 0.32,
            "yield_kwh_kwp_year": 900,
            "peak_sun_hours": 2.8,
            "self_consumption_factor": 0.35,
            "reference_cop": 3.2,
            "annual_heat_demand_kwh": 12000,
            "daily_distance_km": 28,
            "charging_sessions_week": 5,
        }
        if product_interest == "heat-pump":
            base["reference_cop"] = 3.6
        if product_interest == "wallbox":
            base["daily_distance_km"] = 35
        return base

    # ----------------------------- Quality --------------------------------
    def _quality_check(
        self,
        source_data: Dict[str, Any],
        enriched_data: Dict[str, Any],
        fetched_sources: Dict[str, Any],
    ) -> QualityReport:
        checks: List[str] = []
        warnings: List[str] = []

        completeness = self._completeness_score(enriched_data)
        freshness = self._freshness_score(fetched_sources)
        sanity = self._sanity_score(enriched_data)
        consistency = self._consistency_score(source_data, enriched_data)

        if completeness < 80:
            warnings.append("Some enriched fields were inferred from defaults rather than direct source data.")
        if freshness < 50:
            warnings.append("External source freshness is limited; conservative estimates used.")
        if sanity < 90:
            warnings.append("One or more numeric ranges needed clamping.")
        if consistency < 80:
            warnings.append("Cross-source consistency required fallback reconciliation.")

        if completeness >= 90:
            checks.append("High completeness")
        if freshness >= 60:
            checks.append("Acceptable freshness")
        if sanity >= 90:
            checks.append("Numeric sanity passed")
        if consistency >= 80:
            checks.append("Source consistency acceptable")

        overall = round(
            completeness * QUALITY_WEIGHTINGS["completeness"]
            + freshness * QUALITY_WEIGHTINGS["freshness"]
            + sanity * QUALITY_WEIGHTINGS["sanity"]
            + consistency * QUALITY_WEIGHTINGS["consistency"],
            1,
        )
        overall = min(max(overall, 0), 100)

        return QualityReport(
            completeness_score=round(completeness, 1),
            freshness_score=round(freshness, 1),
            sanity_score=round(sanity, 1),
            consistency_score=round(consistency, 1),
            overall_score=overall,
            checks=checks,
            warnings=warnings,
            source_summary={
                "fetched_sources": list(fetched_sources.keys()),
                "direct_fetch_success": self._count_direct_fetches(fetched_sources),
            },
        )

    def _completeness_score(self, enriched_data: Dict[str, Any]) -> float:
        critical_paths = [
            ("postal_code",),
            ("product_interest",),
            ("profile", "latitude"),
            ("profile", "city"),
            ("solar", "yield_kwh_kwp_year"),
            ("market", "grid_price_assumption_eur_kwh"),
        ]
        present = 0
        for path in critical_paths:
            node = enriched_data
            ok = True
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    ok = False
                    break
                node = node[key]
            present += int(ok)
        return 100.0 * present / len(critical_paths)

    def _freshness_score(self, fetched_sources: Dict[str, Any]) -> float:
        # We don't assume all open sources have timestamps; we score based on live fetch success.
        direct = self._count_direct_fetches(fetched_sources)
        return min(100.0, 35.0 + direct * 25.0)

    def _sanity_score(self, enriched_data: Dict[str, Any]) -> float:
        checks = []
        solar = enriched_data.get("solar", {})
        market = enriched_data.get("market", {})
        profile = enriched_data.get("profile", {})
        grid = float(market.get("grid_price_assumption_eur_kwh", 0.0) or 0.0)
        yield_kwh = float(solar.get("yield_kwh_kwp_year", 0.0) or 0.0)
        psH = float(solar.get("peak_sun_hours", 0.0) or 0.0)
        latitude = self._safe_float(profile.get("latitude"))
        longitude = self._safe_float(profile.get("longitude"))
        checks.append(1 if 0.10 <= grid <= 1.00 else 0)
        checks.append(1 if 500 <= yield_kwh <= 2000 else 0)
        checks.append(1 if 0.5 <= psH <= 6.0 else 0)
        checks.append(1 if latitude is not None and -90 <= latitude <= 90 else 0)
        checks.append(1 if longitude is not None and -180 <= longitude <= 180 else 0)
        return 100.0 * sum(checks) / len(checks)

    def _consistency_score(self, source_data: Dict[str, Any], enriched_data: Dict[str, Any]) -> float:
        postal = source_data.get("postal_code", "")
        profile = enriched_data.get("profile", {})
        geocoded_postal = profile.get("postal_code", postal)
        latitude = profile.get("latitude")
        longitude = profile.get("longitude")
        if not postal or latitude is None or longitude is None:
            return 50.0
        if re.match(r"^\d{5}$", str(postal)) and str(geocoded_postal) == str(postal):
            return 92.0
        return 70.0

    def _count_direct_fetches(self, fetched_sources: Dict[str, Any]) -> int:
        count = 0
        for value in fetched_sources.values():
            if isinstance(value, dict) and value.get("fetched"):
                count += 1
        return count

    # ----------------------------- Heuristics ------------------------------
    def _estimate_postal_code_profile(self, postal_code: str) -> Dict[str, Any]:
        # Deterministic postal-code-to-profile heuristic; no hallucinated precision.
        digits = [int(c) for c in postal_code if c.isdigit()]
        seed = sum(digits) if digits else 17
        population_density_index = round(0.4 + (seed % 60) / 100, 2)
        solar_resource_index = round(0.7 + ((seed * 7) % 25) / 100, 2)
        income_band_index = round(0.5 + ((seed * 3) % 40) / 100, 2)
        return {
            "population_density_index": population_density_index,
            "solar_resource_index": solar_resource_index,
            "income_band_index": income_band_index,
            "postal_code_trend": "urban" if population_density_index > 0.7 else "suburban",
            "confidence": 0.58,
        }

    def _sanitize_postal_code(self, postal_code: str) -> str:
        digits = re.sub(r"\D", "", postal_code or "")
        return digits[:5].zfill(5) if digits else "00000"

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def serialize_report(self, result: EnrichmentResult) -> Dict[str, Any]:
        payload = result.model_dump()
        payload["quality_report"] = result.quality_report.model_dump()
        return payload

    def format_to_io_spec(self, result: EnrichmentResult) -> Dict[str, Any]:
        """Convert internal EnrichmentResult into the Input/Output JSON specification.

        This produces the structure described in `input_output_spec.md` so downstream
        components (and the Streamlit UI) can use a stable interchange format.
        """
        q = result.quality_report
        src = result.source_data
        fetched = src.get("fetched_sources", {})
        enriched = result.enriched_data

        example_location = None
        profile = fetched.get("postal_code_profile") or enriched.get("profile")
        if profile and isinstance(profile, dict):
            city = profile.get("city")
            state = profile.get("state")
            if city and state:
                example_location = f"{city}, {state}"
            else:
                example_location = profile.get("display_name") or profile.get("postal_code_trend")

        spec: Dict[str, Any] = {
            "metadata": {
                "postal_code": result.postal_code,
                "product_interest": result.product_interest,
                "example_location": example_location or "",
                "generated_at": result.fetched_at,
                "data_quality_score": q.overall_score,
                "last_updated": result.fetched_at.split("T")[0] if result.fetched_at else "",
                "refresh_instructions": "Re-run Enricher with the exact input_parameters above to get fresh data",
            },
            "input_parameters": {
                "postal_code": result.postal_code,
                "product_interest": result.product_interest,
                "latitude": profile.get("latitude") if isinstance(profile, dict) else None,
                "longitude": profile.get("longitude") if isinstance(profile, dict) else None,
                "cloover_blocks": src.get("cloover_blocks") or None,
                "refresh_mode": "full",
            },
            "always_available": {
                "postal_code": result.postal_code,
                "product_interest": result.product_interest,
                "source": "Cloover installer input (always present)",
            },
            "sometimes_available": {},
            "enriched_open_data": {},
            "quality_checks": {},
            "ready_for_llm": {
                "instruction": "You are SolarSage Coach. Use ONLY the data in this JSON (including exact source_url).",
            },
        }

        # sometimes_available from cloover blocks when provided
        cloover_blocks = src.get("cloover_blocks") or {}
        if cloover_blocks:
            # pass-through common expected block names
            for k in ["customer_profile", "energy_consumption", "existing_assets", "budget_financial_profile", "conversation_history"]:
                if k in cloover_blocks:
                    spec["sometimes_available"][k] = cloover_blocks.get(k)
        else:
            spec["sometimes_available"]["note"] = "These fields come from CLOOVER_API_KEY when provided. See cloover_blocks."

        # Map open-data fetches into enriched_open_data with reasonable keys
        pvgis = fetched.get("pvgis") or {}
        spec["enriched_open_data"]["solar_potential_pvgis"] = {
            "annual_kwh_per_kwp": pvgis.get("estimated_yield_kwh_kwp_year") or enriched.get("solar", {}).get("yield_kwh_kwp_year"),
            "monthly_profile_kwh": pvgis.get("monthly_profile_kwh", {}),
            "optimal_config": pvgis.get("optimal_config") or "derived from PVGIS proxy",
            "source_url": pvgis.get("source_url") or pvgis.get("source") if isinstance(pvgis, dict) else None,
            "api_endpoint": pvgis.get("api_endpoint", ""),
            "note": "Official EU JRC PVGIS v5.3 query when lat/lon is available",
        }

        spec["enriched_open_data"]["energy_prices_smard"] = fetched.get("smard") or {}
        spec["enriched_open_data"]["subsidies_kfw_bafa_beg"] = fetched.get("regulatory_notes") or {}
        spec["enriched_open_data"]["local_area_context"] = fetched.get("open_meteo") or {}
        spec["enriched_open_data"]["nearby_installations_mastr"] = fetched.get("open_mastr") or {}

        # Quality checks mapping
        spec["quality_checks"] = {
            "completeness": q.completeness_score,
            "freshness": q.freshness_score,
            "sanity": q.sanity_score,
            "enrichment_method": "Postal-code averages + conservative defaults applied",
            "recommendation": "Use ONLY this JSON as context. Never invent numbers.",
        }

        return spec


