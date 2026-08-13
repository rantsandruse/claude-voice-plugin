from __future__ import annotations
import json
import time
import click

from .config import load_config, load_dotenv_if_present, secrets as read_secrets
from .ipc import send_message
from .daemon import run_daemon, _make_stt, _make_tts_primary
from .recorder import Recorder


@click.group()
def main() -> None:
    """Claude Voice — voice plugin for Claude Code."""


@main.command()
def start() -> None:
    """Run the daemon (blocking)."""
    run_daemon()


@main.command()
def stop() -> None:
    """Stop the running daemon."""
    reply = send_message({"op": "quit"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo("stopped")


@main.command()
def restart() -> None:
    """Stop the running daemon and start a new one in the background."""
    import subprocess
    from .ipc import SOCKET_PATH
    reply = send_message({"op": "quit"})
    if reply is not None:
        click.echo("stopped")
        # Wait for the socket to disappear so the new daemon doesn't race
        # with the old one's atexit cleanup. Old daemon's atexit unlinks it;
        # new daemon's startup also unlinks defensively, but polling avoids
        # the flap.
        for _ in range(20):
            if not SOCKET_PATH.exists():
                break
            time.sleep(0.25)
    else:
        click.echo("daemon was not running")
    subprocess.Popen(
        ["claude-voice", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    click.echo("restarted (running in background)")


@main.command()
def status() -> None:
    """Print daemon status as JSON."""
    reply = send_message({"op": "status"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo(json.dumps(reply, indent=2))


@main.command()
def replay() -> None:
    """Replay the last spoken response."""
    reply = send_message({"op": "replay"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo("ok" if reply.get("ok") else "nothing to replay")


@main.command()
def interrupt() -> None:
    """Force-stop any in-flight TTS. Fallback if a wedged say/afplay is
    blocking future PTT presses and the auto-timeout hasn't fired yet."""
    reply = send_message({"op": "interrupt"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo("interrupted")


@main.command("test-mic")
def test_mic() -> None:
    """Record 3 seconds and print the transcript."""
    load_dotenv_if_present()
    config = load_config()
    secrets = read_secrets()
    stt = _make_stt(config, secrets)
    rec = Recorder()
    click.echo("recording 3s… speak now")
    rec.start()
    time.sleep(3.0)
    result = rec.stop()
    if result is None:
        click.echo("no audio captured")
        return
    audio, sample_rate = result
    click.echo(f"transcribing {len(audio) / sample_rate:.1f}s of audio…")
    click.echo(stt.transcribe_audio(audio, sample_rate))


@main.command("test-tts")
@click.argument("text")
def test_tts(text: str) -> None:
    """Speak TEXT via the configured TTS provider."""
    load_dotenv_if_present()
    config = load_config()
    secrets = read_secrets()
    provider = _make_tts_primary(config, secrets)
    handle = provider.speak(text)
    handle.wait()
