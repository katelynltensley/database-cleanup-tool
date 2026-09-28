"""
Forewarn provider stub -- NOT wired to a live endpoint yet.

Forewarn (forewarn.com) lists "API and custom integrations available" on
its product page, but as of this build (Sept 2026) no technical API docs
-- auth method, endpoints, request/response schema -- are publicly
published. Getting this working for real requires:

  1. Contacting your Forewarn account rep (or MLS/association contact) for
     API credentials and the actual integration spec.
  2. Confirming with them that automated, bulk lookups for contact-list
     enrichment is a permitted use of your subscription. Forewarn is
     positioned (and likely governed) as an agent-safety / identity-
     verification tool -- it returns criminal and financial records, which
     sit in FCRA-adjacent territory. That's a different permissible-use
     case than a one-off safety check before meeting someone in person,
     and it's worth having that answer in writing before automating it.
  3. Updating the request/response handling below to match their real API
     once you have the docs -- everything here is a best-guess placeholder
     shaped like a typical REST lookup API, not a confirmed contract.

Also note: Forewarn's public materials describe phone and name search
returning identity, phone numbers, and address history -- they do NOT
mention email addresses. Treat this provider as a phone-gap-filler only;
keep relying on cross-record fill (or a different source) for email.

Until the above is done, this provider raises NotImplementedError rather
than silently returning fabricated data or making a request to a guessed
endpoint that could fail in some unexpected way against a real account.
"""

from __future__ import annotations

import os

from ..fillgap import MergedContact
from .base import EnrichmentProvider, EnrichmentResult


class ForewarnProvider(EnrichmentProvider):
    name = "forewarn"

    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "https://api.forewarn.com")
        self.api_key_env = config.get("api_key_env", "FOREWARN_API_KEY")
        self.api_key = os.environ.get(self.api_key_env, "")

    def lookup(self, contact: MergedContact) -> EnrichmentResult:
        if not self.api_key:
            return EnrichmentResult(
                row_id=contact.row_id,
                source="forewarn",
                error=(
                    f"{self.api_key_env} is not set, and the request/response "
                    "shape below is still a placeholder -- see the module "
                    "docstring for what's needed before this can run live."
                ),
            )

        # --- Placeholder only -- replace once you have real API docs. ---
        # import requests
        # response = requests.post(
        #     f"{self.base_url}/v1/search/name",
        #     headers={"Authorization": f"Bearer {self.api_key}"},
        #     json={
        #         "first_name": contact.first_name,
        #         "last_name": contact.last_name,
        #         "address": contact.address,
        #         "city": contact.city,
        #         "state": contact.state,
        #         "zip": contact.zip,
        #     },
        #     timeout=10,
        # )
        # response.raise_for_status()
        # data = response.json()
        # phone = (data.get("results") or [{}])[0].get("phone", "")
        # return EnrichmentResult(
        #     row_id=contact.row_id,
        #     phone_found=phone,
        #     source="forewarn",
        #     confidence="high" if phone else "none",
        # )

        raise NotImplementedError(
            "ForewarnProvider needs a real request/response implementation "
            "once you have API docs and credentials from Forewarn -- see "
            "the module docstring."
        )
