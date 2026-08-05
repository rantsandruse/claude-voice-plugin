from __future__ import annotations
from pathlib import Path
from typing import Callable
import json
import os
import socket
import threading

from .config import CONFIG_DIR

SOCKET_PATH = CONFIG_DIR / "daemon.sock"


def send_message(
    msg: dict,
    socket_path: Path | None = None,
    timeout: float = 2.0,
) -> dict | None:
    path = socket_path or SOCKET_PATH
    if not path.exists():
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        # Use relative path to work around the 104-char macOS AF_UNIX limit.
        prev_cwd = os.getcwd()
        try:
            os.chdir(str(path.parent))
            s.connect(path.name)
        finally:
            os.chdir(prev_cwd)
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
        return None
    try:
        s.sendall((json.dumps(msg) + "\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk:
                break
        line = data.decode().splitlines()[0] if data else ""
        return json.loads(line) if line else None
    except (socket.timeout, json.JSONDecodeError, OSError):
        return None
    finally:
        s.close()


class IPCServer:
    def __init__(self, socket_path: Path, handlers: dict[str, Callable[[dict], dict]]):
        self._path = socket_path
        self._handlers = handlers
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._path.exists():
            self._path.unlink()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(0.5)
        # Bind using a relative path to work around the 104-char macOS limit
        # for AF_UNIX socket paths.
        prev_cwd = os.getcwd()
        try:
            os.chdir(str(self._path.parent))
            self._sock.bind(self._path.name)
        finally:
            os.chdir(prev_cwd)
        self._sock.listen(8)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._path.exists():
            self._path.unlink()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()  # type: ignore
            except (socket.timeout, OSError):
                continue
            threading.Thread(
                target=self._handle_conn, args=(conn,), daemon=True
            ).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2.0)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            line = data.decode().split("\n", 1)[0]
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                conn.sendall(b'{"ok":false,"error":"malformed"}\n')
                return
            op = msg.get("op")
            handler = self._handlers.get(op)
            if not handler:
                conn.sendall(b'{"ok":false,"error":"unknown op"}\n')
                return
            try:
                reply = handler(msg) or {"ok": True}
            except Exception as e:
                reply = {"ok": False, "error": str(e)}
            conn.sendall((json.dumps(reply) + "\n").encode())
        finally:
            conn.close()
