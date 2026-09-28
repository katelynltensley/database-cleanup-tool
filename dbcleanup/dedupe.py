"""
Matching engine: decide which contact rows are the same person.

Design principle (this is the whole point of the project): rules handle
what rules are good at -- exact phone/email matches, formatting-driven
near-matches -- and Claude is only called for the genuinely ambiguous
middle ground, capped so a messy database can't generate a surprise bill.

Pipeline:
  1. Block candidate pairs (avoid O(n^2) on the full database).
  2. Score each candidate pair deterministically.
  3. High score -> auto-merge. Low score -> not a match. Middle -> ask
     Claude (or, if Claude is off, fall back to a stricter deterministic
     cutoff) up to a configured call budget.
  4. Union-find over confirmed matches to build clusters of duplicates.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass

from rapidfuzz import fuzz

from .normalize import (
    name_match_key,
    normalize_address,
    normalize_email,
    normalize_phone,
    normalize_zip,
)
from .parser import Contact


@dataclass
class MatchDecision:
    a_id: int
    b_id: int
    score: float
    method: str  # "exact_contact" | "auto_merge" | "llm" | "fallback_rule"
    is_match: bool
    reason: str = ""


class UnionFind:
    def __init__(self, ids: list[int]):
        self.parent = {i: i for i in ids}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def clusters(self) -> list[list[int]]:
        groups: dict[int, list[int]] = defaultdict(list)
        for i in self.parent:
            groups[self.find(i)].append(i)
        return list(groups.values())


def _fingerprint(c: Contact) -> dict:
    return {
        "phone": normalize_phone(c.phone) or normalize_phone(c.secondary_phone),
        "email": normalize_email(c.email),
        "name_key": name_match_key(c.full_name()),
        "last_key": name_match_key(c.last_name),
        "addr_key": normalize_address(c.address) + " " + normalize_zip(c.zip),
    }


def _candidate_pairs(contacts: list[Contact]) -> set[tuple[int, int]]:
    """Block on shared last name, phone, or email so we never do full N^2."""
    fp = {c.row_id: _fingerprint(c) for c in contacts}
    blocks: dict[str, list[int]] = defaultdict(list)

    for c in contacts:
        f = fp[c.row_id]
        if f["last_key"]:
            blocks[f"last:{f['last_key']}"].append(c.row_id)
        if f["phone"]:
            blocks[f"phone:{f['phone']}"].append(c.row_id)
        if f["email"]:
            blocks[f"email:{f['email']}"].append(c.row_id)

    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        members = sorted(set(members))
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.add((members[i], members[j]))
    return pairs


def _score_pair(fp_a: dict, fp_b: dict) -> tuple[float, str]:
    """Return (score 0-100, method) for a candidate pair."""
    if fp_a["phone"] and fp_a["phone"] == fp_b["phone"]:
        return 100.0, "exact_contact"
    if fp_a["email"] and fp_a["email"] == fp_b["email"]:
        return 100.0, "exact_contact"

    name_score = fuzz.token_sort_ratio(fp_a["name_key"], fp_b["name_key"])
    if fp_a["addr_key"].strip() and fp_b["addr_key"].strip():
        addr_score = fuzz.token_sort_ratio(fp_a["addr_key"], fp_b["addr_key"])
        composite = 0.6 * name_score + 0.4 * addr_score
    else:
        # No address on both sides to corroborate -- lean on name alone but
        # discount it, since name-only matches are the least reliable.
        composite = 0.8 * name_score

    return round(composite, 1), "scored"


LLM_PROMPT = """You are deduplicating a real estate agent's contact database. \
Decide whether these two contact records refer to the same real person, even \
though the data is messy (nicknames, typos, missing fields, formatting \
differences are all common). Respond with strict JSON only, no prose: \
{{"same_person": true or false, "reason": "<one short sentence>"}}

Record A: {a}
Record B: {b}
"""


def _llm_judge(a: Contact, b: Contact, model: str) -> tuple[bool, str]:
    """Ask Claude to resolve an ambiguous pair. Raises on API/parse failure
    so the caller can fall back to the deterministic rule."""
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": LLM_PROMPT.format(
                    a=json.dumps(a.as_dict()), b=json.dumps(b.as_dict())
                ),
            }
        ],
    )
    text = "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    ).strip()
    # Tolerate a stray code fence even though the prompt asks for bare JSON.
    text = text.strip("`").removeprefix("json").strip()
    parsed = json.loads(text)
    return bool(parsed["same_person"]), str(parsed.get("reason", ""))


def find_duplicate_clusters(
    contacts: list[Contact],
    auto_merge_threshold: float = 92,
    review_threshold: float = 72,
    llm_enabled: bool = True,
    llm_model: str = "claude-sonnet-4-5",
    max_llm_calls: int = 250,
) -> tuple[list[list[int]], list[MatchDecision]]:
    """Return (clusters of row_ids, full decision log for the report)."""
    fp = {c.row_id: _fingerprint(c) for c in contacts}
    by_id = {c.row_id: c for c in contacts}
    pairs = _candidate_pairs(contacts)

    decisions: list[MatchDecision] = []
    uf = UnionFind([c.row_id for c in contacts])

    llm_available = llm_enabled and bool(os.environ.get("ANTHROPIC_API_KEY"))
    llm_calls_used = 0

    # Deterministic and exact-match pairs first; ambiguous pairs queued.
    ambiguous: list[tuple[int, int, float]] = []
    for a_id, b_id in sorted(pairs):
        score, method = _score_pair(fp[a_id], fp[b_id])
        if method == "exact_contact" or score >= auto_merge_threshold:
            decisions.append(
                MatchDecision(a_id, b_id, score, method or "auto_merge", True)
            )
            uf.union(a_id, b_id)
        elif score >= review_threshold:
            ambiguous.append((a_id, b_id, score))
        else:
            decisions.append(MatchDecision(a_id, b_id, score, "scored", False))

    for a_id, b_id, score in ambiguous:
        if llm_available and llm_calls_used < max_llm_calls:
            try:
                is_match, reason = _llm_judge(by_id[a_id], by_id[b_id], llm_model)
                llm_calls_used += 1
                decisions.append(
                    MatchDecision(a_id, b_id, score, "llm", is_match, reason)
                )
                if is_match:
                    uf.union(a_id, b_id)
                continue
            except Exception as exc:  # noqa: BLE001 -- fall back on any API/parse issue
                fallback_reason = f"llm_unavailable: {exc}"
        else:
            fallback_reason = (
                "llm_budget_exhausted" if llm_available else "llm_disabled"
            )

        # Deterministic fallback: split the difference between the two
        # thresholds so behavior is at least consistent without an LLM.
        cutoff = (auto_merge_threshold + review_threshold) / 2
        is_match = score >= cutoff
        decisions.append(
            MatchDecision(a_id, b_id, score, "fallback_rule", is_match, fallback_reason)
        )
        if is_match:
            uf.union(a_id, b_id)

    clusters = [c for c in uf.clusters() if len(c) > 1]
    return clusters, decisions
