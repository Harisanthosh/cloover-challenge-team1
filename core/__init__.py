"""Core package for SolarSage Coach."""

from .data_enricher import DataEnricher, EnrichmentResult, QualityReport
from .kb_manager import KBManager
from .sales_coach import SalesCoach

__all__ = [
    "DataEnricher",
    "EnrichmentResult",
    "QualityReport",
    "KBManager",
    "SalesCoach",
]
