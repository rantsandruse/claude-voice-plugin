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
    wav = rec.stop()
    if wav is None:
        click.echo("no audio captured")
        return
    click.echo(f"transcribing {wav}…")
    click.echo(stt.transcribe(wav))


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
