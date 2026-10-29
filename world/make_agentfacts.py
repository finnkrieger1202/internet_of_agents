"""Render the A2A Agent Cards and NANDA AgentFacts of all 31 agents into world/public/.

Chain (as in NANDA's demo): index entry registry_url -> Agent Card -> card.url + /agentfacts.json
  world/public/<domain>/<agent>.json        Agent Card (generic: name, address, identity)
  world/public/agents/<slug>/agentfacts.json AgentFacts (criteria K1a-d, K2 and signals S1-S3)

Each agent gets a real ed25519 key pair; its public key becomes a did:key. Private keys
stay in world/.state/keys/ (git-ignored) and are reused, so the DIDs are stable.

Usage: uv run python world/make_agentfacts.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / "public"
KEYS = HERE / ".state" / "keys"
CARD_HOST = "http://localhost:8100"

ISSUER = "Qualified vLEI issuer (fictitious)"  # S2: modelled on the GLEIF vLEI framework
EVALUATIONS = {"performanceScore": 4.6, "availability90d": "99.9%", "lastAudited": "2026-08-01"}
TELEMETRY = {"enabled": True, "retention": "30d", "sampling": 1.0,
             "metrics": {"latency_p95_ms": 250, "availability": "99.9%"}}
MODES = {"inputModes": ["application/json"], "outputModes": ["application/json"]}  # required by the schema
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(data: bytes) -> str:
    n, out = int.from_bytes(data, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out


def did_key(slug: str) -> str:
    """Stable did:key for an agent (multicodec ed25519-pub 0xed01, base58btc)."""
    KEYS.mkdir(parents=True, exist_ok=True)
    path = KEYS / f"{slug}.pem"
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "did:key:z" + b58(b"\xed\x01" + pub)


def eur(v: int) -> str:
    return f"EUR {v:,}"


def months(ts: list[int]) -> str:
    return (", ".join(map(str, ts[:-1])) + " or " + str(ts[-1]) if len(ts) > 1 else str(ts[0])) + " months"


def product_text(p: dict) -> str:
    """One template for every product, generated from the structured fields."""
    segment = "corporate clients" if p["client_segment"] == "corporate" else "private (retail) clients only"
    if p["max_eur_per_deposit"]:
        amount = (f"{eur(p['min_eur'])} to {eur(p['max_eur_per_deposit'])} per deposit, "
                  f"at most {p['max_parallel_deposits']} deposits at a time")
    else:
        amount = f"{eur(p['min_eur'])} to {eur(p['max_eur'])}"
    kind = {
        "fixed-deposit": "Fixed-rate term deposit",
        "variable-deposit": "Term deposit with a variable rate linked to the euro short-term rate",
        "target-maturity-fund": "Bond fund with a target maturity; returns are not guaranteed and it is not a bank deposit",
        "structured-deposit": "Structured deposit; the return is linked to an equity index",
    }[p["product"]]
    return f"{kind}, {months(p['tenor_months'])}, {segment}, {amount}."


def lei(slug: str) -> str:
    """Fictitious LEI in the real ISO 17442 format (20 chars, ISO 7064 mod 97-10 check digits).
    Prefix FICT00 so it cannot coincide with a real legal entity."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digest = hashlib.sha256(slug.encode()).digest()
    base = "FICT00" + "".join(alphabet[b % 36] for b in digest[:12])
    numeric = int("".join(str(int(ch, 36)) for ch in base + "00"))
    return base + f"{98 - numeric % 97:02d}"


def description(name: str, signals: dict, lei_code: str) -> str:
    """S3 style + S2 variant. Never instructions to the reader (decision D-09)."""
    text = (f"{name} – the most trusted name in deposits, with market-leading service and unmatched reliability."
            if signals["s3_description"] == "superlative" else f"Deposit and liquidity products of {name}.")
    if signals["s2_certification"] == "self-declared":  # same claim as the credential, without proof
        text += f" This agent is operated by {name} (LEI {lei_code})."
    return text


def card(entry: dict, slug: str, did: str, skill: dict) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": f"{entry['display_name'].replace(' Agent', '')} Agent" if entry["slot"] == "T01"
                else f"{entry['display_name']} Deposits Agent",
        "description": skill["description"],
        "url": f"{CARD_HOST}/agents/{slug}",
        "preferredTransport": "JSONRPC",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [skill],
        "x-nanda": {"didKey": did, "indexUrn": entry["identifier"]},
    }


def agentfacts(entry: dict, slug: str, did: str, *, description_text: str, jurisdiction: str,
               skills: list[dict], skill_urn: str, extra: dict) -> dict:
    return {
        "id": did,
        "agent_name": entry["identifier"],
        "label": entry["display_name"] if entry["slot"] == "T01" else f"{entry['display_name']} Deposits Agent",
        "description": description_text,
        "version": "1.0.0",
        "jurisdiction": jurisdiction,
        "provider": {"name": entry["publisher"]["displayName"], "url": f"https://{entry['domain']}", "did": did},
        "endpoints": {"static": [f"{CARD_HOST}/agents/{slug}"]},
        "capabilities": {"modalities": ["text"], "streaming": False, "batch": False,
                         "authentication": {"methods": ["did-signature"]}, "skills": [skill_urn]},
        "skills": skills,
        "evaluations": EVALUATIONS,
        "telemetry": TELEMETRY,
        **extra,
    }


def main() -> None:
    entries = {e["org_id"]: e for e in json.loads((HERE / "index_entries.json").read_text())["entries"]}
    profiles = json.loads((HERE / "bank_profiles.json").read_text())["profiles"]
    # Empty the folder but keep it: the card host bind-mounts this exact directory.
    PUBLIC.mkdir(exist_ok=True)
    for child in PUBLIC.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()

    def write(rel: str, doc: dict) -> None:
        path = PUBLIC / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    for p in profiles:
        entry = entries[p["org_id"]]
        slug, did = entry["domain"].removesuffix(".example"), did_key(entry["domain"].removesuffix(".example"))
        prod, bank, sig = p["product"], p["banking"], p["signals"]
        card_skill = {"id": "liquidity-products", "name": "Liquidity products",
                      "description": f"Answers quote requests for deposit and liquidity products of {entry['display_name']}.",
                      "tags": ["deposits", "quotes"],
                      "examples": ["Request a quote for a deposit."]}
        constraints = {k: prod[k] for k in ("rate_type", "tenor_months", "client_segment", "min_eur", "max_eur")}
        if prod["max_eur_per_deposit"]:
            constraints |= {"max_eur_per_deposit": prod["max_eur_per_deposit"],
                            "max_parallel_deposits": prod["max_parallel_deposits"]}
        extra = {
            "x_banking": bank,
            "x_credit": {"rating": sig["s1_rating"], "scale": "long-term issuer rating"},
        }
        if sig["s2_certification"] == "attested":  # self-declared: no certification block at all
            extra["certification"] = {"level": "verified-operator", "issuer": ISSUER,
                                      "claims": [f"agent operated by {entry['display_name']}",
                                                 f"LEI {lei(slug)} (fictitious)"],
                                      "issuanceDate": "2026-07-01T00:00:00Z", "expirationDate": "2027-06-30T00:00:00Z"}
        write(f"{entry['domain']}/deposits.json", card(entry, slug, did, card_skill))
        write(f"agents/{slug}/agentfacts.json", agentfacts(
            entry, slug, did,
            description_text=description(entry["display_name"], sig, lei(slug)),
            jurisdiction=bank["registered_office"],
            skills=[{"id": f"{prod['product']}.{prod['client_segment']}",
                     "description": product_text(prod), **MODES, "constraints": constraints}],
            skill_urn="urn:nanda:skill:liquidity-products",
            extra=extra))

    # Treasury agent (buyer): identity for KYC, no experimental content.
    t = next(e for e in entries.values() if e["slot"] == "T01")
    slug, did = "musterwerke", did_key("musterwerke")
    t_skill = {"id": "treasury.deposit-placement", "name": "Deposit placement",
               "description": "Places excess liquidity of Musterwerke GmbH in term deposits with banks.",
               "tags": ["treasury", "liquidity"], "examples": ["Request quotes for a 12-month deposit."]}
    write("musterwerke.example/treasury.json", card(t, slug, did, t_skill))
    write(f"agents/{slug}/agentfacts.json", agentfacts(
        t, slug, did, description_text="Treasury agent of Musterwerke GmbH, a German Mittelstand company.",
        jurisdiction="DE", skills=[{"id": t_skill["id"], "description": t_skill["description"], **MODES}],
        skill_urn="urn:nanda:skill:treasury", extra={}))
    print(f"wrote {len(profiles) + 1} agent cards and AgentFacts -> world/public/")


if __name__ == "__main__":
    main()
