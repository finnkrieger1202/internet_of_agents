"""Register the entries of world/index_entries.json in the LOCAL NANDA Index.

Follows NANDA's own registration flow through the public API:
  account (POST /auth/register) -> account email token (POST /auth/verify-account)
  -> entry (POST /api/v1/orgs) -> contact email token (POST /api/v1/verify-email).
Email tokens are read from the server log (SMTP_URL=log: no mail is sent).

The only bypass: the DNS-TXT ownership proof cannot be performed for `.example`
domains locally. It is marked as passed with the same UPDATE that NANDA runs after a
successful DNS check (markDomainVerified, server/src/db/queries/organizations.ts),
plus the constant created_at of the experiment.

Idempotent: existing entries of this file are deleted via the API and re-created.
Never runs against anything but localhost.

Usage: python3 world/register.py
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://localhost:3001"
SERVER_CONTAINER = "nanda-index-v2-server-1"
DB_CONTAINER = "nanda-index-v2-db-1"
HERE = Path(__file__).resolve().parent
ENTRIES = HERE / "index_entries.json"
STATE = HERE / ".state" / "accounts.json"  # local passwords, git-ignored

ACCOUNT_LINK = re.compile(r'account verification link for "(?P<email>[^"]+)" → \S*token=(?P<token>[0-9a-f]+)')
ORG_LINK = re.compile(r'verification link for org "(?P<org>[^"]+)" → \S*token=(?P<token>[0-9a-f]+)')


def call(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return err.code, {"raw": raw.decode(errors="replace")}


def latest_token(pattern: re.Pattern, key: str, value: str) -> str:
    """Newest emailed token for `value` from the server log (log mail transport)."""
    for _ in range(20):
        log = subprocess.run(["docker", "logs", SERVER_CONTAINER], capture_output=True, text=True).stdout
        hits = [m["token"] for m in pattern.finditer(log) if m[key] == value]
        if hits:
            return hits[-1]
        time.sleep(0.25)
    sys.exit(f"no emailed token found in the server log for {value}")


def psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", "nanda", "-d", "nanda_index", "-v", "ON_ERROR_STOP=1", "-qtA"],
        input=sql, capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"psql failed: {out.stderr.strip()}")
    return out.stdout.strip()


def session(entry: dict, state: dict) -> str:
    """Log in (or sign up and verify) the account that owns this entry."""
    email = entry["contact_email"]
    account = state.setdefault(email, {})
    if "password" not in account:
        account["password"] = secrets.token_urlsafe(18)
        status, body = call("POST", "/auth/register",
                            {"email": email, "password": account["password"], "display_name": entry["display_name"]})
        if status != 201:
            sys.exit(f"register {email}: {status} {body}")
        status, body2 = call("POST", "/auth/verify-account", {"token": latest_token(ACCOUNT_LINK, "email", email)})
        if status != 200:
            sys.exit(f"verify-account {email}: {status} {body2}")
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2))
        return body["token"]
    status, body = call("POST", "/auth/login", {"email": email, "password": account["password"]})
    if status != 200:
        sys.exit(f"login {email}: {status} {body}")
    return body["token"]


def register(entry: dict, token: str) -> None:
    org_id = entry["org_id"]
    status, _ = call("GET", f"/api/v1/orgs/{org_id}", token=token)
    if status == 200:
        status, body = call("DELETE", f"/api/v1/orgs/{org_id}", token=token)
        if status not in (200, 204):
            sys.exit(f"delete {org_id}: {status} {body}")
    payload = {k: v for k, v in entry.items() if k != "slot"}
    status, body = call("POST", "/api/v1/orgs", payload, token=token)
    if status != 201:
        sys.exit(f"create {org_id}: {status} {body}")
    status, body = call("POST", "/api/v1/verify-email", {"token": latest_token(ORG_LINK, "org", org_id)})
    if status != 200:
        sys.exit(f"verify-email {org_id}: {status} {body}")


def mark_domains_verified(org_ids: list[str], created_at: str) -> str:
    """Same UPDATE as NANDA's markDomainVerified after a successful DNS check."""
    ids = ",".join("'" + o.replace("'", "''") + "'" for o in org_ids)
    return psql(f"""
        UPDATE organizations SET
          ever_proven                 = TRUE,
          domain_verified             = TRUE,
          domain_verified_at          = NOW(),
          domain_challenge            = NULL,
          domain_challenge_expires_at = NULL,
          status                      = CASE WHEN status = 'pending' THEN 'active' ELSE status END,
          created_at                  = '{created_at}',
          updated_at                  = NOW()
        WHERE org_id IN ({ids})
        RETURNING org_id;
    """)


def main() -> None:
    doc = json.loads(ENTRIES.read_text())
    entries = doc["entries"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    started = time.time()
    for n, entry in enumerate(entries, 1):
        register(entry, session(entry, state))
        print(f"  [{n:2d}/{len(entries)}] {entry['org_id']:<22} {entry['identifier']}")
    done = mark_domains_verified([e["org_id"] for e in entries], doc["created_at"]).splitlines()
    print(f"\n{len(entries)} entries registered via the API, {len(done)} marked domain-verified "
          f"({time.time() - started:.1f} s).")


if __name__ == "__main__":
    main()
