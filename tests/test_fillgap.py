from dbcleanup.fillgap import apply_fillgap, merge_cluster
from dbcleanup.parser import Contact


def make(row_id, **kwargs):
    defaults = dict(
        first_name="", last_name="", email="", phone="", secondary_phone="",
        address="", city="", state="", zip="", contact_type="", last_contacted="",
    )
    defaults.update(kwargs)
    return Contact(row_id=row_id, **defaults)


def test_gap_filled_from_duplicate_row():
    a = make(0, first_name="Priya", last_name="Patel", email="")
    b = make(1, first_name="Priya", last_name="Patel", email="priya.patel@gmail.com")
    merged = merge_cluster([0, 1], {0: a, 1: b})
    assert merged.email == "priya.patel@gmail.com"
    assert "email" in merged.filled_fields


def test_fuller_name_variant_wins():
    a = make(0, first_name="Jenn", last_name="Alvarez", last_contacted="2026-01-14")
    b = make(1, first_name="Jennifer", last_name="Alvarez", last_contacted="2026-06-02")
    merged = merge_cluster([0, 1], {0: a, 1: b})
    assert merged.first_name == "Jennifer"


def test_conflicting_values_keep_most_recently_contacted_and_log_the_rest():
    a = make(0, first_name="Michael", last_name="Chen", phone="772-555-0198", last_contacted="2025-11-20")
    b = make(1, first_name="Michael", last_name="Chen", phone="772-555-0199", last_contacted="2026-03-11")
    merged = merge_cluster([0, 1], {0: a, 1: b})
    assert merged.phone == "772-555-0199"
    assert merged.conflicts["phone"] == ["772-555-0198"]


def test_singletons_pass_through_unmerged():
    contacts = [make(0, first_name="Sarah", last_name="Whitfield")]
    results = apply_fillgap(contacts, clusters=[])
    assert len(results) == 1
    assert results[0].merged_from == [0]
    assert results[0].filled_fields == []
