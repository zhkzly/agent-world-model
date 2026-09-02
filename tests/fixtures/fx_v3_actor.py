from __future__ import annotations

import importlib.util
import json
from pathlib import Path


class CounterEnvironment:
    def __init__(self, instance_directory: Path) -> None:
        self.root = Path(instance_directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"

    def _read(self) -> dict[str, int]:
        if not self.state_path.exists():
            return {"count": 0}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write(self, state: dict[str, int]) -> None:
        self.state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    def reset(self, start: dict[str, int] | None = None) -> dict[str, int]:
        state = {"count": int((start or {}).get("seed", 0))}
        self._write(state)
        return dict(state)

    def tools(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "name": "increment",
                "description": "Increment the persistent counter.",
                "input_schema": {
                    "type": "object",
                    "properties": {"amount": {"type": "integer", "minimum": 1}},
                    "required": ["amount"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
            },
        )

    def invoke(self, tool_name: str, arguments: dict[str, int]) -> dict[str, object]:
        if tool_name != "increment":
            raise ValueError(f"unknown tool {tool_name}")
        state = self._read()
        if int(arguments["amount"]) > 10:
            return {
                "ok": False,
                "data": None,
                "error": {"code": "amount_too_large", "message": "amount exceeds limit"},
            }
        state["count"] += int(arguments["amount"])
        self._write(state)
        return {"ok": True, "data": dict(state), "error": None}

    def close(self) -> None:
        return


def _reject_host_imports() -> None:
    if importlib.util.find_spec("agent_env_foundry") is not None:
        raise RuntimeError("ambient Host package is importable")


def make_environment(instance_directory: Path) -> CounterEnvironment:
    _reject_host_imports()
    return CounterEnvironment(instance_directory)


def read_state(instance_directory: Path) -> dict[str, int]:
    _reject_host_imports()
    path = Path(instance_directory) / "state.json"
    if not path.exists():
        return {"count": 0}
    return json.loads(path.read_text(encoding="utf-8"))
