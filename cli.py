#!/usr/bin/env python3
"""
Database Cleanup Tool — CLI entrypoint.

Usage:
    python cli.py --input path/to/export.csv
    python cli.py --input path/to/export.csv --config config.yaml
    python cli.py --input path/to/export.csv --provider mock
    python cli.py --input path/to/export.csv --no-llm

Runs the whole pipeline unattended: parse -> dedupe -> free cross-record
fill -> optional paid enrichment -> clean CSV + data-quality report.
Exits 0 on success with a summary printed to stdout, non-zero on failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from dbcleanup.pipeline import run_pipeline

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
EXAMPLE_CONFIG_PATH = Path(__file__).parent / "config.example.yaml"


def load_config(path: Path | None) -> dict:
    if path and path.exists():
        return yaml.safe_load(path.read_text())
    if DEFAULT_CONFIG_PATH.exists():
        return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text())
    if EXAMPLE_CONFIG_PATH.exists():
        print(
            f"No config.yaml found -- using {EXAMPLE_CONFIG_PATH.name} defaults. "
            "Copy it to config.yaml to customize.",
            file=sys.stderr,
        )
        return yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text())
    raise SystemExit("No config file found and no config.example.yaml to fall back to.")


def main() -> int:
    load_dotenv()  # picks up ANTHROPIC_API_KEY / FOREWARN_API_KEY from .env if present

    parser = argparse.ArgumentParser(description="Clean and enrich a messy contact database.")
    parser.add_argument("--input", required=True, help="Path to the CSV/Excel export to clean.")
    parser.add_argument("--config", type=Path, default=None, help="Path to a config YAML file.")
    parser.add_argument(
        "--provider",
        choices=["none", "mock", "forewarn"],
        default=None,
        help="Override the enrichment provider set in config.",
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Disable Claude for ambiguous-match judgment calls."
    )
    parser.add_argument(
        "--output-dir", default=None, help="Override the output directory for CSV/report files."
    )
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1

    config = load_config(args.config)

    if args.provider is not None:
        config.setdefault("enrichment", {})["provider"] = args.provider
    if args.no_llm:
        config.setdefault("llm", {})["enabled"] = False
    if args.output_dir:
        out = Path(args.output_dir)
        config.setdefault("output", {})
        config["output"]["clean_csv"] = str(out / "cleaned_contacts.csv")
        config["output"]["report"] = str(out / "data_quality_report.md")
        config["output"]["report_json"] = str(out / "data_quality_report.json")

    try:
        merged, report = run_pipeline(args.input, config)
    except Exception as exc:  # noqa: BLE001 -- top-level CLI boundary
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1

    print(f"Processed {report.total_input_rows} rows -> {report.final_contact_count} unique contacts")
    print(f"  Duplicate clusters merged: {report.duplicate_clusters}")
    print(
        f"  Phone coverage: {report.phone_present_before_pct:.0f}% -> "
        f"{report.phone_present_after_pct:.0f}%"
    )
    print(
        f"  Email coverage: {report.email_present_before_pct:.0f}% -> "
        f"{report.email_present_after_pct:.0f}%"
    )
    print(f"  Still needs manual research -- phone: {report.still_missing_phone}, "
          f"email: {report.still_missing_email}")
    out_cfg = config.get("output", {})
    print(f"\nClean CSV:  {out_cfg.get('clean_csv', 'output/cleaned_contacts.csv')}")
    print(f"Report:     {out_cfg.get('report', 'output/data_quality_report.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
