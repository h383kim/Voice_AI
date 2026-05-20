"""macOS system-action tools the agent can call.

Security: every action runs via subprocess with an argument **list** (never a
shell string). Model/voice-supplied values are passed to osascript through
`argv`, never interpolated into the AppleScript source, so there is no shell or
AppleScript injection. open_url validates the scheme; open_app uses an allowlist.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from .. import config


class ToolError(Exception):
    """Raised when a tool's arguments are invalid or execution fails."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], str]
    requires_confirmation: bool


def _run(args: list[str]) -> None:
    try:
        subprocess.run(args, capture_output=True, text=True, check=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        raise ToolError((exc.stderr or "command failed").strip()[-300:]) from exc
    except FileNotFoundError as exc:
        raise ToolError(f"{args[0]} not found (macOS only).") from exc


# --- handlers ---

def _notify(args: dict) -> str:
    title = str(args.get("title") or "Assistant")
    message = str(args.get("message") or "").strip()
    if not message:
        raise ToolError("notify requires a non-empty 'message'.")
    # Values passed via argv -> no injection.
    script = (
        "on run argv\n"
        "  display notification (item 2 of argv) with title (item 1 of argv)\n"
        "end run"
    )
    _run(["osascript", "-e", script, title, message])
    return f"Notification shown: {title} — {message}"


def _open_url(args: dict) -> str:
    url = str(args.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError("open_url only accepts http/https URLs.")
    _run(["/usr/bin/open", url])
    return f"Opened {url}"


def _open_app(args: dict) -> str:
    name = str(args.get("name") or "").strip()
    if not name:
        raise ToolError("open_app requires an app 'name'.")
    allowed = {a.lower() for a in config.OPEN_APP_ALLOWLIST}
    if name.lower() not in allowed:
        raise ToolError(
            f"App '{name}' is not allowlisted. Allowed: "
            f"{', '.join(config.OPEN_APP_ALLOWLIST)}"
        )
    _run(["/usr/bin/open", "-a", name])
    return f"Opened {name}"


_MUSIC_SCRIPTS = {
    "play": 'tell application "Music" to play',
    "pause": 'tell application "Music" to pause',
    "playpause": 'tell application "Music" to playpause',
    "next": 'tell application "Music" to next track',
    "previous": 'tell application "Music" to previous track',
}


def _music(args: dict) -> str:
    action = str(args.get("action") or "").strip().lower()
    if action == "volume":
        try:
            value = int(args.get("value"))
        except (TypeError, ValueError):
            raise ToolError("music volume requires an integer 'value' 0-100.")
        if not 0 <= value <= 100:
            raise ToolError("music volume must be between 0 and 100.")
        _run(["osascript", "-e", f'tell application "Music" to set sound volume to {value}'])
        return f"Set music volume to {value}"
    if action not in _MUSIC_SCRIPTS:
        raise ToolError(
            "music action must be one of: play, pause, playpause, next, previous, volume."
        )
    _run(["osascript", "-e", _MUSIC_SCRIPTS[action]])
    return f"Music: {action}"


# --- registry ---

TOOLS: dict[str, Tool] = {
    "notify": Tool(
        name="notify",
        description="Show a macOS desktop notification.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notification title."},
                "message": {"type": "string", "description": "Notification body text."},
            },
            "required": ["message"],
        },
        handler=_notify,
        requires_confirmation=False,
    ),
    "open_url": Tool(
        name="open_url",
        description="Open a web URL (http/https) in the default browser.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full http/https URL."},
            },
            "required": ["url"],
        },
        handler=_open_url,
        requires_confirmation=True,
    ),
    "open_app": Tool(
        name="open_app",
        description="Launch a macOS application by name (allowlisted apps only).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Application name, e.g. Calculator."},
            },
            "required": ["name"],
        },
        handler=_open_app,
        requires_confirmation=True,
    ),
    "music": Tool(
        name="music",
        description="Control the macOS Music app.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "playpause", "next", "previous", "volume"],
                    "description": "Playback action.",
                },
                "value": {
                    "type": "integer",
                    "description": "Volume 0-100 (only for action=volume).",
                },
            },
            "required": ["action"],
        },
        handler=_music,
        requires_confirmation=False,
    ),
}


def get_tool_schemas() -> list[dict]:
    """Ollama/OpenAI-style tool definitions for the chat request."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]


def requires_confirmation(name: str) -> bool:
    tool = TOOLS.get(name)
    return bool(tool and tool.requires_confirmation)


def execute(name: str, args: dict) -> str:
    tool = TOOLS.get(name)
    if not tool:
        raise ToolError(f"Unknown tool: {name}")
    return tool.handler(args or {})
