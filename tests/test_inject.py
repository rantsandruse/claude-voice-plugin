import subprocess
from claude_voice.inject import inject


def test_inject_pastes_and_restores_clipboard(mocker):
    # pbpaste returns "prev clipboard"
    check_output = mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        return_value=b"prev clipboard",
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("new text")

    # Sequence: check_output(pbpaste), run(pbcopy new), run(osascript ⌘V), run(pbcopy prev)
    check_output.assert_called_once_with(["pbpaste"])
    calls = run.call_args_list
    # first run: pbcopy of "new text"
    assert calls[0].args[0] == ["pbcopy"]
    assert calls[0].kwargs["input"] == b"new text"
    # second run: osascript keystroke
    assert calls[1].args[0][0] == "osascript"
    assert "keystroke" in " ".join(calls[1].args[0])
    # third run: pbcopy restore
    assert calls[2].args[0] == ["pbcopy"]
    assert calls[2].kwargs["input"] == b"prev clipboard"


def test_inject_handles_non_utf8_clipboard(mocker):
    mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        return_value=b"\xff\xfe\x00\x01",  # not UTF-8
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("hello")

    # pbcopy new + osascript, but NO restore (skipped)
    ops = [c.args[0] for c in run.call_args_list]
    assert ops.count(["pbcopy"]) == 1


def test_inject_handles_pbpaste_failure(mocker):
    mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "pbpaste"),
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("hello")

    ops = [c.args[0] for c in run.call_args_list]
    # still does pbcopy + osascript, just no restore
    assert ["pbcopy"] in ops


def test_inject_auto_submit_sends_return(mocker):
    mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        return_value=b"prev clipboard",
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("hello", auto_submit=True)

    # Find the osascript calls in order
    osascript_scripts = [
        " ".join(c.args[0])
        for c in run.call_args_list
        if c.args[0] and c.args[0][0] == "osascript"
    ]
    assert len(osascript_scripts) == 2
    assert 'keystroke "v"' in osascript_scripts[0]
    assert "keystroke return" in osascript_scripts[1]


def test_inject_default_does_not_submit(mocker):
    """Default behavior (auto_submit=False) must NOT send Return."""
    mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        return_value=b"prev",
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("hello")  # no auto_submit arg → False by default

    osascript_scripts = [
        " ".join(c.args[0])
        for c in run.call_args_list
        if c.args[0] and c.args[0][0] == "osascript"
    ]
    assert len(osascript_scripts) == 1
    assert "keystroke return" not in osascript_scripts[0]
