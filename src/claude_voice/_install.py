from __future__ import annotations
import json
import shutil
from pathlib import Path
import sys


def _merge_event_hook(settings: dict, event: str, command: str) -> dict:
    """Append a command hook under settings["hooks"][event], deduping by
    command. Same shape whether it's Stop (end-of-turn TTS) or PreToolUse
    (interim narration before each tool call)."""
    settings = dict(settings)
    hooks = dict(settings.get("hooks") or {})
    event_list = list(hooks.get(event) or [])
    for entry in event_list:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                hooks[event] = event_list
                settings["hooks"] = hooks
                return settings
    event_list.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    })
    hooks[event] = event_list
    settings["hooks"] = hooks
    return settings


def merge_stop_hook(settings: dict, command: str = "claude-voice-hook") -> dict:
    return _merge_event_hook(settings, "Stop", command)


def merge_pretooluse_hook(settings: dict, command: str = "claude-voice-hook") -> dict:
    """Speak interim narration before each tool call. Each assistant text
    block gets a unique message_id in the transcript, so the daemon's
    existing response_id dedup keeps the same command from re-speaking
    the same block when multiple tools chain."""
    return _merge_event_hook(settings, "PreToolUse", command)


def merge_userpromptsubmit_hook(settings: dict, command: str = "claude-voice-hook") -> dict:
    """Play a tick when Claude Code receives a user prompt so you can hear
    that Claude has started thinking without looking at the screen."""
    return _merge_event_hook(settings, "UserPromptSubmit", command)


def _cli() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "merge-settings":
        print("usage: python -m claude_voice._install merge-settings", file=sys.stderr)
        return 2
    path = Path.home() / ".claude" / "settings.json"
    if path.exists():
        with open(path) as fp:
            data = json.load(fp)
    else:
        data = {}
    # Resolve to an absolute path so Claude Code can invoke the hook without
    # depending on its own exec environment's PATH — which typically excludes
    # anaconda/venv bin dirs added only by .zshrc.
    resolved = shutil.which("claude-voice-hook") or "claude-voice-hook"
    merged = merge_stop_hook(data, command=resolved)
    merged = merge_pretooluse_hook(merged, command=resolved)
    merged = merge_userpromptsubmit_hook(merged, command=resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fp:
        json.dump(merged, fp, indent=2)
    print(f"updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
