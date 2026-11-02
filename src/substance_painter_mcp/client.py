"""Client for painter_plugin/painter_bridge.py, over a private Unix socket."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import socket
from typing import Any, Literal


Kind = Literal["python", "session", "eval", "js"]

CHUNK_BYTES = 1024 * 1024
DEFAULT_SOCKET = "~/.painter_bridge.sock"


class PainterRemoteError(RuntimeError):
    """Base error raised by the Painter remote client."""


class PainterConnectionError(PainterRemoteError):
    """The bridge is not listening, so nothing ran."""


class PainterTimeoutError(PainterRemoteError):
    """Painter took too long to reply. The request may still finish there."""


class PainterScriptError(PainterRemoteError):
    """Painter rejected or failed to execute a script."""


@dataclass(frozen=True, slots=True)
class PainterRemoteConfig:
    socket_path: str = DEFAULT_SOCKET
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "PainterRemoteConfig":
        return cls(
            socket_path=os.getenv("SP_MCP_SOCKET", DEFAULT_SOCKET),
            timeout_seconds=float(os.getenv("SP_MCP_TIMEOUT", "30")),
        )


class PainterRemote:
    """Small, typed client for the Painter bridge.

    Requests are never retried: a reply that didn't arrive doesn't mean the
    edit didn't happen, and repeating it could apply it twice.
    """

    def __init__(self, config: PainterRemoteConfig | None = None):
        self.config = config or PainterRemoteConfig.from_env()

    def check_connection(self) -> str:
        """Return the Painter application version or raise a useful error."""
        return str(self.execute_js("alg.version.painter"))

    def execute_python(self, code: str) -> Any:
        """Evaluate one Python expression in Painter and return its value."""
        return self._send({"kind": "eval", "code": code})["result"]

    def execute_js(self, code: str) -> Any:
        result = self._send({"kind": "js", "code": code})["result"]
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return result

    def execute_python_json(
        self,
        code: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run statements in an isolated namespace and return a JSON envelope.

        ``code`` may read the JSON-compatible ``params`` mapping and assign its
        return value to ``result``. Values travel as JSON instead of being
        interpolated into Python source, preventing quoting/code-injection bugs.
        """
        reply = self._send({"kind": "python", "code": code, "params": params or {}})
        return {"success": True, "data": reply["result"]}

    def execute_session(self, code: str) -> dict[str, Any]:
        """Run statements in the namespace kept between calls; capture prints too."""
        reply = self._send({"kind": "session", "code": code})
        return {"result": reply["result"], "output": reply["output"]}

    def _send(self, request: dict[str, Any]) -> dict[str, Any]:
        path = os.path.expanduser(self.config.socket_path)
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        chunks = []
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(self.config.timeout_seconds)
                sock.connect(path)
                sock.sendall(payload)
                while not chunks or not chunks[-1].endswith(b"\n"):
                    chunk = sock.recv(CHUNK_BYTES)
                    if not chunk:
                        raise PainterConnectionError(
                            "Painter closed the bridge connection before replying. "
                            "Check whether it crashed or quit."
                        )
                    chunks.append(chunk)
        except TimeoutError as exc:
            raise PainterTimeoutError(
                f"Painter did not reply within {self.config.timeout_seconds:g}s. It may "
                "still finish this request; check its state before repeating anything."
            ) from exc
        except OSError as exc:
            raise PainterConnectionError(
                f"Cannot reach Painter's bridge at {path} ({exc}). Open Substance Painter "
                "with painter_bridge.py linked into its python/startup folder."
            ) from exc

        reply = json.loads(b"".join(chunks))
        if not reply["ok"]:
            message = f"{reply['error_type']}: {reply['error']}\n{reply['traceback']}"
            raise PainterScriptError(message.strip())
        return reply
