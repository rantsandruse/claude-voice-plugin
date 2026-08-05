from claude_voice._install import (
    merge_stop_hook,
    merge_pretooluse_hook,
    merge_userpromptsubmit_hook,
)


def test_merge_userpromptsubmit_into_empty_settings():
    out = merge_userpromptsubmit_hook({})
    assert out["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "claude-voice-hook"


def test_merge_userpromptsubmit_is_idempotent():
    once = merge_userpromptsubmit_hook({})
    twice = merge_userpromptsubmit_hook(once)
    commands = [
        h["command"]
        for entry in twice["hooks"]["UserPromptSubmit"]
        for h in entry.get("hooks", [])
    ]
    assert commands.count("claude-voice-hook") == 1


def test_merge_into_empty_settings():
    out = merge_stop_hook({})
    assert out["hooks"]["Stop"][0]["hooks"][0]["command"] == "claude-voice-hook"


def test_merge_pretooluse_into_empty_settings():
    out = merge_pretooluse_hook({})
    assert out["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "claude-voice-hook"


def test_merge_pretooluse_is_idempotent():
    once = merge_pretooluse_hook({})
    twice = merge_pretooluse_hook(once)
    commands = [
        h["command"]
        for entry in twice["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert commands.count("claude-voice-hook") == 1


def test_merge_pretooluse_preserves_other_pretooluse_hooks():
    settings = {"hooks": {"PreToolUse": [
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "other-guard"}]}
    ]}}
    out = merge_pretooluse_hook(settings)
    commands = [
        h["command"]
        for entry in out["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert "other-guard" in commands
    assert "claude-voice-hook" in commands


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
