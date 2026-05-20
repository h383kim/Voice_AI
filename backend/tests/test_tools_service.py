"""Tool tests with subprocess mocked (no real osascript/open runs)."""
import pytest

from backend.app import config
from backend.app.services import tools_service
from backend.app.services.tools_service import (
    ToolError,
    execute,
    get_tool_schemas,
    requires_confirmation,
)


@pytest.fixture
def captured(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(tools_service, "_run", lambda args: calls.append(args))
    return calls


def test_schemas_cover_all_tools():
    names = {s["function"]["name"] for s in get_tool_schemas()}
    assert names == {"notify", "open_url", "open_app", "music"}


def test_confirmation_flags():
    assert requires_confirmation("open_url") is True
    assert requires_confirmation("open_app") is True
    assert requires_confirmation("notify") is False
    assert requires_confirmation("music") is False


def test_notify_passes_values_via_argv(captured):
    execute("notify", {"title": "Build", "message": 'done "ok"'})
    args = captured[0]
    assert args[0] == "osascript"
    # The dynamic strings are argv tail entries, not spliced into the script.
    assert args[-2:] == ["Build", 'done "ok"']
    assert 'done "ok"' not in args[2]  # not interpolated into the AppleScript source


def test_notify_requires_message(captured):
    with pytest.raises(ToolError):
        execute("notify", {"title": "x"})


def test_open_url_rejects_non_http(captured):
    with pytest.raises(ToolError):
        execute("open_url", {"url": "file:///etc/passwd"})
    with pytest.raises(ToolError):
        execute("open_url", {"url": "not a url"})
    assert captured == []  # nothing executed


def test_open_url_accepts_https(captured):
    execute("open_url", {"url": "https://example.com/x"})
    assert captured[0] == ["/usr/bin/open", "https://example.com/x"]


def test_open_app_enforces_allowlist(captured, monkeypatch):
    monkeypatch.setattr(config, "OPEN_APP_ALLOWLIST", ["Calculator", "Notes"])
    execute("open_app", {"name": "calculator"})  # case-insensitive
    assert captured[0] == ["/usr/bin/open", "-a", "calculator"]
    with pytest.raises(ToolError):
        execute("open_app", {"name": "Terminal"})


def test_music_actions_and_volume(captured):
    execute("music", {"action": "pause"})
    execute("music", {"action": "volume", "value": 40})
    assert captured[0][0] == "osascript"
    assert "set sound volume to 40" in captured[1][-1]
    with pytest.raises(ToolError):
        execute("music", {"action": "destroy"})
    with pytest.raises(ToolError):
        execute("music", {"action": "volume", "value": 999})


def test_unknown_tool_raises(captured):
    with pytest.raises(ToolError):
        execute("rm_rf", {})
