"""Substance Painter startup module: runs requests from the MCP server.

Replaces Painter's --enable-remote-scripting HTTP endpoint. That endpoint runs
code for anything that reaches its loopback port; this listens on a Unix socket
only this user can open, so a web page or another account can't reach it.

Requests are handled in Qt slots, so code runs on Painter's main thread, the
only one where the API is safe.

    request   {"kind": "python" | "session" | "eval" | "js", "code": "...", "params": {}}
    response  {"ok": true, "result": ..., "output": "..."}
    failure   {"ok": false, "error": "...", "error_type": "...", "traceback": "...", "output": "..."}
"""

import contextlib
import io
import json
import os
import traceback

from PySide6 import QtNetwork
import substance_painter.js
import substance_painter.logging

SOCKET_PATH = os.environ.get("SP_MCP_SOCKET", os.path.expanduser("~/.painter_bridge.sock"))
MAX_REQUEST_BYTES = 32 * 1024 * 1024

server = None
pending = {}
session = {}  # survives between "session" requests, for execute_python


def evaluate(request):
    kind, code = request["kind"], request["code"]
    if kind == "js":
        return substance_painter.js.evaluate(code)
    if kind == "eval":
        return eval(compile(code, "<painter-bridge>", "eval"), {})
    if kind == "session":
        scope = session
        scope.pop("result", None)
    elif kind == "python":
        scope = {}
    else:
        raise ValueError("Unknown request kind: %s" % kind)
    scope["params"] = request.get("params") or {}
    exec(compile(code, "<painter-bridge>", "exec"), scope)
    return scope.get("result")


def handle(line):
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            reply = {"ok": True, "result": evaluate(json.loads(line))}
    except BaseException as exc:
        reply = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        }
    reply["output"] = output.getvalue()
    return json.dumps(reply, default=str, ensure_ascii=False).encode("utf-8")


def on_ready(socket):
    buffered = pending.get(socket)
    if buffered is None:
        return
    buffered += bytes(socket.readAll())
    if len(buffered) > MAX_REQUEST_BYTES:
        socket.abort()
    elif buffered.endswith(b"\n"):
        pending[socket] = bytearray()
        socket.write(handle(bytes(buffered)) + b"\n")
        socket.flush()
        socket.disconnectFromServer()


def on_gone(socket):
    pending.pop(socket, None)
    socket.deleteLater()


def on_connection():
    while server.hasPendingConnections():
        socket = server.nextPendingConnection()
        pending[socket] = bytearray()
        socket.readyRead.connect(lambda s=socket: on_ready(s))
        socket.disconnected.connect(lambda s=socket: on_gone(s))


def start_plugin():
    global server
    QtNetwork.QLocalServer.removeServer(SOCKET_PATH)
    server = QtNetwork.QLocalServer()
    server.setSocketOptions(QtNetwork.QLocalServer.SocketOption.UserAccessOption)
    server.newConnection.connect(on_connection)
    if not server.listen(SOCKET_PATH):
        substance_painter.logging.error("Bridge failed: " + server.errorString())
        return
    substance_painter.logging.info("Bridge listening on " + SOCKET_PATH)


def close_plugin():
    global server
    if server:
        server.close()
        server = None
