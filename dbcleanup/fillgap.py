"""
Cross-record fill: merge a cluster of duplicate rows into one golden
record, letting a value present on one duplicate fill a gap on another.

This is the free enrichment step -- no external API, no cost, just making
use of data the database already has but has scattered across duplicate
rows. It runs before (and independently of) any paid enrichment provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .normalize import normalize_name
from .parser import Contact

FIELDS_TO_MERGE = [
    "email", "phone", "secondary_phone", "address", "city", "state", "zip",
    "contact_type",
]


@dataclass
class MergedContact:
    row_id: int  # id of the "primary" surviving row
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    secondary_phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    contact_type: str = ""
    last_contacted: str = ""
    merged_from: list[int] = field(default_factory=list)
    filled_fields: list[str] = field(default_factory=list)  # was empty, now filled
    conflicts: dict[str, list[str]] = field(default_factory=dict)  # discarded alt values
    provider_filled_fields: list[str] = field(default_factory=list)  # filled by paid API
    needs_manual_research: list[str] = field(default_factory=list)  # still empty after all steps

    def as_output_row(self) -> dict:
        return {
            "First Name": self.first_name,
            "Last Name": self.last_name,
            "Email": self.email,
            "Phone": self.phone,
            "Secondary Phone": self.secondary_phone,
            "Address": self.address,
            "City": self.city,
            "State": self.state,
            "Zip": self.zip,
            "Contact Type": self.contact_type,
            "Last Contacted": self.last_contacted,
            "Merged From Rows": ", ".join(str(r) for r in self.merged_from),
            "Fields Filled From Duplicate": ", ".join(self.filled_fields),
            "Fields Filled By Provider": ", ".join(self.provider_filled_fields),
            "Needs Manual Research": ", ".join(self.needs_manual_research),
        }


def _parse_date(value: str):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _most_recent(records: list[Contact]) -> Contact:
    dated = [(r, _parse_date(r.last_contacted)) for r in records]
    dated_known = [d for d in dated if d[1] is not None]
    if dated_known:
        return max(dated_known, key=lambda d: d[1])[0]
    return records[0]


def merge_cluster(row_ids: list[int], by_id: dict[int, Contact]) -> MergedContact:
    records = [by_id[r] for r in row_ids]
    primary = _most_recent(records)

    # Fuller name wins (handles "Jenn" vs "Jennifer"); ties keep primary's.
    name_candidates = sorted(
        records, key=lambda r: len(r.full_name()), reverse=True
    )
    first_name = normalize_name(name_candidates[0].first_name or primary.first_name)
    last_name = normalize_name(name_candidates[0].last_name or primary.last_name)

    merged = MergedContact(
        row_id=primary.row_id,
        first_name=first_name,
        last_name=last_name,
        last_contacted=primary.last_contacted,
        merged_from=sorted(row_ids),
    )

    for fname in FIELDS_TO_MERGE:
        values_by_row = {r.row_id: (getattr(r, fname) or "").strip() for r in records}
        non_empty = {rid: v for rid, v in values_by_row.items() if v}
        distinct_values = sorted(set(non_empty.values()))

        was_empty_on_primary = not values_by_row.get(primary.row_id)

        if not distinct_values:
            setattr(merged, fname, "")
        elif len(distinct_values) == 1:
            setattr(merged, fname, distinct_values[0])
            if was_empty_on_primary:
                merged.filled_fields.append(fname)
        else:
            # Real conflict (e.g. two different emails) -- take the most
            # recently-contacted record's value, keep the rest visible in
            # the report rather than silently discarding them.
            recent_with_field = [r for r in records if values_by_row.get(r.row_id)]
            winner = _most_recent(recent_with_field)
            chosen = values_by_row[winner.row_id]
            setattr(merged, fname, chosen)
            if was_empty_on_primary:
                merged.filled_fields.append(fname)
            merged.conflicts[fname] = [v for v in distinct_values if v != chosen]

    return merged


def apply_fillgap(
    contacts: list[Contact], clusters: list[list[int]]
) -> list[MergedContact]:
    by_id = {c.row_id: c for c in contacts}
    clustered_ids = {rid for cluster in clusters for rid in cluster}

    results: list[MergedContact] = [
        merge_cluster(cluster, by_id) for cluster in clusters
    ]

    for c in contacts:
        if c.row_id not in clustered_ids:
            results.append(
                MergedContact(
                    row_id=c.row_id,
                    first_name=normalize_name(c.first_name),
                    last_name=normalize_name(c.last_name),
                    email=c.email,
                    phone=c.phone,
                    secondary_phone=c.secondary_phone,
                    address=c.address,
                    city=c.city,
                    state=c.state,
                    zip=c.zip,
                    contact_type=c.contact_type,
                    last_contacted=c.last_contacted,
                    merged_from=[c.row_id],
                )
            )

    return results
