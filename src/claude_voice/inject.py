from __future__ import annotations
import subprocess
import sys
import time

_KEYSTROKE_PASTE = 'tell application "System Events" to keystroke "v" using command down'
_KEYSTROKE_RETURN = 'tell application "System Events" to keystroke return'


def _run_osascript(script: str, label: str) -> None:
    """Run an osascript keystroke command and surface failures. Previously
    these calls were fire-and-forget subprocess.run() with no return-code
    check, which silently swallowed the common macOS-1002 "assistive access
    not authorized" error — pastes would just no-op and the user got no
    signal that Accessibility permission was missing."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[inject] osascript {label} failed (rc={result.returncode}): "
            f"{(result.stderr or '').strip()}",
            file=sys.stderr,
        )


def frontmost_app() -> str | None:
    """Bundle id of the app in front, e.g. com.apple.Terminal. None if it
    can't be read."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.bundleIdentifier()) if app is not None else None
    except Exception:
        return None


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
    _run_osascript(_KEYSTROKE_PASTE, "paste")
    time.sleep(0.15)
    if saved is not None:
        subprocess.run(["pbcopy"], input=saved)
    if auto_submit:
        # Small extra delay so the paste settles before Enter fires;
        # avoids racing with terminal input processing.
        time.sleep(0.05)
        _run_osascript(_KEYSTROKE_RETURN, "return")
