"""macOS system-action tools the agent can call.

Security: every action runs via subprocess with an argument **list** (never a
shell string). Model/voice-supplied values are passed to osascript through
`argv`, never interpolated into the AppleScript source, so there is no shell or
AppleScript injection. open_url validates the scheme; open_app uses an allowlist.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from .. import config

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Phone handle: digits with optional +, spaces, dashes, parens; at least 7 digits.
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s().-]{5,}$")


def _is_handle(value: str) -> bool:
    value = value.strip()
    return bool(_EMAIL_RE.match(value) or _PHONE_RE.match(value))


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


_FIND_CONTACT_SCRIPT = (
    "on run argv\n"
    "  set q to item 1 of argv\n"
    "  set out to \"\"\n"
    "  set n to 0\n"
    "  tell application \"Contacts\"\n"
    "    repeat with p in (every person whose name contains q)\n"
    "      set out to out & (name of p) & \": \"\n"
    "      repeat with ph in phones of p\n"
    "        set out to out & (value of ph) & \" \"\n"
    "      end repeat\n"
    "      repeat with em in emails of p\n"
    "        set out to out & (value of em) & \" \"\n"
    "      end repeat\n"
    "      set out to out & linefeed\n"
    "      set n to n + 1\n"
    "      if n is greater than or equal to (item 2 of argv as integer) then exit repeat\n"
    "    end repeat\n"
    "  end tell\n"
    "  return out\n"
    "end run"
)

_SEND_IMESSAGE_SCRIPT = (
    "on run argv\n"
    "  set theHandle to item 1 of argv\n"
    "  set theText to item 2 of argv\n"
    "  try\n"
    "    tell application \"Messages\"\n"
    "      set acc to 1st account whose service type = iMessage\n"
    "      set p to participant theHandle of acc\n"
    "      send theText to p\n"
    "    end tell\n"
    "    return \"OK\"\n"
    "  on error errMsg number errNum\n"
    "    return \"ERR \" & errNum & \": \" & errMsg\n"
    "  end try\n"
    "end run"
)


def _run_capture(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, check=True, timeout=20
        )
        return proc.stdout
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if "not authoriz" in stderr.lower() or "-1743" in stderr:
            raise ToolError(
                "Not authorized. Grant Automation permission in System Settings → "
                "Privacy & Security → Automation."
            ) from exc
        raise ToolError(stderr[-300:] or "command failed") from exc
    except FileNotFoundError as exc:
        raise ToolError(f"{args[0]} not found (macOS only).") from exc


def _find_contact(args: dict) -> str:
    name = str(args.get("name") or "").strip()
    if not name:
        raise ToolError("find_contact requires a 'name'.")
    out = _run_capture(
        ["osascript", "-e", _FIND_CONTACT_SCRIPT, name, str(config.CONTACTS_MAX_RESULTS)]
    ).strip()
    return out or f"No contact found matching '{name}'."


_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _words_to_digits(text: str) -> str:
    """Convert spelled-out English digits to numerals (other tokens kept)."""
    parts = [_DIGIT_WORDS.get(tok, tok) for tok in re.split(r"[\s,\-]+", text.strip().lower())]
    return "".join(parts)


def _normalize_handle(to: str) -> str:
    """Clean a recipient handle so Messages can resolve it.

    Emails are left as-is. For phone numbers: spelled-out digits become numerals,
    formatting (spaces/()-./) is stripped, a leading '+' is kept, and a national
    number (leading 0, no '+') is upgraded with DEFAULT_COUNTRY_CODE when set.
    """
    to = to.strip()
    if _EMAIL_RE.match(to):
        return to
    plus = to.startswith("+")
    digits = re.sub(r"\D", "", _words_to_digits(to))
    if not digits:
        return to  # let validation reject it
    if plus:
        return "+" + digits
    cc = config.DEFAULT_COUNTRY_CODE
    if cc:
        national = digits[1:] if digits.startswith("0") else digits
        return cc + national
    return digits


def _send_imessage(args: dict) -> str:
    if not config.IMESSAGE_ENABLED:
        raise ToolError("iMessage sending is disabled (IMESSAGE_ENABLED=false).")
    raw_to = str(args.get("to") or "").strip()
    message = str(args.get("message") or "").strip()
    # Normalize first (handles spelled-out digits / formatting), then validate.
    to = _normalize_handle(raw_to)
    if not _is_handle(to):
        raise ToolError(
            "send_imessage 'to' must be a phone number or email handle "
            "(say a number, or resolve a name with find_contact first)."
        )
    if not message:
        raise ToolError("send_imessage requires a non-empty 'message'.")
    out = _run_capture(["osascript", "-e", _SEND_IMESSAGE_SCRIPT, to, message]).strip()
    if not out.startswith("OK"):
        # AppleScript reported a failure (e.g. "ERR -1743: Not authorized",
        # "ERR -1728: Can't get participant ...") instead of silently no-op'ing.
        raise ToolError(out or "Message send failed (no response from Messages).")
    return f"Sent to {to}"


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
    "find_contact": Tool(
        name="find_contact",
        description=(
            "Look up a person in macOS Contacts by name and return their phone/email "
            "handles. Call this before send_imessage to get a recipient handle."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's name to search for."},
            },
            "required": ["name"],
        },
        handler=_find_contact,
        requires_confirmation=False,
    ),
    "send_imessage": Tool(
        name="send_imessage",
        description=(
            "Send an iMessage. 'to' must be a phone number or email handle obtained "
            "from find_contact (never guess a number)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient phone number or email handle."},
                "message": {"type": "string", "description": "Message text to send."},
                "display_name": {
                    "type": "string",
                    "description": "Recipient's name, for the confirmation prompt.",
                },
            },
            "required": ["to", "message"],
        },
        handler=_send_imessage,
        requires_confirmation=True,
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
