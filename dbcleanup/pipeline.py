"""
End-to-end orchestration: load -> dedupe -> free cross-record fill ->
optional paid enrichment -> report + clean CSV. This is what the CLI
calls, and it's built to run unattended -- one call, no prompts, no
manual steps, so it can be scheduled (cron, a scheduled task runner) as
easily as run by hand.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd

from .dedupe import find_duplicate_clusters
from .enrich.base import get_provider
from .fillgap import MergedContact, apply_fillgap
from .parser import load_contacts
from .report import RunReport, build_report, write_report


def run_pipeline(input_path: str | Path, config: dict) -> tuple[list[MergedContact], RunReport]:
    contacts = load_contacts(input_path)

    matching_cfg = config.get("matching", {})
    llm_cfg = config.get("llm", {})
    clusters, decisions = find_duplicate_clusters(
        contacts,
        auto_merge_threshold=matching_cfg.get("auto_merge_threshold", 92),
        review_threshold=matching_cfg.get("review_threshold", 72),
        llm_enabled=llm_cfg.get("enabled", True),
        llm_model=llm_cfg.get("model", "claude-sonnet-4-5"),
        max_llm_calls=matching_cfg.get("max_claude_calls", 250),
    )

    merged_before = apply_fillgap(contacts, clusters)
    merged_after = copy.deepcopy(merged_before)

    enrich_cfg = config.get("enrichment", {})
    provider_name = enrich_cfg.get("provider", "none")
    provider = get_provider(provider_name, enrich_cfg)

    enrichment_results = []
    if provider is not None:
        max_lookups = enrich_cfg.get("max_lookups_per_run", 200)
        candidates = [m for m in merged_after if not m.phone or not m.email]
        for m in candidates[:max_lookups]:
            result = provider.lookup(m)
            enrichment_results.append(result)
            if result.error:
                continue
            if result.phone_found and not m.phone:
                m.phone = result.phone_found
                m.provider_filled_fields.append("phone")
            if result.email_found and not m.email:
                m.email = result.email_found
                m.provider_filled_fields.append("email")

    for m in merged_after:
        if not m.phone:
            m.needs_manual_research.append("phone")
        if not m.email:
            m.needs_manual_research.append("email")

    report = build_report(
        original_contacts=contacts,
        clusters=clusters,
        decisions=decisions,
        merged_before_enrichment=merged_before,
        merged_after_enrichment=merged_after,
        enrichment_results=enrichment_results,
        provider_name=provider_name,
    )

    output_cfg = config.get("output", {})
    clean_csv_path = output_cfg.get("clean_csv", "output/cleaned_contacts.csv")
    report_md_path = output_cfg.get("report", "output/data_quality_report.md")
    report_json_path = output_cfg.get("report_json", "output/data_quality_report.json")

    df = pd.DataFrame([m.as_output_row() for m in merged_after])
    Path(clean_csv_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(clean_csv_path, index=False)
    write_report(report, report_md_path, report_json_path)

    return merged_after, report
