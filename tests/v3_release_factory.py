"""Physical EnvironmentRelease/3 fixture with one executable actor project."""

from __future__ import annotations

import json
from pathlib import Path

import agent_env_foundry.environment_semantic_qualification as qualification_module
from agent_env_foundry.conformance_v3 import make_conformance_receipt
from agent_env_foundry.environment_semantic_qualification import (
    SEMANTIC_QUALIFICATION_FORMAT,
    SemanticFinding,
    SemanticQualification,
    make_qualified_conformance_evidence,
)
from agent_env_foundry.project_identity import compute_authored_project_digest
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.release_v3 import ValidatedReleaseV3, publish_release_v3_internal
from agent_env_foundry.research import BuilderProjection


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o644)


def build_actor_project(root: Path) -> Path:
    _write(
        root / "pyproject.toml",
        """[project]
name = "generated-environment"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.29,<0.12.0"]
build-backend = "uv_build"
""",
    )
    _write(
        root / "uv.lock",
        """version = 1
revision = 3
requires-python = ">=3.12, <3.13"

[[package]]
name = "generated-environment"
version = "0.1.0"
source = { editable = "." }
""",
    )
    _write(root / "src/generated_environment/__init__.py", "")
    _write(
        root / "src/generated_environment/release.py",
        (Path(__file__).parent / "fixtures/fx_v3_actor.py").read_text(encoding="utf-8"),
    )
    start, reset, state = v3_schemas()
    _write(root / "docs/schemas/start.json", json.dumps(start))
    _write(root / "docs/schemas/reset.json", json.dumps(reset))
    _write(root / "docs/schemas/state.json", json.dumps(state))
    _write(
        root / "docs/conformance/scenarios.json",
        json.dumps(
            {
                "format": "environment-diagnostics/1",
                "scenarios": [
                    {
                        "scenario_id": "increment-and-refuse",
                        "reset": None,
                        "steps": [
                            {
                                "tool": "increment",
                                "arguments": {"amount": 1},
                                "expected_ok": True,
                                "state_effect": "changed",
                                "expected_error_code": None,
                            },
                            {
                                "tool": "increment",
                                "arguments": {"amount": 99},
                                "expected_ok": False,
                                "state_effect": "unchanged",
                                "expected_error_code": "amount_too_large",
                            },
                        ],
                    }
                ],
            }
        ),
    )
    return root


def v3_schemas() -> tuple[dict, dict, dict]:
    start = {
        "type": "object",
        "properties": {"seed": {"type": "integer"}},
        "additionalProperties": False,
    }
    observation = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    return start, observation, observation


def v3_tools() -> tuple[dict, ...]:
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


def build_v3_release(
    root: Path,
    *,
    receipt_tools: tuple[dict, ...] | None = None,
) -> ValidatedReleaseV3:
    actor = build_actor_project(root / "actor-project")
    actor_digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    start, reset, state = v3_schemas()
    tools = receipt_tools or v3_tools()
    tool_name = tools[0]["name"]
    diagnostic_evidence = (
        {
            "scenario_id": "fixture",
            "reset": {
                "evidence_ref": "fixture:reset",
                "reset_observation": {"count": 0},
                "initial_state": {"count": 0},
            },
            "steps": [
                {
                    "evidence_ref": "fixture:step:0",
                    "tool": tool_name,
                    "arguments": {"amount": 1},
                    "observation": {"ok": True, "data": {"count": 1}, "error": None},
                    "before_state": {"count": 0},
                    "after_state": {"count": 1},
                },
                {
                    "evidence_ref": "fixture:step:1",
                    "tool": tool_name,
                    "arguments": {"amount": 99},
                    "observation": {
                        "ok": False,
                        "data": None,
                        "error": {"code": "amount_too_large", "message": "too large"},
                    },
                    "before_state": {"count": 1},
                    "after_state": {"count": 1},
                },
            ],
            "final_state": {"count": 1},
        },
    )
    projection = BuilderProjection(
        frozen_need={"original_need": "Increment a persistent counter.", "clauses": []},
        selected_world={"scope": "counter"},
        requirements=(
            {
                "id": "REQ-001",
                "kind": "workflows",
                "state_relation": "A valid increment changes persistent count.",
                "observable_relation": "The new count is returned.",
                "falsifiable_consequence": "Count does not change.",
            },
            {
                "id": "REQ-002",
                "kind": "refusals",
                "state_relation": "An excessive increment is refused without mutation.",
                "observable_relation": "A stable error code is returned.",
                "falsifiable_consequence": "The refusal changes count.",
            },
        ),
        initial_world_relations=(),
        cited_evidence=(),
    )
    normalized_tools = qualification_module._normalized_tools(tools)
    review_inputs = [
        qualification_module._review_input(
            projection,
            normalized_tools,
            diagnostic_evidence,
            requirement_ids=group,
        )
        for group in qualification_module._requirement_groups(projection)
    ]
    qualification = SemanticQualification(
        SEMANTIC_QUALIFICATION_FORMAT,
        actor_digest,
        sha256_hex(canonical_bytes(projection.to_document())),
        sha256_hex(canonical_bytes(review_inputs)),
        sha256_hex(canonical_bytes(list(diagnostic_evidence))),
        "fixture-reviewer",
        sha256_hex(qualification_module._PROMPT.encode("utf-8")),
        2,
        (None, None),
        (
            SemanticFinding("REQ-001", "satisfied", ("fixture:step:0",), "observed"),
            SemanticFinding("REQ-002", "satisfied", ("fixture:step:1",), "observed"),
        ),
    )
    physical_evidence = {
        "format": "environment-conformance-evidence/3",
        "actor_project_digest": actor_digest,
        "builder_checks": [],
        "host_checks": {
            "public_tool_specs": [dict(item) for item in normalized_tools],
            "diagnostic_evidence": list(diagnostic_evidence),
        },
    }
    evidence = make_qualified_conformance_evidence(
        physical_evidence,
        projection=projection,
        tool_specs=normalized_tools,
        diagnostic_evidence=diagnostic_evidence,
        qualification=qualification,
    )
    receipt = make_conformance_receipt(
        actor_project_digest=actor_digest,
        actor_factory="generated_environment.release:make_environment",
        state_reader_factory="generated_environment.release:read_state",
        start_schema=start,
        reset_observation_schema=reset,
        state_schema=state,
        tool_specs=normalized_tools,
        evidence=evidence,
    )
    return publish_release_v3_internal(
        root / "EnvironmentRelease",
        actor_project=actor,
        receipt=receipt,
        evidence=evidence,
        start_schema=start,
        reset_observation_schema=reset,
        state_schema=state,
    )


__all__ = ["build_actor_project", "build_v3_release", "v3_schemas", "v3_tools"]
