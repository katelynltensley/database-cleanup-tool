from dbcleanup.enrich.mock_provider import MockProvider
from dbcleanup.enrich.forewarn_provider import ForewarnProvider
from dbcleanup.fillgap import MergedContact


def test_mock_provider_only_fills_gaps_and_flags_itself_as_simulated():
    contact = MergedContact(row_id=0, first_name="Sarah", last_name="Whitfield", zip="33469")
    result = MockProvider().lookup(contact)
    assert result.is_simulated is True
    assert result.phone_found  # was missing, mock fills it
    assert "simulated-lookup.invalid" in result.email_found


def test_mock_provider_never_overwrites_existing_values():
    contact = MergedContact(
        row_id=0, first_name="Sarah", last_name="Whitfield",
        phone="+15615550100", email="sarah@example.com",
    )
    result = MockProvider().lookup(contact)
    assert result.phone_found == ""
    assert result.email_found == ""


def test_forewarn_provider_fails_clearly_without_credentials(monkeypatch):
    monkeypatch.delenv("FOREWARN_API_KEY", raising=False)
    contact = MergedContact(row_id=0, first_name="Sarah", last_name="Whitfield")
    result = ForewarnProvider({}).lookup(contact)
    assert result.error
    assert not result.phone_found
