"""Agentic tool-calling loop over the Ollama chat API.

Drives: ask the model (with tool schemas) -> if it returns tool_calls, execute
them (auto, or pause for confirmation) -> feed results back -> repeat until the
model returns a normal answer. Yields typed events the route turns into SSE.

Confirmation: when a tool needs approval, we save the in-progress state in
PENDING keyed by a pending_id, yield ToolConfirm, and stop. The client approves
via the resume endpoint, which calls resume_agent() to continue.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Iterator

from .. import config
from . import session_service, tools_service
from .llm_service import SYSTEM_PROMPT, LLMService


# --- events ---

@dataclass
class ToolStarted:
    name: str
    args: dict


@dataclass
class ToolResult:
    name: str
    result: str
    ok: bool


@dataclass
class ToolConfirm:
    pending_id: str
    name: str
    args: dict


@dataclass
class Done:
    text: str


AgentEvent = ToolStarted | ToolResult | ToolConfirm | Done


@dataclass
class AgentState:
    llm: LLMService
    session_id: str
    user_text: str
    messages: list[dict]
    pending_calls: list[dict] = field(default_factory=list)
    awaiting: tuple[str, dict] | None = None


# pending_id -> paused AgentState awaiting user confirmation
PENDING: dict[str, AgentState] = {}


def _parse_call(call: dict) -> tuple[str, dict]:
    fn = call.get("function", {}) or {}
    name = fn.get("name", "")
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, (args or {})


def _safe_execute(name: str, args: dict) -> tuple[str, bool]:
    try:
        return tools_service.execute(name, args), True
    except tools_service.ToolError as exc:
        return f"Error: {exc}", False


def _persist(state: AgentState, assistant_text: str) -> None:
    if assistant_text:
        session_service.append(state.session_id, "user", state.user_text)
        session_service.append(state.session_id, "assistant", assistant_text)


def _drive(state: AgentState) -> Iterator[AgentEvent]:
    iters = 0
    while True:
        # Execute any queued tool calls (pausing for confirm-required ones).
        while state.pending_calls:
            name, args = _parse_call(state.pending_calls[0])
            if tools_service.requires_confirmation(name):
                pending_id = uuid.uuid4().hex
                state.awaiting = (name, args)
                PENDING[pending_id] = state
                yield ToolConfirm(pending_id, name, args)
                return
            state.pending_calls.pop(0)
            yield ToolStarted(name, args)
            result, ok = _safe_execute(name, args)
            yield ToolResult(name, result, ok)
            state.messages.append({"role": "tool", "name": name, "content": result})

        iters += 1
        if iters > config.TOOLS_MAX_ITERS:
            text = "Sorry, I couldn't complete that."
            _persist(state, text)
            yield Done(text)
            return

        msg = state.llm.chat(state.messages, tools=tools_service.get_tool_schemas())
        calls = msg.get("tool_calls")
        if not calls:
            content = (msg.get("content") or "").strip() or "Done."
            _persist(state, content)
            yield Done(content)
            return
        state.messages.append(msg)
        state.pending_calls = list(calls)


def run_agent(llm: LLMService, session_id: str, user_text: str) -> Iterator[AgentEvent]:
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + session_service.get_history(session_id)
        + [{"role": "user", "content": user_text}]
    )
    state = AgentState(
        llm=llm, session_id=session_id, user_text=user_text, messages=messages
    )
    yield from _drive(state)


def resume_agent(pending_id: str, approved: bool) -> Iterator[AgentEvent]:
    state = PENDING.pop(pending_id, None)
    if state is None or state.awaiting is None:
        yield Done("That action is no longer pending.")
        return

    name, args = state.awaiting
    state.awaiting = None
    state.pending_calls.pop(0)  # consume the confirm call

    if approved:
        yield ToolStarted(name, args)
        result, ok = _safe_execute(name, args)
        yield ToolResult(name, result, ok)
    else:
        result = "User declined this action."
        yield ToolResult(name, result, False)
    state.messages.append({"role": "tool", "name": name, "content": result})

    yield from _drive(state)
