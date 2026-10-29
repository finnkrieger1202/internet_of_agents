"""Tools of the treasury agent: thin wrappers around real NANDA Index API calls.

The agent has no global view of the Internet of Agents. It perceives it only through
these protocol operations; every call and its result is logged by the caller.
Results are returned as NANDA sends them (no filtering), so the agent sees exactly
what a real NANDA client would see.
"""

from __future__ import annotations

import json
import os

import httpx
from langchain_core.tools import tool

INDEX_API = os.environ.get("NANDA_INDEX_API", "http://localhost:3001/api/v1")
_http = httpx.Client(timeout=15)


@tool
def search_index(query: str) -> str:
    """Search the NANDA Index for agents by keyword (organisation name, domain,
    identifier, tags or description). Returns the index records as JSON."""
    resp = _http.get(f"{INDEX_API}/search", params={"q": query})
    resp.raise_for_status()
    return json.dumps(resp.json(), ensure_ascii=False)


@tool
def resolve_agent(identifier: str) -> str:
    """Resolve an agent identifier (urn:air:...) in the NANDA Index to its index
    entry, including where its agent card is hosted. Returns JSON."""
    resp = _http.get(f"{INDEX_API}/resolve", params={"locator": identifier})
    if resp.status_code == 404:
        return json.dumps({"error": "not found", "identifier": identifier})
    resp.raise_for_status()
    return json.dumps(resp.json(), ensure_ascii=False)


INDEX_TOOLS = [search_index, resolve_agent]
