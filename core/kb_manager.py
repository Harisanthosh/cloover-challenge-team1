from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile, ZIP_DEFLATED

from pydantic import BaseModel, Field

from .data_enricher import EnrichmentResult, QualityReport


class KBSessionRecord(BaseModel):
    session_id: str
    timestamp: str
    postal_code: str
    product_interest: str
    quality_score: float
    markdown_path: str
    json_path: str


class KBManager:
    def __init__(self, base_dir: str = "knowledge_base"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.base_dir / "dynamic_enrichments.json"
        self.regulations_path = self.base_dir / "regulations_knowledge.md"
        self.index_path = self.base_dir / "sessions_index.json"
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not self.json_path.exists():
            self.json_path.write_text(json.dumps({"sessions": []}, indent=2), encoding="utf-8")
        if not self.regulations_path.exists():
            self.regulations_path.write_text(
                "# Regulations Knowledge\n\n"
                "This file stores lightweight reference notes for SolarSage Coach.\n\n"
                "- Always confirm local subsidy and permitting details before quoting\n"
                "- Use quality-checked data only\n"
                "- Prefer conservative savings assumptions\n",
                encoding="utf-8",
            )
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"records": []}, indent=2), encoding="utf-8")

    def load_latest(self) -> Dict[str, Any]:
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        records = data.get("sessions", [])
        latest = records[-1] if records else None
        regulations = self.regulations_path.read_text(encoding="utf-8")
        return {"latest": latest, "records": records, "regulations": regulations}

    def save_enrichment(self, result: EnrichmentResult, extra_notes: Optional[str] = None) -> KBSessionRecord:
        base_session_id = datetime.now(timezone.utc).strftime("session_%Y%m%d_%H%M%S")
        session_id = base_session_id
        counter = 1
        md_path = self.base_dir / f"{session_id}.md"
        json_path = self.base_dir / f"{session_id}.json"
        while md_path.exists() or json_path.exists():
            session_id = f"{base_session_id}_{counter:02d}"
            md_path = self.base_dir / f"{session_id}.md"
            json_path = self.base_dir / f"{session_id}.json"
            counter += 1

        payload = result.model_dump()
        payload["quality_report"] = result.quality_report.model_dump()
        payload["extra_notes"] = extra_notes or ""

        md_path.write_text(self._render_markdown(payload), encoding="utf-8")
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        record = KBSessionRecord(
            session_id=session_id,
            timestamp=result.fetched_at,
            postal_code=result.postal_code,
            product_interest=result.product_interest,
            quality_score=result.quality_report.overall_score,
            markdown_path=str(md_path),
            json_path=str(json_path),
        )

        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        sessions = data.setdefault("sessions", [])
        sessions.append(record.model_dump())
        self.json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        index_records = index.setdefault("records", [])
        index_records.append(record.model_dump())
        self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

        return record

    def load_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        return list(reversed(data.get("sessions", [])))[:limit]

    def read_session_markdown(self, session_id: str) -> str:
        path = self.base_dir / f"{session_id}.md"
        return path.read_text(encoding="utf-8")

    def read_session_json(self, session_id: str) -> Dict[str, Any]:
        path = self.base_dir / f"{session_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def create_zip_bundle(self) -> bytes:
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for path in sorted(self.base_dir.glob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.name)
        buffer.seek(0)
        return buffer.read()

    def render_quality_badge(self, score: float) -> str:
        if score >= 90:
            return "🟢"
        if score >= 75:
            return "🟡"
        return "🔴"

    def _render_markdown(self, payload: Dict[str, Any]) -> str:
        qr = payload.get("quality_report", {})
        enriched = payload.get("enriched_data", {})
        lines = [
            "# SolarSage Coach Session",
            "",
            f"- Timestamp: {payload.get('fetched_at')}",
            f"- Postal code: {payload.get('postal_code')}",
            f"- Product interest: {payload.get('product_interest')}",
            f"- Quality score: {qr.get('overall_score')}",
            "",
            "## Quality Report",
            f"- Completeness: {qr.get('completeness_score')}",
            f"- Freshness: {qr.get('freshness_score')}",
            f"- Sanity: {qr.get('sanity_score')}",
            f"- Consistency: {qr.get('consistency_score')}",
            "",
            "## Enriched Data",
            "```json",
            json.dumps(enriched, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Source Data",
            "```json",
            json.dumps(payload.get("source_data", {}), indent=2, ensure_ascii=False),
            "```",
        ]
        if payload.get("extra_notes"):
            lines.extend(["", "## Extra Notes", payload["extra_notes"]])
        return "\n".join(lines)


