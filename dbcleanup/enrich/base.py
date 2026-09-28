"""
Pluggable enrichment provider interface.

Cross-record fill (fillgap.py) is free and always runs. This layer is the
OPTIONAL second stage: for whatever's still missing after the free pass,
look it up through a real paid data source. It's built as a swappable
interface on purpose -- the free tier ships and demos with zero external
dependencies (provider: none, or provider: mock), and wiring in a live
provider like Forewarn later is a config change plus filling in one class,
not a rewrite of the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..fillgap import MergedContact


@dataclass
class EnrichmentResult:
    row_id: int
    phone_found: str = ""
    email_found: str = ""
    source: str = ""
    confidence: str = ""  # e.g. "high" | "medium" | "low"
    is_simulated: bool = False
    notes: str = ""
    error: str = ""


class EnrichmentProvider(ABC):
    """Looks up a missing phone/email for one contact at a time.

    A provider only gets called for contacts that STILL have a gap after
    free cross-record fill, and only up to the run's configured budget --
    see pipeline.py for the cap enforcement.
    """

    name: str = "base"

    @abstractmethod
    def lookup(self, contact: MergedContact) -> EnrichmentResult:
        raise NotImplementedError


def get_provider(name: str, config: dict) -> EnrichmentProvider | None:
    name = (name or "none").lower()
    if name == "none":
        return None
    if name == "mock":
        from .mock_provider import MockProvider

        return MockProvider()
    if name == "forewarn":
        from .forewarn_provider import ForewarnProvider

        return ForewarnProvider(config.get("forewarn", {}))
    raise ValueError(f"Unknown enrichment provider: {name!r}")
