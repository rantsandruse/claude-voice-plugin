import time
from pathlib import Path
import pytest
from claude_voice.ipc import IPCServer, send_message


@pytest.fixture
def socket_path(tmp_path):
    return tmp_path / "test.sock"


def test_send_message_no_daemon_returns_none(socket_path):
    assert send_message({"op": "ping"}, socket_path=socket_path, timeout=0.5) is None


def test_server_dispatches_to_handler(socket_path):
    calls = []

    def handler(msg):
        calls.append(msg)
        return {"ok": True, "echo": msg.get("text")}

    server = IPCServer(socket_path, {"ping": handler})
    server.start()
    try:
        reply = send_message({"op": "ping", "text": "hi"}, socket_path=socket_path)
        assert reply == {"ok": True, "echo": "hi"}
        assert calls == [{"op": "ping", "text": "hi"}]
    finally:
        server.stop()


def test_server_unknown_op_returns_error(socket_path):
    server = IPCServer(socket_path, {})
    server.start()
    try:
        reply = send_message({"op": "nope"}, socket_path=socket_path)
        assert reply is not None
        assert reply["ok"] is False
    finally:
        server.stop()


def test_server_handles_malformed_message(socket_path):
    import socket
    server = IPCServer(socket_path, {})
    server.start()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(socket_path))
        s.sendall(b"not json\n")
        reply = s.recv(1024).decode()
        s.close()
        assert "malformed" in reply
    finally:
        server.stop()


def test_server_removes_stale_socket(socket_path):
    socket_path.touch()  # simulate leftover socket file
    server = IPCServer(socket_path, {})
    server.start()
    try:
        assert socket_path.exists()
    finally:
        server.stop()
    # after stop, socket should be cleaned up
    assert not socket_path.exists()
