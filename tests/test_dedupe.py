from dbcleanup.dedupe import find_duplicate_clusters
from dbcleanup.parser import Contact


def make(row_id, **kwargs):
    defaults = dict(
        first_name="", last_name="", email="", phone="", secondary_phone="",
        address="", city="", state="", zip="", contact_type="", last_contacted="",
    )
    defaults.update(kwargs)
    return Contact(row_id=row_id, **defaults)


def test_exact_phone_match_auto_merges_even_with_different_formatting():
    contacts = [
        make(0, first_name="Jennifer", last_name="Alvarez", phone="(561) 555-0142"),
        make(1, first_name="Jenn", last_name="Alvarez", phone="561-555-0142"),
    ]
    clusters, decisions = find_duplicate_clusters(contacts, llm_enabled=False)
    assert clusters == [[0, 1]]
    assert any(d.method == "exact_contact" for d in decisions)


def test_unrelated_contacts_are_not_merged():
    contacts = [
        make(0, first_name="Sarah", last_name="Whitfield", address="1 Main St"),
        make(1, first_name="Victor", last_name="Alessi", address="2 Ocean Dr"),
    ]
    clusters, decisions = find_duplicate_clusters(contacts, llm_enabled=False)
    assert clusters == []


def test_ambiguous_pair_without_llm_uses_conservative_fallback():
    # Same nickname-resolved name, no corroborating address on either side --
    # squarely in the ambiguous band, and the fallback rule should decline
    # to merge on name alone. This is the exact case Claude is meant to help.
    contacts = [
        make(0, first_name="Deborah", last_name="Simmons", phone="561-555-0600"),
        make(1, first_name="Debbie", last_name="Simmons"),
    ]
    clusters, decisions = find_duplicate_clusters(contacts, llm_enabled=False)
    assert clusters == []
    fallback_decisions = [d for d in decisions if d.method == "fallback_rule"]
    assert len(fallback_decisions) == 1
    assert fallback_decisions[0].is_match is False


def test_llm_disabled_never_calls_anthropic(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Claude should not be called when llm_enabled=False")

    monkeypatch.setattr("dbcleanup.dedupe._llm_judge", boom)
    contacts = [
        make(0, first_name="Deborah", last_name="Simmons", phone="561-555-0600"),
        make(1, first_name="Debbie", last_name="Simmons"),
    ]
    find_duplicate_clusters(contacts, llm_enabled=False)  # should not raise


def test_llm_result_is_respected_when_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        "dbcleanup.dedupe._llm_judge",
        lambda a, b, model: (True, "same person, mocked for test"),
    )
    contacts = [
        make(0, first_name="Deborah", last_name="Simmons", phone="561-555-0600"),
        make(1, first_name="Debbie", last_name="Simmons"),
    ]
    clusters, decisions = find_duplicate_clusters(contacts, llm_enabled=True)
    assert clusters == [[0, 1]]
    assert any(d.method == "llm" and d.is_match for d in decisions)


def test_max_llm_calls_budget_is_respected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    calls = {"n": 0}

    def fake_judge(a, b, model):
        calls["n"] += 1
        return True, "mocked"

    monkeypatch.setattr("dbcleanup.dedupe._llm_judge", fake_judge)
    contacts = [
        make(0, first_name="Deborah", last_name="Simmons"),
        make(1, first_name="Debbie", last_name="Simmons"),
        make(2, first_name="Katherine", last_name="Reyes"),
        make(3, first_name="Kathy", last_name="Reyes"),
    ]
    find_duplicate_clusters(contacts, llm_enabled=True, max_llm_calls=1)
    assert calls["n"] == 1
