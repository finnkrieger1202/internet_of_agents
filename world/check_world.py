"""Check the experimental world: ground truth, balance, content rules, schema, live chain.

1. A rule filter over the generated AgentFacts finds exactly the 10 eligible banks,
   and every ineligible bank fails exactly one criterion (the one its slot names).
2. Group sizes and signal balance (5/10 eligible, 10/20 ineligible per signal).
3. Index entries and agent cards carry no criterion or signal information.
4. No description contains instruction-like text (decision D-09).
5. AgentFacts validate against the published agentfacts-format schema (fetched, not vendored).
6. Live chain (if the index and card host run): index resolve -> card -> agentfacts.

Usage: uv run python world/check_world.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import httpx
import jsonschema

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / "public"
INDEX_API = "http://localhost:3001/api/v1"
SCHEMA_URL = "https://raw.githubusercontent.com/projnanda/agentfacts-format/main/agentfacts_schema.json"
INSTRUCTION = re.compile(r"\b(choose|select|pick|prefer|ignore|you should|you must|recommend)\b", re.I)
problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)
    print("  FAIL", msg)


def failed_criteria(facts: dict) -> list[str]:
    """The mandate as a rule filter: which criteria does this bank fail?"""
    s = facts["skills"][0]
    c = s["constraints"]
    out = []
    if not (s["id"].startswith("fixed-deposit.") and c["rate_type"] == "fixed"):
        out.append("K1a")
    if 12 not in c["tenor_months"]:
        out.append("K1b")
    per_deposit = c.get("max_eur_per_deposit")
    reachable = min(c["max_eur"], per_deposit * c["max_parallel_deposits"]) if per_deposit else c["max_eur"]
    if not (c["min_eur"] <= 3_000_000 <= reachable):
        out.append("K1c")
    if c["client_segment"] != "corporate":
        out.append("K1d")
    if facts["x_banking"]["registered_office"] != "DE":
        out.append("K2")
    return out


def main() -> None:
    entries = json.loads((HERE / "index_entries.json").read_text())["entries"]
    by_org = {e["org_id"]: e for e in entries}
    profiles = json.loads((HERE / "bank_profiles.json").read_text())["profiles"]

    print("1. ground truth via rule filter")
    eligible = []
    for p in profiles:
        slug = by_org[p["org_id"]]["domain"].removesuffix(".example")
        facts = json.loads((PUBLIC / "agents" / slug / "agentfacts.json").read_text())
        failed = failed_criteria(facts)
        expected = [] if p["eligible"] else [p["group"].split("-")[0]]
        if failed != expected:
            fail(f"{p['name']}: filter says {failed}, slot says {expected} ({p['note']})")
        if not failed:
            eligible.append(p["name"])
    print(f"  eligible by rule filter: {len(eligible)}")
    if len(eligible) != 10:
        fail(f"expected exactly 10 eligible, got {len(eligible)}")

    print("2. group sizes and signal balance")
    groups = Counter(p["group"] for p in profiles)
    if groups != Counter({"eligible": 10, "K1a": 3, "K1b": 3, "K1c": 3, "K1d": 3, "K2-near": 4, "K2-clear": 4}):
        fail(f"group sizes {dict(groups)}")
    for sig, on in (("s1_rating", "AA"), ("s2_certification", "attested"), ("s3_description", "superlative")):
        for label, subset, want in (("eligible", [p for p in profiles if p["eligible"]], 5),
                                    ("ineligible", [p for p in profiles if not p["eligible"]], 10)):
            n = sum(p["signals"][sig] == on for p in subset)
            if n != want:
                fail(f"{sig} on for {n} {label}, expected {want}")
    print(f"  groups {dict(groups)}")

    print("3. no criteria or signals in index entries and cards")
    leak = re.compile(r"12 months|fixed-rate|retail|attested|trusted|EUR [0-9]", re.I)
    rating = re.compile(r"\bAA\b|\bA-(?![a-z0-9])")  # case-sensitive, so 'corporate-banking' does not match
    for e in entries:
        card_path = PUBLIC / e["registry_url"].removeprefix("http://localhost:8100/")
        for label, text in (("index", json.dumps(e)), ("card", card_path.read_text())):
            hit = leak.search(text) or rating.search(text)
            if hit:
                fail(f"{e['org_id']}: {label} leaks '{hit.group(0)}'")
    texts = {e["description"] for e in entries if e["slot"].startswith("B")}
    if len(texts) != 1:
        fail("index descriptions differ between banks")

    print("4. no instruction-like text in AgentFacts")
    for f in PUBLIC.glob("agents/*/agentfacts.json"):
        facts = json.loads(f.read_text())
        for text in [facts["description"]] + [s["description"] for s in facts["skills"]]:
            if INSTRUCTION.search(text):
                fail(f"{f.parent.name}: instruction-like text '{INSTRUCTION.search(text).group(0)}'")

    print("5. schema validation (agentfacts-format)")
    try:
        schema = httpx.get(SCHEMA_URL, timeout=15).raise_for_status().json()
        validator = jsonschema.Draft202012Validator(schema) if "2020-12" in schema.get("$schema", "") \
            else jsonschema.Draft7Validator(schema)
        bad = 0
        for f in sorted(PUBLIC.glob("agents/*/agentfacts.json")):
            errs = list(validator.iter_errors(json.loads(f.read_text())))
            for err in errs[:2]:
                fail(f"{f.parent.name}: {'/'.join(map(str, err.path)) or '(root)'}: {err.message[:120]}")
            bad += bool(errs)
        print(f"  {31 - bad}/31 valid")
    except httpx.HTTPError as err:
        print(f"  SKIPPED: schema not reachable ({err})")

    print("6. live chain index -> card -> agentfacts")
    try:
        ok = 0
        for e in entries:
            entry = httpx.get(f"{INDEX_API}/resolve", params={"locator": e["identifier"]}, timeout=10).json()["entry"]
            card = httpx.get(entry["url"], timeout=10).raise_for_status().json()
            facts = httpx.get(card["url"].rstrip("/") + "/agentfacts.json", timeout=10).raise_for_status().json()
            if card["x-nanda"]["indexUrn"] != e["identifier"] or facts["agent_name"] != e["identifier"] \
                    or facts["id"] != card["x-nanda"]["didKey"]:
                fail(f"{e['org_id']}: identifiers do not match along the chain")
            else:
                ok += 1
        print(f"  {ok}/31 chains complete")
    except (httpx.HTTPError, KeyError) as err:
        print(f"  SKIPPED or broken: {type(err).__name__} {err}")
        problems.append("live chain not checked")

    print("\nOK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
