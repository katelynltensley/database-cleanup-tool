from dbcleanup.normalize import (
    name_match_key,
    normalize_address,
    normalize_email,
    normalize_phone,
    normalize_zip,
)


def test_phone_formats_collapse_to_same_e164():
    variants = ["(561) 555-0142", "561-555-0142", "561.555.0142", "5615550142"]
    normalized = {normalize_phone(v) for v in variants}
    assert normalized == {"+15615550142"}


def test_invalid_phone_returns_empty():
    assert normalize_phone("not a phone") == ""
    assert normalize_phone("123") == ""


def test_email_lowercased_and_trimmed():
    assert normalize_email("  Jen.Alvarez@Gmail.com  ") == "jen.alvarez@gmail.com"


def test_invalid_email_returns_empty():
    assert normalize_email("not-an-email") == ""


def test_nickname_resolution_is_per_word():
    assert name_match_key("Debbie Simmons") == name_match_key("Deborah Simmons")
    assert name_match_key("Tom Bradford") == name_match_key("Thomas Bradford")


def test_address_abbreviation_normalization():
    a = normalize_address("412 Ocean Avenue")
    b = normalize_address("412 Ocean Ave")
    assert a == b == "412 ocean ave"


def test_zip_strips_plus4():
    assert normalize_zip("33410-1234") == "33410"
