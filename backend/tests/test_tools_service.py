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


@pytest.fixture
def captured_capture(monkeypatch):
    """Capture calls to _run_capture (find_contact / send_imessage); returns OK."""
    calls: list[list[str]] = []

    def fake(args):
        calls.append(args)
        return "OK"

    monkeypatch.setattr(tools_service, "_run_capture", fake)
    return calls


def test_schemas_cover_all_tools():
    names = {s["function"]["name"] for s in get_tool_schemas()}
    assert names == {
        "notify", "open_url", "open_app", "music", "find_contact", "send_imessage",
    }


def test_confirmation_flags():
    assert requires_confirmation("open_url") is True
    assert requires_confirmation("open_app") is True
    assert requires_confirmation("send_imessage") is True
    assert requires_confirmation("notify") is False
    assert requires_confirmation("music") is False
    assert requires_confirmation("find_contact") is False


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


def test_find_contact_builds_argv(captured_capture):
    execute("find_contact", {"name": "Sarah Kim"})
    args = captured_capture[0]
    assert args[0] == "osascript"
    # Name passed via argv, not interpolated into the AppleScript source.
    assert args[3] == "Sarah Kim"
    assert "Sarah Kim" not in args[2]


def test_send_imessage_normalizes_handle_and_passes_argv(captured_capture):
    execute("send_imessage", {"to": "+1 (555) 123-4567", "message": 'hi "there"'})
    execute("send_imessage", {"to": "sarah@icloud.com", "message": "hello"})
    # Phone formatting stripped before sending; email left as-is.
    assert captured_capture[0][-2:] == ["+15551234567", 'hi "there"']
    assert captured_capture[1][-2:] == ["sarah@icloud.com", "hello"]
    # Message not spliced into the AppleScript source.
    assert 'hi "there"' not in captured_capture[0][2]


def test_normalize_handle():
    assert tools_service._normalize_handle("+1 (555) 123-4567") == "+15551234567"
    assert tools_service._normalize_handle("(555) 123.4567") == "5551234567"
    assert tools_service._normalize_handle("sarah@icloud.com") == "sarah@icloud.com"


def test_normalize_handle_spelled_out_digits():
    spoken = "zero one zero one two three four five six seven eight"
    assert tools_service._normalize_handle(spoken) == "01012345678"


def test_normalize_handle_country_code(monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_COUNTRY_CODE", "+82")
    assert tools_service._normalize_handle("010-1234-5678") == "+821012345678"
    assert (
        tools_service._normalize_handle(
            "zero one zero one two three four five six seven eight"
        )
        == "+821012345678"
    )
    # Already international -> unchanged.
    assert tools_service._normalize_handle("+821012345678") == "+821012345678"


def test_send_imessage_accepts_spoken_number(captured_capture):
    execute(
        "send_imessage",
        {"to": "zero one zero one two three four five six seven eight", "message": "hi"},
    )
    assert captured_capture[0][-2:] == ["01012345678", "hi"]


def test_send_imessage_surfaces_failure(monkeypatch):
    monkeypatch.setattr(
        tools_service, "_run_capture", lambda args: "ERR -1728: Can't get participant"
    )
    with pytest.raises(ToolError, match="ERR -1728"):
        execute("send_imessage", {"to": "+15551234567", "message": "hi"})


def test_send_imessage_rejects_non_handle(captured_capture):
    with pytest.raises(ToolError):
        execute("send_imessage", {"to": "Sarah Kim", "message": "hi"})
    with pytest.raises(ToolError):
        execute("send_imessage", {"to": "+15551234567", "message": ""})
    assert captured_capture == []  # nothing sent


def test_send_imessage_respects_disabled_flag(captured_capture, monkeypatch):
    monkeypatch.setattr(config, "IMESSAGE_ENABLED", False)
    with pytest.raises(ToolError):
        execute("send_imessage", {"to": "+15551234567", "message": "hi"})
    assert captured_capture == []
