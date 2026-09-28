from pathlib import Path

from dbcleanup.pipeline import run_pipeline

SAMPLE = Path(__file__).parent.parent / "sample_data" / "kw_command_sample_export.csv"


def base_config(tmp_path, provider="none", llm_enabled=False):
    return {
        "matching": {"auto_merge_threshold": 92, "review_threshold": 72, "max_claude_calls": 50},
        "llm": {"enabled": llm_enabled, "model": "claude-sonnet-4-5"},
        "enrichment": {"provider": provider, "max_lookups_per_run": 200, "forewarn": {}},
        "output": {
            "clean_csv": str(tmp_path / "cleaned.csv"),
            "report": str(tmp_path / "report.md"),
            "report_json": str(tmp_path / "report.json"),
        },
    }


def test_pipeline_runs_end_to_end_with_no_external_dependencies(tmp_path):
    merged, report = run_pipeline(SAMPLE, base_config(tmp_path, provider="none"))
    assert report.total_input_rows == 33
    assert report.duplicate_clusters >= 10
    assert report.final_contact_count == report.total_input_rows - report.rows_merged_away
    assert Path(tmp_path / "cleaned.csv").exists()
    assert Path(tmp_path / "report.md").exists()


def test_mock_provider_brings_coverage_to_100_percent(tmp_path):
    merged, report = run_pipeline(SAMPLE, base_config(tmp_path, provider="mock"))
    assert report.still_missing_phone == 0
    assert report.still_missing_email == 0
    assert all(m.phone and m.email for m in merged)


def test_no_network_calls_when_llm_disabled_and_provider_none(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("No external call should happen in this configuration")

    monkeypatch.setattr("dbcleanup.dedupe._llm_judge", boom)
    run_pipeline(SAMPLE, base_config(tmp_path, provider="none", llm_enabled=False))
