from __future__ import annotations
import subprocess
import sys
import time

_KEYSTROKE_PASTE = 'tell application "System Events" to keystroke "v" using command down'
_KEYSTROKE_RETURN = 'tell application "System Events" to keystroke return'


def inject(text: str, auto_submit: bool = False) -> None:
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
    subprocess.run(["osascript", "-e", _KEYSTROKE_PASTE])
    time.sleep(0.15)
    if saved is not None:
        subprocess.run(["pbcopy"], input=saved)
    if auto_submit:
        # Small extra delay so the paste settles before Enter fires;
        # avoids racing with terminal input processing.
        time.sleep(0.05)
        subprocess.run(["osascript", "-e", _KEYSTROKE_RETURN])
