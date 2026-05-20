"""Agent loop tests with a fake LLM (no Ollama) and mocked tool execution."""
import pytest

from backend.app.services import agent_service, session_service, tools_service
from backend.app.services.agent_service import (
    Done,
    ToolConfirm,
    ToolResult,
    ToolStarted,
    resume_agent,
    run_agent,
)


class FakeLLM:
    """Returns a scripted sequence of assistant messages on each chat() call."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return self._scripted.pop(0)


def _tool_call(name, args):
    return {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


@pytest.fixture(autouse=True)
def no_real_exec(monkeypatch):
    calls = []
    monkeypatch.setattr(tools_service, "_run", lambda args: calls.append(args))
    return calls


def test_plain_answer_no_tools():
    llm = FakeLLM([{"content": "Hi there."}])
    sid = session_service.ensure_session("agent-1")
    events = list(run_agent(llm, sid, "hello"))
    assert events == [Done("Hi there.")]
    assert session_service.get_history(sid)[-1]["content"] == "Hi there."
    session_service.reset(sid)


def test_auto_tool_then_answer(no_real_exec):
    llm = FakeLLM([
        _tool_call("notify", {"message": "Tea is ready"}),
        {"content": "Done — notification sent."},
    ])
    sid = session_service.ensure_session("agent-2")
    events = list(run_agent(llm, sid, "notify me tea is ready"))
    assert isinstance(events[0], ToolStarted) and events[0].name == "notify"
    assert isinstance(events[1], ToolResult) and events[1].ok
    assert events[-1] == Done("Done — notification sent.")
    assert no_real_exec  # osascript invoked once
    session_service.reset(sid)


def test_confirm_required_pauses_then_resume_approved(no_real_exec):
    llm = FakeLLM([
        _tool_call("open_url", {"url": "https://example.com"}),
        {"content": "Opened the page."},
    ])
    sid = session_service.ensure_session("agent-3")
    events = list(run_agent(llm, sid, "open example"))
    assert len(events) == 1 and isinstance(events[0], ToolConfirm)
    pending_id = events[0].pending_id
    assert events[0].name == "open_url"

    resumed = list(resume_agent(pending_id, approved=True))
    assert isinstance(resumed[0], ToolStarted)
    assert isinstance(resumed[1], ToolResult) and resumed[1].ok
    assert resumed[-1] == Done("Opened the page.")
    assert no_real_exec  # the open command ran after approval
    session_service.reset(sid)


def test_confirm_required_denied_does_not_execute(no_real_exec):
    llm = FakeLLM([
        _tool_call("open_app", {"name": "Calculator"}),
        {"content": "Okay, I won't open it."},
    ])
    sid = session_service.ensure_session("agent-4")
    events = list(run_agent(llm, sid, "open calculator"))
    pending_id = events[0].pending_id

    resumed = list(resume_agent(pending_id, approved=False))
    # No ToolStarted (nothing executed); a denied ToolResult, then the answer.
    assert not any(isinstance(e, ToolStarted) for e in resumed)
    assert isinstance(resumed[0], ToolResult) and resumed[0].ok is False
    assert resumed[-1] == Done("Okay, I won't open it.")
    assert no_real_exec == []  # nothing actually executed
    session_service.reset(sid)


def test_max_iters_cap(monkeypatch):
    monkeypatch.setattr(agent_service.config, "TOOLS_MAX_ITERS", 3)
    # Always returns an auto tool call -> would loop forever without the cap.
    llm = FakeLLM([_tool_call("music", {"action": "next"}) for _ in range(10)])
    sid = session_service.ensure_session("agent-5")
    events = list(run_agent(llm, sid, "keep going"))
    assert isinstance(events[-1], Done)
    assert llm.calls <= 3
    session_service.reset(sid)


def test_expired_pending_id():
    events = list(resume_agent("does-not-exist", approved=True))
    assert isinstance(events[0], Done)
