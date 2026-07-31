from __future__ import annotations
import subprocess
import sys
import time

_KEYSTROKE = 'tell application "System Events" to keystroke "v" using command down'


def inject(text: str) -> None:
    if not text:
        return
    saved: bytes | None = None
    try:
        saved = subprocess.check_output(["pbpaste"])
        saved.decode("utf-8")  # verify it's text; raises otherwise
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        saved = None
        print("[inject] non-text clipboard; skipping restore", file=sys.stderr)

    subprocess.run(["pbcopy"], input=text.encode())
    subprocess.run(["osascript", "-e", _KEYSTROKE])
    time.sleep(0.15)
    if saved is not None:
        subprocess.run(["pbcopy"], input=saved)
