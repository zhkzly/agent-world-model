from __future__ import annotations

import importlib.util
import json
from pathlib import Path

BEHAVIOR = "__BEHAVIOR__"
MUTATE = False
RAISE_AFTER_MUTATION = False
BROKEN_STARTUP = False


class MechanicalSemantics:
    def start_cases(self, seed: int, limit: int):
        return [{"case_id": "case-1", "reset_input": {"seed": seed}, "regime_tags": ["baseline"]}][
            :limit
        ]

    def inspect(self, instance_directory: Path):
        root = Path(instance_directory)
        if MUTATE:
            (root / "semantics-mutated").write_text("bad", encoding="utf-8")
            if RAISE_AFTER_MUTATION:
                raise RuntimeError("mutated then failed")
        state = root / "state.json"
        return (
            json.loads(state.read_text(encoding="utf-8"))
            if state.exists()
            else {"count": 0, "resets": 0, "behavior": BEHAVIOR}
        )

    def capabilities(self):
        print("semantics-noise-must-not-enter-wire", flush=True)
        return [
            {
                "capability_id": "increment",
                "requirement_ids": ["REQ-1"],
                "workflow_ids": ["counter"],
                "composition_rules": [],
                "actor_role": "operator",
                "task_kind": "state_change",
                "intent_label": "increment the counter",
                "protected_binding_schema": {"type": "object", "additionalProperties": True},
                "public_descriptor_schema": {"type": "object", "additionalProperties": True},
                "facets": [
                    {
                        "name": "name",
                        "public_label": "name",
                        "value_schema": {"type": "string"},
                        "allowed_operators": ["eq"],
                    }
                ],
                "conditions": [],
                "answer_fields": [
                    {
                        "field_id": "count",
                        "schema": {"type": "integer"},
                        "public_label": "count",
                        "public_source": {
                            "kind": "tool_output",
                            "tool_name": "increment",
                            "json_pointer": "/count",
                            "value": None,
                        },
                    }
                ],
                "supported_goal_kinds": ["atom"],
                "rendering": {
                    "imperative": "increment",
                    "target_noun": "counter",
                    "answer_phrase": "report count",
                },
            }
        ]

    def enumerate_bindings(self, capability_id: str, facts):
        return [
            {
                "semantic_key": "counter",
                "eligible": True,
                "reason_codes": [],
                "protected_binding": {"key": "counter"},
                "public_descriptor": {"name": "counter"},
                "facets": {"name": "counter"},
                "public_sources": [
                    {
                        "field_pointer": "/public_descriptor/name",
                        "source": {
                            "kind": "task_literal",
                            "tool_name": None,
                            "json_pointer": None,
                            "value": "counter",
                        },
                    },
                    {
                        "field_pointer": "/facets/name",
                        "source": {
                            "kind": "task_literal",
                            "tool_name": None,
                            "json_pointer": None,
                            "value": "counter",
                        },
                    },
                ],
            }
        ]

    def evaluate_atom(self, request):
        before = int(request["before_facts"].get("count", 0))
        after = int(request["after_facts"].get("count", 0))
        ok = after > before
        return {
            "initially_satisfied": False,
            "satisfied": ok,
            "required_effects_ok": ok,
            "collateral_ok": True,
            "answer_ok": True,
            "process_ok": None,
            "report_values": {"count": after},
            "failure_codes": [] if ok else ["not_incremented"],
        }

    def evaluate_condition(self, request):
        return {"status": "true", "report_values": {"behavior": BEHAVIOR}, "failure_codes": []}


def make_semantics() -> MechanicalSemantics:
    if (
        importlib.util.find_spec("agent_env_foundry") is not None
        or importlib.util.find_spec("preparation") is not None
    ):
        raise RuntimeError("ambient Host package is importable")
    if BROKEN_STARTUP:
        raise RuntimeError("semantics startup failed")
    return MechanicalSemantics()
