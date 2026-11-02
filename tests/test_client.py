import json
import os
import shutil
import socket
import tempfile
import threading

import pytest

from substance_painter_mcp.client import (
    PainterConnectionError,
    PainterRemote,
    PainterRemoteConfig,
    PainterScriptError,
    PainterTimeoutError,
)


class FakeBridge:
    """Unix-socket server that answers like painter_plugin/painter_bridge.py."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        # tmp_path can exceed the short length limit on socket paths.
        self.directory = tempfile.mkdtemp(prefix="sp", dir="/tmp")
        self.path = os.path.join(self.directory, "bridge.sock")
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(self.path)
        self.listener.listen()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            with connection, connection.makefile("rb") as reader:
                request = json.loads(reader.readline())
                self.requests.append(request)
                reply = self.handler(request)
                if reply is not None:
                    connection.sendall(json.dumps(reply).encode() + b"\n")

    def remote(self, timeout=2.0):
        return PainterRemote(PainterRemoteConfig(self.path, timeout))

    def close(self):
        self.listener.close()
        shutil.rmtree(self.directory)


@pytest.fixture
def bridge_for():
    created = []

    def create(handler):
        created.append(FakeBridge(handler))
        return created[-1]

    yield create
    for bridge in created:
        bridge.close()


def ok(result, output=""):
    return lambda _request: {"ok": True, "result": result, "output": output}


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SP_MCP_SOCKET", "/tmp/custom.sock")
    monkeypatch.setenv("SP_MCP_TIMEOUT", "2.5")
    assert PainterRemoteConfig.from_env() == PainterRemoteConfig("/tmp/custom.sock", 2.5)


def test_config_defaults_without_env(monkeypatch):
    monkeypatch.delenv("SP_MCP_SOCKET", raising=False)
    monkeypatch.delenv("SP_MCP_TIMEOUT", raising=False)
    assert PainterRemoteConfig.from_env() == PainterRemoteConfig("~/.painter_bridge.sock", 30.0)


def test_python_json_transports_params_as_data(bridge_for):
    bridge = bridge_for(ok({"value": 1}))
    params = {"name": "quote ' layer", "color": [1, 2, 3]}
    assert bridge.remote().execute_python_json("result = 1", params) == {
        "success": True,
        "data": {"value": 1},
    }
    assert bridge.requests == [{"kind": "python", "code": "result = 1", "params": params}]


def test_session_returns_printed_output(bridge_for):
    bridge = bridge_for(ok(3, "hello\n"))
    assert bridge.remote().execute_session("print('hello')") == {
        "result": 3,
        "output": "hello\n",
    }
    assert bridge.requests[0]["kind"] == "session"


def test_js_decodes_json_strings(bridge_for):
    assert bridge_for(ok("true")).remote().execute_js("x") is True
    assert bridge_for(ok("12.2.0")).remote().execute_js("x") == "12.2.0"


def test_script_failure_includes_type_and_traceback(bridge_for):
    bridge = bridge_for(
        lambda _request: {
            "ok": False,
            "error": "missing",
            "error_type": "ValueError",
            "traceback": "line 7",
            "output": "",
        }
    )
    with pytest.raises(PainterScriptError, match=r"ValueError: missing\nline 7"):
        bridge.remote().execute_python("x")


def test_missing_socket_is_a_connection_error():
    remote = PainterRemote(PainterRemoteConfig("/tmp/no-such-painter.sock", 0.1))
    with pytest.raises(PainterConnectionError, match="Open Substance Painter"):
        remote.check_connection()


def test_hang_up_without_reply_is_a_connection_error(bridge_for):
    with pytest.raises(PainterConnectionError, match="before replying"):
        bridge_for(lambda _request: None).remote().execute_python("x")


def test_timeout_is_not_reported_as_a_failed_connection(bridge_for):
    release = threading.Event()

    def stall(_request):
        release.wait(2)
        return None

    bridge = bridge_for(stall)
    with pytest.raises(PainterTimeoutError, match="may\\s+still finish"):
        bridge.remote(timeout=0.1).execute_python("x")
    release.set()


def test_requests_are_never_retried(bridge_for):
    bridge = bridge_for(lambda _request: None)
    with pytest.raises(PainterConnectionError):
        bridge.remote().execute_python_json("edit()")
    assert len(bridge.requests) == 1
