from __future__ import annotations
import json
from pathlib import Path
import sys


def merge_stop_hook(settings: dict, command: str = "claude-voice-hook") -> dict:
    settings = dict(settings)
    hooks = dict(settings.get("hooks") or {})
    stop_list = list(hooks.get("Stop") or [])
    # dedupe by command
    for entry in stop_list:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                hooks["Stop"] = stop_list
                settings["hooks"] = hooks
                return settings
    stop_list.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    })
    hooks["Stop"] = stop_list
    settings["hooks"] = hooks
    return settings


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
    merged = merge_stop_hook(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fp:
        json.dump(merged, fp, indent=2)
    print(f"updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
