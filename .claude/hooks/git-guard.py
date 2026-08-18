#!/usr/bin/env python3
"""PreToolUse guard: force a confirmation prompt on git commands that write.

CLAUDE.md forbids committing or pushing without explicit permission. Instructions can be
forgotten mid-session; this hook cannot be. Anything matching a writing git subcommand is
escalated to an explicit user decision regardless of the current permission mode.

Branch *creation* (`checkout -b`, `switch -c`) is deliberately NOT guarded: the p2p pipeline
cuts one branch per task automatically. Branch *deletion* stays guarded, because that can
destroy uncommitted work.
"""
import json
import re
import sys

GUARDED = re.compile(
    r"""\bgit\b[^|;&]*?\b(
          commit | push | merge | rebase | reset | revert | cherry-pick
        | (branch\s+-[dD]) | (tag\b) | (clean\s+-[a-zA-Z]*f)
    )\b""",
    re.VERBOSE,
)

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

command = payload.get("tool_input", {}).get("command", "")
match = GUARDED.search(command)

if match:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                f"'git {match.group(1).strip()}' writes to git history. PlanToPlate's "
                f"CLAUDE.md requires explicit permission for every commit, push, or history "
                f"rewrite. Confirm only if you asked for this in your last message."
            ),
        }
    }))

sys.exit(0)
