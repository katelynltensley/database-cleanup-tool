"""
Deterministic normalization for names, phones, emails, and addresses.

This is the layer that does NOT need judgment -- formatting is either
right or it isn't -- so it's kept as plain rules, no LLM calls. Clean,
consistent values here are what make the matching engine's fuzzy
comparisons actually work.
"""

from __future__ import annotations

import re

import phonenumbers

# Common nicknames -> given name, used only to help matching (never used to
# silently overwrite what's in the database).
NICKNAME_MAP = {
    "jenn": "jennifer", "jen": "jennifer", "dave": "david", "tom": "thomas",
    "tommy": "thomas", "mike": "michael", "mikey": "michael", "bob": "robert",
    "bobby": "robert", "rob": "robert", "bill": "william", "will": "william",
    "liz": "elizabeth", "beth": "elizabeth", "jim": "james", "jimmy": "james",
    "rick": "richard", "dick": "richard", "sue": "susan", "susie": "susan",
    "greg": "gregory", "chris": "christopher", "steve": "steven",
    "nick": "nicholas", "matt": "matthew", "sam": "samuel", "alex": "alexander",
    "andy": "andrew", "ken": "kenneth", "ron": "ronald", "don": "donald",
    "vic": "victor", "gene": "eugene", "pat": "patricia",
    "deb": "deborah", "debbie": "deborah", "debby": "deborah",
}

STREET_ABBREVIATIONS = {
    "avenue": "ave", "boulevard": "blvd", "street": "st", "drive": "dr",
    "highway": "hwy", "road": "rd", "lane": "ln", "court": "ct",
    "circle": "cir", "place": "pl", "terrace": "ter", "parkway": "pkwy",
    "trail": "trl", "square": "sq",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value.title()


def name_match_key(value: str) -> str:
    """Lowercased, nickname-resolved form of a name, for matching only.

    Nickname substitution runs per word (so "Debbie Simmons" resolves to
    "deborah simmons"), not on the joined string -- the map only has
    single-word entries.
    """
    v = re.sub(r"[^a-zA-Z ]", "", (value or "")).strip().lower()
    v = re.sub(r"\s+", " ", v)
    words = [NICKNAME_MAP.get(w, w) for w in v.split(" ")]
    return " ".join(words)


def normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    return value if EMAIL_RE.match(value) else ""


def normalize_phone(value: str, region: str = "US") -> str:
    """Return E.164 format (+15615550142) or '' if it can't be parsed."""
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parsed = phonenumbers.parse(value, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
    except phonenumbers.NumberParseException:
        pass
    return ""


def display_phone(e164_value: str) -> str:
    """Human-friendly (561) 555-0142 format for report/output display."""
    if not e164_value:
        return ""
    try:
        parsed = phonenumbers.parse(e164_value, None)
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.NATIONAL
        )
    except phonenumbers.NumberParseException:
        return e164_value


def normalize_address(value: str) -> str:
    value = re.sub(r"[.,]", "", (value or "")).strip().lower()
    value = re.sub(r"\s+", " ", value)
    words = value.split(" ")
    words = [STREET_ABBREVIATIONS.get(w, w) for w in words]
    return " ".join(words)


def normalize_zip(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[:5]
