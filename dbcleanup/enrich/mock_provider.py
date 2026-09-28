"""
Fake, obviously-fake enrichment provider for demos and tests.

This exists so the tool is fully runnable and demoable -- including the
"paid lookup" stage of the pipeline -- without an API key or any cost.
Every value it returns uses reserved fictional ranges (555-01xx phone
numbers, an .invalid email domain) and is flagged is_simulated=True so
there is no way simulated data accidentally ends up looking like a real
lookup result in the output or report.
"""

from __future__ import annotations

import hashlib

from ..fillgap import MergedContact
from ..normalize import display_phone
from .base import EnrichmentProvider, EnrichmentResult


class MockProvider(EnrichmentProvider):
    name = "mock"

    def lookup(self, contact: MergedContact) -> EnrichmentResult:
        # Deterministic "hash of the name" fake phone in the block reserved
        # by NANPA for fictional use (555-0100 to 555-0199), so it can never
        # collide with a real number.
        digest = hashlib.sha256(
            f"{contact.first_name}{contact.last_name}{contact.zip}".encode()
        ).hexdigest()
        fake_line = 100 + (int(digest[:6], 16) % 100)
        fake_phone = display_phone(f"+1561555{fake_line:04d}"[:12])

        fake_email = (
            f"{contact.first_name}.{contact.last_name}"
            f"@simulated-lookup.invalid"
        ).lower().replace(" ", "")

        return EnrichmentResult(
            row_id=contact.row_id,
            phone_found=fake_phone if not contact.phone else "",
            email_found=fake_email if not contact.email else "",
            source="mock",
            confidence="n/a (simulated)",
            is_simulated=True,
            notes="SIMULATED DEMO DATA -- not a real lookup result.",
        )
