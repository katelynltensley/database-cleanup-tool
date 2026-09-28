# Database Cleanup Tool

A command-line tool that takes a messy real estate agent contact export,
merges the duplicates, fills in missing phone numbers and emails from
whatever the database already has scattered across those duplicates, and
optionally runs whatever's still missing through a real paid lookup
provider. It outputs a clean CSV and a data-quality report explaining
exactly what changed and why.

Built to run unattended — one command, no prompts, no manual review step
required to finish a run — so it can be scheduled instead of run by hand.

## Why this exists

Real estate agent databases accumulate years of duplicate, partial, and
inconsistently formatted contacts: the same person entered twice with
different phone formatting, a nickname instead of a given name, an old
address that's been updated on one entry but not the other. Rule-based
dedupe tools tend to miss the near-matches that matter (a nickname plus a
typo'd address) and flag ones that don't (two different people who happen
to share a last name). This tool splits the problem the way it should be
split: deterministic code handles everything that's actually
deterministic — phone/email formatting, exact matches, clearly-not-a-match
pairs — and Claude is only called in for the genuinely ambiguous middle,
capped so a 10,000-row database can't generate a surprise bill.

## What it actually does, in order

1. **Parse** — flexible column-name mapping, so it isn't locked to one
   CRM's export format (`dbcleanup/parser.py`).
2. **Normalize** — phone numbers, emails, names, and addresses get put
   into consistent formats so later comparisons are apples-to-apples
   (`dbcleanup/normalize.py`).
3. **Match** — exact phone/email matches and clear fuzzy matches
   (name + address) are resolved by rules alone. Only pairs that land in
   the ambiguous middle get sent to Claude for a same-person judgment
   call, up to a configured budget; beyond that budget (or with Claude
   turned off) a conservative fallback rule takes over so the pipeline
   never stalls waiting on an API key (`dbcleanup/dedupe.py`).
4. **Fill gaps for free** — duplicate rows get merged into one golden
   record, and a phone or email present on one duplicate fills the gap on
   its sibling. No external cost (`dbcleanup/fillgap.py`).
5. **Enrich (optional, paid)** — whatever's still missing after the free
   pass can be run through a real lookup provider. Off by default
   (`dbcleanup/enrich/`).
6. **Report** — a Markdown + JSON data-quality report: duplicates found,
   what got filled and from where, conflicts it had to resolve, and
   what's still missing (`dbcleanup/report.py`).

## Quickstart

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml     # then edit if you want to change defaults
python cli.py --input sample_data/kw_command_sample_export.csv
```

That runs the free path end-to-end (dedupe + cross-record fill, Claude
judgment calls if `ANTHROPIC_API_KEY` is set) with no other setup and no
cost beyond whatever Claude calls the ambiguous pairs need. Output lands
in `output/cleaned_contacts.csv` and `output/data_quality_report.md`.

On the bundled 33-row sample (11 duplicate clusters, including a couple of
genuinely ambiguous nickname/address cases), the free pass alone takes
phone coverage from 54% to 59% and email coverage from 58% to 77% — pure
duplicate-fill, no paid lookups. Turning on the enrichment stage against
the bundled mock provider (`--provider mock`) — which returns obviously
fake, clearly-flagged demo data so this is runnable and demoable with zero
API cost — closes the rest of the gap to 100%, to show what the full
pipeline looks like end to end with a live provider wired in.

Useful flags:

```bash
python cli.py --input export.csv --no-llm              # rules only, no Claude calls
python cli.py --input export.csv --provider mock        # demo the paid-lookup stage for free
python cli.py --input export.csv --provider forewarn     # see "Wiring in Forewarn" below
python cli.py --input export.csv --output-dir results/
```

## Configuration (`config.yaml`)

- `matching.auto_merge_threshold` / `review_threshold` — the score band
  that separates "auto-merge," "ask Claude," and "not a match."
- `matching.max_claude_calls` — hard cap on ambiguous-pair judgment calls
  per run. Anything past the cap is left unmerged and flagged for manual
  review rather than silently guessed at.
- `llm.enabled` — turn Claude off entirely; the fallback rule takes over
  and the pipeline still finishes.
- `enrichment.provider` — `none` (default), `mock` (free demo), or
  `forewarn` (see below).
- `enrichment.max_lookups_per_run` — spend/rate cap for the paid stage.

## Wiring in a real enrichment provider

The enrichment stage is a small interface
(`dbcleanup/enrich/base.py::EnrichmentProvider`) with one method,
`lookup(contact) -> EnrichmentResult`. Adding a real provider means
writing one class and flipping a config value — the rest of the pipeline
doesn't change.

**Forewarn** is stubbed out (`dbcleanup/enrich/forewarn_provider.py`) but
not wired to a live endpoint, for two reasons that are worth reading before
enabling it:

1. Forewarn's public materials list "API and custom integrations
   available," but no technical docs (auth, endpoints, request/response
   shape) are published. Getting this working means asking your Forewarn
   or MLS/association rep for API credentials and the actual spec — the
   request-building code in the stub is a best-guess placeholder, not a
   confirmed contract.
2. Forewarn's phone/name search is built and positioned as an
   agent-safety / identity-verification tool — it returns identity,
   criminal, and financial records alongside phone numbers, which sits in
   FCRA-adjacent territory. Worth confirming with your rep, in writing,
   that automated bulk lookups for contact-list enrichment (rather than a
   one-off safety check before meeting someone) is a permitted use of the
   subscription, before pointing this at a real account. Also note their
   materials don't mention returning email addresses at all — plan on
   Forewarn as a phone-gap-filler only, with email still coming from
   cross-record fill or a different source.

## Testing

```bash
pip install pytest
python -m pytest -q
```

23 tests cover normalization edge cases, exact vs. fuzzy vs. ambiguous
matching (including that the fallback rule behaves conservatively and that
Claude is never called when disabled or over budget), cross-record fill
and conflict resolution, the mock/Forewarn providers, and a full
end-to-end run against the sample data.

## Architecture notes

- **Blocking before scoring**: candidate duplicate pairs are grouped by
  shared last name, phone, or email before any fuzzy comparison runs, so
  the matcher doesn't do an O(n²) comparison over the whole database.
- **Nothing is fabricated**: the mock provider's output uses phone numbers
  from the range NANPA reserves for fictional use (555-01xx) and an
  `.invalid` email domain, and every simulated result is flagged
  `is_simulated=True` end to end, so there's no path by which demo data
  could be mistaken for a real lookup result in the CSV or report.
- **Conflicts are surfaced, not silently resolved**: when duplicates
  disagree (two different phone numbers, say), the most recently-contacted
  record wins, but the discarded alternative is logged in the report
  rather than thrown away.

## Where this fits

This started as a Claude-powered rebuild of the database cleanup that's
part of Level 10 Leverage's Agent Assist service — currently done by hand
per client — into something that runs unattended and could be sold on its
own, one-time or subscription, to agents who just want a clean database
without the rest of the Agent Assist package.
