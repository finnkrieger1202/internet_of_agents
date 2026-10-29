"""Deterministic mock model: exercises the full pipeline (tools, NANDA Index, logging,
structured output) without inference and without an API key.

It reads the conversation and answers only with tool calls:
search the index once, then submit every bank it found. It is a pipeline check,
not a baseline of rational behaviour.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

QUERY = "corporate deposits"


class MockTreasuryModel(BaseChatModel):
    submit_tool: str = "Screening"
    _calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "mock-treasury"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "MockTreasuryModel":
        names = [getattr(t, "name", None) or getattr(t, "__name__", None) or t.get("name") for t in tools]
        if "Screening" not in names and names:
            self.submit_tool = names[-1]
        return self

    def _tool_call(self, name: str, args: dict) -> AIMessage:
        self._calls += 1
        return AIMessage(content="", tool_calls=[{"id": f"mock-{self._calls}", "name": name, "args": args}])

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            msg = self._tool_call("search_index", {"query": QUERY})
        else:
            found = json.loads(results[-1].content).get("results", [])
            ids = [r["identifier"] for r in found if "bank" in r.get("tags", [])]
            msg = self._tool_call(self.submit_tool, {
                "eligible_identifiers": ids,
                "rationale": "Mock model: submits every bank returned by the index (pipeline check only).",
            })
        return ChatResult(generations=[ChatGeneration(message=msg)])
