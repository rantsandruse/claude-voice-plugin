from claude_voice._install import merge_stop_hook


def test_merge_into_empty_settings():
    out = merge_stop_hook({})
    assert out["hooks"]["Stop"][0]["hooks"][0]["command"] == "claude-voice-hook"


def test_merge_preserves_unrelated_settings():
    settings = {"other": "value", "hooks": {"PreToolUse": [{"matcher": "*"}]}}
    out = merge_stop_hook(settings)
    assert out["other"] == "value"
    assert out["hooks"]["PreToolUse"] == [{"matcher": "*"}]
    assert "Stop" in out["hooks"]


def test_merge_is_idempotent():
    settings = {}
    once = merge_stop_hook(settings)
    twice = merge_stop_hook(once)
    stop_entries = twice["hooks"]["Stop"]
    all_commands = [
        h["command"]
        for entry in stop_entries
        for h in entry.get("hooks", [])
    ]
    assert all_commands.count("claude-voice-hook") == 1


def test_merge_preserves_other_stop_hooks():
    settings = {"hooks": {"Stop": [
        {"matcher": "", "hooks": [{"type": "command", "command": "other-tool"}]}
    ]}}
    out = merge_stop_hook(settings)
    all_commands = [
        h["command"]
        for entry in out["hooks"]["Stop"]
        for h in entry.get("hooks", [])
    ]
    assert "other-tool" in all_commands
    assert "claude-voice-hook" in all_commands
