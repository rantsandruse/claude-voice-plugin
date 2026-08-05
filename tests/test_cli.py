from click.testing import CliRunner
from claude_voice.cli import main


def test_stop_when_daemon_not_running(mocker):
    mocker.patch("claude_voice.cli.send_message", return_value=None)
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test_stop_when_daemon_running(mocker):
    mocker.patch("claude_voice.cli.send_message", return_value={"ok": True})
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0
    assert "stop" in result.output.lower() or "ok" in result.output.lower()


def test_status_prints_json(mocker):
    mocker.patch(
        "claude_voice.cli.send_message",
        return_value={"ok": True, "playing": False},
    )
    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0
    assert "playing" in result.output


def test_replay_sends_op(mocker):
    send = mocker.patch(
        "claude_voice.cli.send_message", return_value={"ok": True}
    )
    result = CliRunner().invoke(main, ["replay"])
    assert result.exit_code == 0
    assert send.call_args.args[0]["op"] == "replay"


def test_test_tts_speaks(mocker):
    mocker.patch("claude_voice.cli.load_config")
    mocker.patch("claude_voice.cli.read_secrets", return_value={
        "DEEPGRAM_API_KEY": None,
        "ELEVENLABS_API_KEY": None,
        "ANTHROPIC_API_KEY": None,
    })
    provider = mocker.MagicMock()
    handle = mocker.MagicMock()
    provider.speak.return_value = handle
    mocker.patch("claude_voice.cli._make_tts_primary", return_value=provider)
    result = CliRunner().invoke(main, ["test-tts", "hello"])
    assert result.exit_code == 0
    provider.speak.assert_called_once_with("hello")
    handle.wait.assert_called()
