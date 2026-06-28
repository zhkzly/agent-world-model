from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent_world.online_runtime import RuntimeAction, load_online_runtime


class RuntimeHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], package_dir: Path):
        self.package_dir = Path(package_dir)
        self.runtime = load_online_runtime(self.package_dir)
        self.runtime.start()
        self.sessions: dict[str, Any] = {}
        super().__init__(server_address, RuntimeRequestHandler)

    def server_close(self) -> None:
        try:
            self.runtime.close()
        finally:
            super().server_close()


class RuntimeRequestHandler(BaseHTTPRequestHandler):
    server: RuntimeHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "package_dir": str(self.server.package_dir),
                    "started": self.server.runtime.started,
                    "sessions": sorted(self.server.sessions),
                },
            )
            return
        if self.path == "/runtime":
            self._send_json(
                200,
                {
                    "contract": "OnlineEnvRuntime",
                    "endpoints": ["/health", "/runtime", "/reset", "/observe", "/step", "/finalize"],
                },
            )
            return
        self._send_json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/reset":
                task_id = str(payload["task_id"])
                run_id = payload.get("run_id")
                session = self.server.runtime.reset(task_id, run_id=str(run_id) if run_id else None)
                self.server.sessions[session.session_id] = session
                self._send_json(200, {"session_id": session.session_id, "observation": session.observe().to_dict()})
                return
            if self.path == "/observe":
                session = self._session(payload)
                self._send_json(200, {"session_id": session.session_id, "observation": session.observe().to_dict()})
                return
            if self.path == "/step":
                session = self._session(payload)
                action_payload = payload.get("action", {})
                action = RuntimeAction(
                    action_id=str(action_payload.get("action_id", f"http-step-{session._step_index}")),
                    kind=str(action_payload.get("kind", "tool_call")),
                    tool_name=str(action_payload.get("tool_name", "")),
                    arguments=dict(action_payload.get("arguments", {})),
                    raw_model_output=str(action_payload.get("raw_model_output", "")),
                    metadata=dict(action_payload.get("metadata", {})),
                )
                self._send_json(200, {"session_id": session.session_id, "step": session.step(action).to_dict()})
                return
            if self.path == "/finalize":
                session = self._session(payload)
                final = session.finalize(payload.get("answer"))
                self._send_json(200, {"session_id": session.session_id, "final": final.to_dict()})
                return
            self._send_json(404, {"error": "not_found", "path": self.path})
        except KeyError as exc:
            self._send_json(400, {"error": "missing_field", "field": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": exc.__class__.__name__, "message": str(exc)})

    def _session(self, payload: dict[str, Any]) -> Any:
        session_id = str(payload["session_id"])
        if session_id not in self.server.sessions:
            raise KeyError(f"unknown session_id: {session_id}")
        return self.server.sessions[session_id]

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def create_http_server(package_dir: Path, *, host: str = "127.0.0.1", port: int = 8000) -> RuntimeHTTPServer:
    return RuntimeHTTPServer((host, port), Path(package_dir))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = create_http_server(args.package, host=args.host, port=args.port)
    host, port = server.server_address
    print(f"agent-world HTTP runtime serving {args.package} at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
