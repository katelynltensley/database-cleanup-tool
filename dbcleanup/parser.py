"""
Flexible loader for messy CRM contact exports.

Agent databases come out of KW Command, Follow Up Boss, BoomTown, or a
hand-built spreadsheet, and no two brokerages name their columns the same
way. Rather than hardcoding one schema, this module maps a wide set of
known column-name variants onto a canonical Contact schema, and falls back
to fuzzy header matching for anything it doesn't recognize by exact name.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process

# Canonical field -> known column-name variants seen across common CRM
# exports (KW Command, Follow Up Boss, BoomTown, generic spreadsheets).
COLUMN_ALIASES: dict[str, list[str]] = {
    "first_name": ["first name", "firstname", "first", "fname"],
    "last_name": ["last name", "lastname", "last", "lname", "surname"],
    "email": [
        "email address", "email", "e-mail", "primary email", "email 1",
    ],
    "phone": [
        "cell phone", "mobile phone", "mobile", "cell", "phone", "phone number",
        "primary phone", "phone 1",
    ],
    "secondary_phone": [
        "home phone", "work phone", "office phone", "phone 2", "secondary phone",
        "other phone",
    ],
    "address": [
        "mailing address", "address", "street address", "address 1", "street",
        "address line 1",
    ],
    "city": ["city"],
    "state": ["state", "st"],
    "zip": ["zip", "zip code", "postal code", "zipcode"],
    "contact_type": [
        "contact type", "type", "tags", "category", "lead type", "source",
    ],
    "last_contacted": [
        "last contacted", "last contact date", "last activity", "last touch",
    ],
}

CANONICAL_FIELDS = list(COLUMN_ALIASES.keys())

FUZZY_HEADER_THRESHOLD = 80


@dataclass
class Contact:
    """One canonical contact record, carrying its original row for traceability."""

    row_id: int
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
    raw: dict = field(default_factory=dict, repr=False)

    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def as_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "raw"}
        return d


def _build_header_map(columns: list[str]) -> dict[str, str]:
    """Map each source column name to a canonical field name, or drop it."""
    header_map: dict[str, str] = {}
    normalized_lookup = {c.strip().lower(): c for c in columns}

    for canonical, aliases in COLUMN_ALIASES.items():
        matched = None
        for alias in aliases:
            if alias in normalized_lookup:
                matched = normalized_lookup[alias]
                break
        if matched is None:
            # Fuzzy fallback: closest header name to any known alias.
            candidates = list(normalized_lookup.keys())
            if candidates:
                best = process.extractOne(
                    canonical.replace("_", " "), candidates, scorer=fuzz.token_sort_ratio
                )
                if best and best[1] >= FUZZY_HEADER_THRESHOLD:
                    matched = normalized_lookup[best[0]]
        if matched is not None:
            header_map[matched] = canonical

    return header_map


def _read_table(path: Path, header_row: int = 0) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str, header=header_row)
    return pd.read_csv(
        path, dtype=str, keep_default_na=False, na_filter=False, header=header_row
    )


def _multi_column_values(columns: list[str], keyword: str) -> list[str]:
    """All column names containing `keyword`, left-to-right as they appear in
    the source file. CRM exports that break phone/email into several typed
    columns (e.g. KW Command's "Primary cell phone", "Primary work phone",
    "Others mobile phone", ...) consistently list the most-likely-current
    numbers/addresses before older/secondary ones, so column order alone is
    a reasonable priority ranking without hardcoding every CRM's field names.
    """
    return [c for c in columns if keyword in c.strip().lower()]


def load_contacts(path: str | Path) -> list[Contact]:
    """Load a CSV or Excel export into canonical Contact records."""
    path = Path(path)
    df = _read_table(path, header_row=0)
    header_map = _build_header_map(list(df.columns))

    # Some CRM exports (KW Command among them) ship a two-row header: a row
    # of section group labels ("PRIMARY ADDRESS", "Key Dates", mostly blank)
    # followed by the actual field names. If the first row didn't give us a
    # name field, assume it was a group-label row and re-read using the
    # second row as the real header instead.
    if "first_name" not in header_map.values() and "last_name" not in header_map.values():
        try:
            retry_df = _read_table(path, header_row=1)
        except (pd.errors.ParserError, IndexError):
            retry_df = None
        if retry_df is not None:
            retry_header_map = _build_header_map(list(retry_df.columns))
            if (
                "first_name" in retry_header_map.values()
                or "last_name" in retry_header_map.values()
            ):
                df = retry_df
                header_map = retry_header_map

    columns = list(df.columns)
    phone_cols = _multi_column_values(columns, "phone")
    email_cols = _multi_column_values(columns, "email")

    contacts: list[Contact] = []
    for idx, row in df.iterrows():
        raw = row.to_dict()
        values = {canonical: "" for canonical in CANONICAL_FIELDS}
        for source_col, canonical in header_map.items():
            val = raw.get(source_col, "")
            values[canonical] = "" if pd.isna(val) else str(val).strip()

        # Override phone/email with the multi-column consolidation: several
        # differently-typed phone/email columns collapse into one primary
        # (+ one secondary phone), taking the first non-empty, left-to-right.
        if phone_cols:
            found: list[str] = []
            for col in phone_cols:
                val = raw.get(col, "")
                val = "" if pd.isna(val) else str(val).strip()
                if val and val not in found:
                    found.append(val)
            values["phone"] = found[0] if found else ""
            values["secondary_phone"] = found[1] if len(found) > 1 else values.get(
                "secondary_phone", ""
            )
        if email_cols:
            for col in email_cols:
                val = raw.get(col, "")
                val = "" if pd.isna(val) else str(val).strip()
                if val:
                    values["email"] = val
                    break
            else:
                values["email"] = ""

        contacts.append(Contact(row_id=idx, raw=raw, **values))

    return contacts


def contacts_to_dataframe(contacts: list[Contact]) -> pd.DataFrame:
    return pd.DataFrame([c.as_dict() for c in contacts])
