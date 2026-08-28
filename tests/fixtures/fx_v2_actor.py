from __future__ import annotations

import importlib.util
import json
from pathlib import Path

BEHAVIOR = "__BEHAVIOR__"


class MechanicalEnvironment:
    def __init__(self, instance_directory: Path) -> None:
        self.root = Path(instance_directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"

    def _read(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {"count": 0, "resets": 0, "behavior": BEHAVIOR}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write(self, state: dict[str, object]) -> None:
        self.state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    def reset(self, start: dict[str, object] | None = None) -> dict[str, object]:
        previous = self._read()
        state = {
            "count": int((start or {}).get("seed", 0)),
            "resets": int(previous["resets"]) + 1,
            "behavior": BEHAVIOR,
        }
        self._write(state)
        return dict(state)

    def tools(self) -> tuple[dict[str, object], ...]:
        print("actor-noise-must-not-enter-wire", flush=True)
        return (
            {
                "name": "increment",
                "description": "Increment the persistent counter",
                "input_schema": {
                    "type": "object",
                    "properties": {"amount": {"type": "integer", "minimum": 1}},
                    "required": ["amount"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "behavior": {"type": "string"},
                    },
                    "required": ["count", "behavior"],
                    "additionalProperties": False,
                },
            },
        )

    def invoke(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        if tool_name != "increment":
            raise ValueError(f"unknown tool {tool_name}")
        state = self._read()
        state["count"] = int(state["count"]) + int(arguments["amount"])
        self._write(state)
        return {"ok": True, "data": {"count": state["count"], "behavior": BEHAVIOR}, "error": None}

    def close(self) -> None:
        return


def make_environment(instance_directory: Path) -> MechanicalEnvironment:
    if (
        importlib.util.find_spec("agent_env_foundry") is not None
        or importlib.util.find_spec("preparation") is not None
    ):
        raise RuntimeError("ambient Host package is importable")
    return MechanicalEnvironment(instance_directory)
