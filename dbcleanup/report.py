"""
Data-quality report: what changed, where each value came from, and what
is still missing. This is the artifact that makes the tool's output
trustworthy -- an agent (or a hiring manager reading the case study)
should be able to see exactly why a record looks the way it does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .dedupe import MatchDecision
from .enrich.base import EnrichmentResult
from .fillgap import MergedContact
from .parser import Contact


@dataclass
class RunReport:
    total_input_rows: int = 0
    duplicate_clusters: int = 0
    rows_merged_away: int = 0
    final_contact_count: int = 0

    llm_calls_made: int = 0
    llm_decisions_matched: int = 0
    fallback_rule_decisions: int = 0
    fallback_rule_matched: int = 0

    phone_present_before_pct: float = 0.0
    email_present_before_pct: float = 0.0
    phone_present_after_pct: float = 0.0
    email_present_after_pct: float = 0.0

    fields_filled_cross_record: dict = field(default_factory=dict)  # field -> count
    fields_filled_by_provider: dict = field(default_factory=dict)   # field -> count
    provider_used: str = "none"
    provider_lookups_attempted: int = 0
    provider_lookups_succeeded: int = 0
    provider_errors: int = 0

    still_missing_phone: int = 0
    still_missing_email: int = 0

    conflicts_found: list = field(default_factory=list)  # [{row, field, kept, discarded}]

    def to_dict(self) -> dict:
        return self.__dict__

    def to_markdown(self) -> str:
        lines = []
        lines.append("# Database Cleanup — Data Quality Report\n")
        lines.append("## Summary\n")
        lines.append(f"- Input rows: **{self.total_input_rows}**")
        lines.append(
            f"- Duplicate clusters found: **{self.duplicate_clusters}** "
            f"({self.rows_merged_away} rows merged away)"
        )
        lines.append(f"- Final unique contacts: **{self.final_contact_count}**\n")

        lines.append("## Matching\n")
        lines.append(
            f"- Ambiguous pairs resolved by Claude: **{self.llm_calls_made}** "
            f"({self.llm_decisions_matched} judged the same person)"
        )
        lines.append(
            f"- Ambiguous pairs resolved by fallback rule (Claude off/over "
            f"budget): **{self.fallback_rule_decisions}** "
            f"({self.fallback_rule_matched} judged the same person)\n"
        )

        lines.append("## Completeness\n")
        lines.append("| Field | Before | After |")
        lines.append("|---|---|---|")
        lines.append(
            f"| Phone | {self.phone_present_before_pct:.0f}% | "
            f"{self.phone_present_after_pct:.0f}% |"
        )
        lines.append(
            f"| Email | {self.email_present_before_pct:.0f}% | "
            f"{self.email_present_after_pct:.0f}% |\n"
        )

        lines.append("## Where filled values came from\n")
        for f, count in self.fields_filled_cross_record.items():
            lines.append(f"- {f}: **{count}** filled free, from a duplicate row")
        if self.provider_used != "none":
            lines.append(
                f"\nPaid enrichment provider: **{self.provider_used}** — "
                f"{self.provider_lookups_attempted} lookups attempted, "
                f"{self.provider_lookups_succeeded} succeeded, "
                f"{self.provider_errors} errored"
            )
            for f, count in self.fields_filled_by_provider.items():
                lines.append(f"- {f}: **{count}** filled by {self.provider_used}")
        else:
            lines.append(
                "\nPaid enrichment provider: **none** (free cross-record fill only)"
            )

        lines.append("\n## Still missing after this run\n")
        lines.append(f"- Contacts still missing a phone number: **{self.still_missing_phone}**")
        lines.append(f"- Contacts still missing an email: **{self.still_missing_email}**")

        if self.conflicts_found:
            lines.append("\n## Conflicts resolved (kept most-recently-contacted value)\n")
            lines.append("| Row | Field | Kept | Other value(s) seen |")
            lines.append("|---|---|---|---|")
            for c in self.conflicts_found:
                lines.append(
                    f"| {c['row']} | {c['field']} | {c['kept']} | "
                    f"{', '.join(c['discarded'])} |"
                )

        return "\n".join(lines) + "\n"


def _pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def build_report(
    original_contacts: list[Contact],
    clusters: list[list[int]],
    decisions: list[MatchDecision],
    merged_before_enrichment: list[MergedContact],
    merged_after_enrichment: list[MergedContact],
    enrichment_results: list[EnrichmentResult],
    provider_name: str,
) -> RunReport:
    r = RunReport()
    r.total_input_rows = len(original_contacts)
    r.duplicate_clusters = len(clusters)
    r.rows_merged_away = sum(len(c) - 1 for c in clusters)
    r.final_contact_count = len(merged_after_enrichment)
    r.provider_used = provider_name

    for d in decisions:
        if d.method == "llm":
            r.llm_calls_made += 1
            r.llm_decisions_matched += int(d.is_match)
        elif d.method == "fallback_rule":
            r.fallback_rule_decisions += 1
            r.fallback_rule_matched += int(d.is_match)

    r.phone_present_before_pct = _pct(
        sum(1 for c in original_contacts if c.phone or c.secondary_phone),
        len(original_contacts),
    )
    r.email_present_before_pct = _pct(
        sum(1 for c in original_contacts if c.email), len(original_contacts)
    )

    for m in merged_before_enrichment:
        for f in m.filled_fields:
            if f in ("phone", "secondary_phone"):
                r.fields_filled_cross_record["phone"] = (
                    r.fields_filled_cross_record.get("phone", 0) + 1
                )
            elif f == "email":
                r.fields_filled_cross_record["email"] = (
                    r.fields_filled_cross_record.get("email", 0) + 1
                )
        for field_name, discarded in m.conflicts.items():
            kept = getattr(m, field_name)
            r.conflicts_found.append(
                {
                    "row": m.row_id,
                    "field": field_name,
                    "kept": kept,
                    "discarded": discarded,
                }
            )

    for res in enrichment_results:
        r.provider_lookups_attempted += 1
        if res.error:
            r.provider_errors += 1
            continue
        if res.phone_found or res.email_found:
            r.provider_lookups_succeeded += 1
        if res.phone_found:
            r.fields_filled_by_provider["phone"] = (
                r.fields_filled_by_provider.get("phone", 0) + 1
            )
        if res.email_found:
            r.fields_filled_by_provider["email"] = (
                r.fields_filled_by_provider.get("email", 0) + 1
            )

    r.phone_present_after_pct = _pct(
        sum(1 for m in merged_after_enrichment if m.phone),
        len(merged_after_enrichment),
    )
    r.email_present_after_pct = _pct(
        sum(1 for m in merged_after_enrichment if m.email),
        len(merged_after_enrichment),
    )
    r.still_missing_phone = sum(1 for m in merged_after_enrichment if not m.phone)
    r.still_missing_email = sum(1 for m in merged_after_enrichment if not m.email)

    return r


def write_report(report: RunReport, markdown_path: str | Path, json_path: str | Path) -> None:
    Path(markdown_path).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_path).write_text(report.to_markdown())
    Path(json_path).write_text(json.dumps(report.to_dict(), indent=2))
