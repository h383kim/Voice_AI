#!/usr/bin/env bash
# Test iMessage sending in isolation (no backend / LLM needed).
#
# Usage:  ./scripts/test_imessage.sh "<handle>" "<message>"
#   <handle>  a phone number (full international, e.g. +15551234567) or email
#   <message> the text to send
#
# Prints "OK" on success, or "ERR <num>: <reason>" on failure. The first run
# triggers the macOS Automation permission prompt for Messages — approve it.
# Common errors: -1743 = not authorized (grant Automation permission);
# -1728 = couldn't resolve the recipient (try the full +country-code number).
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 \"<handle>\" \"<message>\"" >&2
  exit 2
fi

osascript -e '
on run argv
  set theHandle to item 1 of argv
  set theText to item 2 of argv
  try
    tell application "Messages"
      set acc to 1st account whose service type = iMessage
      set p to participant theHandle of acc
      send theText to p
    end tell
    return "OK"
  on error errMsg number errNum
    return "ERR " & errNum & ": " & errMsg
  end try
end run
' "$1" "$2"
