# Input / Output JSON Specification

## Input

```json
{
  "input_parameters": {
    "postal_code": "69123",
    "product_interest": "solar",
    "latitude": 49.398,
    "longitude": 8.672,
    "cloover_blocks": {
      "customer_profile": { "...": "..." },
      "energy_consumption": { "...": "..." },
      "existing_assets": { "...": "..." },
      "budget_financial_profile": { "...": "..." },
      "conversation_history": { "...": "..." }
    },
    "refresh_mode": "full"
  }
}
```

---

## Output

```json
{
  "metadata": {
    "postal_code": "69123",
    "product_interest": "solar",
    "example_location": "Heidelberg, Baden-Württemberg",
    "generated_at": "2026-04-08T15:11:00Z",
    "data_quality_score": 95,
    "last_updated": "2026-04-08",
    "refresh_instructions": "Re-run Enricher with the exact input_parameters above to get fresh data"
  },

  "input_parameters": {
    "postal_code": "69123",
    "product_interest": "solar",
    "latitude": 49.398,
    "longitude": 8.672,
    "cloover_blocks": null,
    "refresh_mode": "full"
  },

  "always_available": {
    "postal_code": "69123",
    "product_interest": "solar",
    "source": "Cloover installer input (always present)"
  },

  "sometimes_available": {
    "note": "These fields come from CLOOVER_API_KEY when provided. Below is realistic example structure.",
    "customer_profile": {
      "household_size": 4,
      "personal_details": "Family with 2 children, owner-occupied single-family house",
      "property_details": {
        "roof_type": "south-facing pitched roof",
        "roof_area_m2": 120,
        "existing_solar": "Possible 4 kWp system that can be extended"
      }
    },
    "energy_consumption": {
      "annual_kwh": 3500,
      "monthly_profile": "Higher in winter (heating)",
      "source": "Cloover blocks or smart-meter data"
    },
    "existing_assets": {
      "current_heating": "Gas boiler (replaceable)",
      "existing_solar_kwp": 4,
      "wallbox": false,
      "battery": false
    },
    "budget_financial_profile": {
      "max_upfront_eur": 15000,
      "preferred_monthly_eur": 120,
      "income_bracket": "medium (eligible for income bonus)"
    },
    "conversation_history": {
      "notes": "Interested in solar + battery combo, concerned about payback and subsidies",
      "source": "Cloover chat logs"
    }
  },

  "enriched_open_data": {
    "solar_potential_pvgis": {
      "annual_kwh_per_kwp": 1450,
      "monthly_profile_kwh": { "jan":60, "feb":90, "mar":130, "apr":160, "may":180, "jun":190, "jul":195, "aug":180, "sep":150, "oct":110, "nov":70, "dec":50 },
      "optimal_config": "35° tilt, 0° south-facing, 14% system loss",
      "source_url": "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc",
      "api_endpoint": "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat=49.398&lon=8.672&peakpower=1&loss=14&angle=35&aspect=0&outputformat=json",
      "note": "Official EU JRC PVGIS v5.3 – real-time query with lat/lon"
    },

    "energy_prices_smard": {
      "current_day_ahead_eur_mwh": 93,
      "2025_annual_average_eur_mwh": 89.32,
      "trend_30d": "+13.8% YoY",
      "why_now": "Rising wholesale prices + negative-price hours increasing",
      "source_url": "https://www.smard.de/en/downloadcenter/download-market-data",
      "api_endpoint": "https://www.smard.de/en/downloadcenter/download-market-data (filter Day-ahead price, latest XLSX)",
      "note": "Bundesnetzagentur SMARD download center – latest day-ahead data"
    },

    "subsidies_kfw_bafa_beg": {
      "heat_pump": { "base_grant": "30%", "climate_speed_bonus": "20%", "income_bonus": "up to 30%", "max_grant_eur": 21000 },
      "solar_pv": { "grant": "BEG EM individual measures – active for rooftop", "note": "Small systems phasing adjustments 2026" },
      "application": "Via BAFA or KfW",
      "source_url": "https://www.bafa.de/DE/Energie/Effiziente_Gebaeude/effiziente_gebaeude_node.html",
      "api_endpoint": "https://www.energiewechsel.de/beg (official BEG guidelines)",
      "note": "BAFA / KfW BEG EM 2026 guidelines"
    },

    "regulations_geg_eeg_gmg": {
      "current_status": "GEG replaced by Building Modernisation Act (GMG)",
      "key_changes_2026": "65% RE rule abolished; new framework expected July 2026",
      "eeg_feed_in": "Tariffs attractive for new solar",
      "source_url": "https://www.bundeswirtschaftsministerium.de/Redaktion/EN/Dossier/enhancing-energy-efficiency-in-buildings.html",
      "api_endpoint": "https://www.bafa.de/DE/Energie/Effiziente_Gebaeude/effiziente_gebaeude_node.html (BEG + GMG updates)",
      "note": "Official BMWE / BAFA / Bundesnetzagentur announcements"
    },

    "nearby_installations_mastr": {
      "national_2025_additions_gw": 16.2,
      "local_trend_heidelberg_region": "High density – 3–6 new systems within 2 km",
      "balcony_solar_2025": "430,000 new units nationwide",
      "source_url": "https://www.marktstammdatenregister.de/MaStR/Datendownload",
      "api_endpoint": "open-mastr Python package (bulk XML daily dump) – https://www.marktstammdatenregister.de/MaStR/Datendownload",
      "story_hook": "3–5 neighbors in 69123 installed last 12 months"
    }
  },

  "quality_checks": {
    "completeness": 95,
    "freshness": "All prices/subsidies <48h old as of 2026-04-08",
    "sanity": "Cross-validated across official sources",
    "enrichment_method": "Postal-code averages + conservative defaults applied",
    "recommendation": "Use ONLY this JSON as context. Never invent numbers."
  },

  "ready_for_llm": {
    "instruction": "You are SolarSage Coach. Use ONLY the data above (including exact source_url). Generate 3-pillar output. Cite sources and quality score."
  }
}
```
