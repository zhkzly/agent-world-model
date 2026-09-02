from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_env_foundry.builder import CandidateBuild, CommandResult
from agent_env_foundry.environment_conformance_v3 import (
    _replay_projection,
    run_environment_conformance_v3_internal,
)
from agent_env_foundry.preparation_v3 import (
    PreparationExecutionErrorV3,
    PreparationSettingsV3,
)
from agent_env_foundry.project_identity import compute_authored_project_digest
from v3_release_factory import build_actor_project


def _settings() -> PreparationSettingsV3:
    return PreparationSettingsV3(
        Path(os.environ.get("UV_CACHE_DIR", "/tmp/foundry-v3-runtime-uv-cache")),
        120.0,
    )


def _candidate(root: Path, *, phases: tuple[str, ...] | None = None) -> CandidateBuild:
    actor = build_actor_project(root)
    digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    selected = phases or (
        "lock",
        "sync",
        "build",
        "tests",
        "public_contract",
        "source_determinism",
        "live_contract",
    )
    checks = tuple(CommandResult(phase, ("physical", phase), 0, "passed", "") for phase in selected)
    return CandidateBuild(actor, "fixture-thread", digest, "fixture", checks)


def test_v3_conformance_issues_host_receipt_from_physical_actor(tmp_path: Path) -> None:
    conformed = run_environment_conformance_v3_internal(
        _candidate(tmp_path / "actor"),
        tmp_path / "runtime",
        settings=_settings(),
    )

    assert conformed.receipt.verdict == "passed"
    assert conformed.receipt.actor_project_digest
    assert conformed.receipt.evidence_digest
    assert tuple(item["name"] for item in conformed.tool_specs) == ("increment",)
    host = conformed.evidence["host_checks"]
    assert isinstance(host, dict)
    assert host["reopen_persistence"] is True
    assert host["controlled_reset_replay"] is True
    assert host["instance_isolation"] is True
    assert host["public_tool_specs"] == [dict(item) for item in conformed.tool_specs]
    assert host["diagnostic_results"] == [
        {
            "scenario_id": "increment-and-refuse",
            "step_count": 2,
            "trace_digest": host["diagnostic_results"][0]["trace_digest"],
        }
    ]
    assert list(conformed.diagnostic_evidence) == host["diagnostic_evidence"]
    scenario = conformed.diagnostic_evidence[0]
    assert scenario["reset"]["evidence_ref"] == "increment-and-refuse:reset"
    assert [item["evidence_ref"] for item in scenario["steps"]] == [
        "increment-and-refuse:step:0",
        "increment-and-refuse:step:1",
    ]
    assert scenario["steps"][0]["state_after_reopen"] == {"count": 1}
    assert [item["evidence_ref"] for item in scenario["lifecycle"]] == [
        "increment-and-refuse:reopen",
        "increment-and-refuse:reset-after-actions",
    ]
    assert scenario["lifecycle"][0]["before_state"] == {"count": 1}
    assert scenario["lifecycle"][0]["after_state"] == {"count": 1}
    assert scenario["lifecycle"][1]["after_state"] == {"count": 0}
    reviewer_evidence = json.dumps(conformed.diagnostic_evidence)
    assert "expected_ok" not in reviewer_evidence
    assert "state_effect" not in reviewer_evidence
    assert "expected_error_code" not in reviewer_evidence


def test_v3_conformance_rejects_incomplete_builder_evidence(tmp_path: Path) -> None:
    with pytest.raises(PreparationExecutionErrorV3) as caught:
        run_environment_conformance_v3_internal(
            _candidate(tmp_path / "actor", phases=("tests",)),
            tmp_path / "runtime",
            settings=_settings(),
        )
    assert caught.value.code == "builder_evidence_incomplete"


def test_replay_projection_normalizes_only_the_host_instance_locator(tmp_path: Path) -> None:
    instance = tmp_path / "instance-a"
    value = {
        "root": str(instance),
        "file": str(instance / "src/app.py"),
        "similar_but_external": str(tmp_path / "instance-ab/file.txt"),
        "nested": [str(instance / "README.md"), 3],
    }

    assert _replay_projection(value, instance) == {
        "root": "<INSTANCE_ROOT>",
        "file": "<INSTANCE_ROOT>/src/app.py",
        "similar_but_external": str(tmp_path / "instance-ab/file.txt"),
        "nested": ["<INSTANCE_ROOT>/README.md", 3],
    }


def test_v3_diagnostic_runner_rejects_refusal_state_mutation(tmp_path: Path) -> None:
    actor = build_actor_project(tmp_path / "actor")
    source_path = actor / "src/generated_environment/release.py"
    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(
        source.replace(
            'if int(arguments["amount"]) > 10:\n            return {',
            'if int(arguments["amount"]) > 10:\n'
            '            self._write({"count": state["count"] + 1})\n'
            "            return {",
        ),
        encoding="utf-8",
    )
    digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    phases = (
        "lock",
        "sync",
        "build",
        "tests",
        "public_contract",
        "source_determinism",
        "live_contract",
    )
    checks = tuple(CommandResult(phase, ("physical", phase), 0, "passed", "") for phase in phases)

    with pytest.raises(PreparationExecutionErrorV3) as caught:
        run_environment_conformance_v3_internal(
            CandidateBuild(actor, "fixture-thread", digest, "fixture", checks),
            tmp_path / "runtime",
            settings=_settings(),
        )

    assert caught.value.code == "diagnostic_state_effect_mismatch"


def test_v3_diagnostic_runner_rejects_instance_derived_replay_state(tmp_path: Path) -> None:
    actor = build_actor_project(tmp_path / "actor")
    source_path = actor / "src/generated_environment/release.py"
    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(
        source.replace("import importlib.util", "import hashlib\nimport importlib.util")
        .replace(
            'state["count"] += int(arguments["amount"])\n        self._write(state)',
            'state["count"] += int(arguments["amount"])\n'
            '        state["nonce"] = hashlib.sha256(str(self.root).encode()).hexdigest()\n'
            "        self._write(state)",
        )
        .replace(
            '"data": dict(state)',
            '"data": {"count": state["count"]}',
        ),
        encoding="utf-8",
    )
    state_schema_path = actor / "docs/schemas/state.json"
    state_schema = json.loads(state_schema_path.read_text(encoding="utf-8"))
    state_schema["properties"]["nonce"] = {"type": "string"}
    state_schema_path.write_text(json.dumps(state_schema), encoding="utf-8")
    digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    phases = (
        "lock",
        "sync",
        "build",
        "tests",
        "public_contract",
        "source_determinism",
        "live_contract",
    )
    checks = tuple(CommandResult(phase, ("physical", phase), 0, "passed", "") for phase in phases)

    with pytest.raises(PreparationExecutionErrorV3) as caught:
        run_environment_conformance_v3_internal(
            CandidateBuild(actor, "fixture-thread", digest, "fixture", checks),
            tmp_path / "runtime",
            settings=_settings(),
        )

    assert caught.value.code == "diagnostic_replay_drift"


def test_v3_diagnostic_runner_rejects_reset_that_keeps_prior_mutation(
    tmp_path: Path,
) -> None:
    actor = build_actor_project(tmp_path / "actor")
    source_path = actor / "src/generated_environment/release.py"
    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(
        source.replace(
            'state = {"count": int((start or {}).get("seed", 0))}\n'
            "        self._write(state)\n"
            "        return dict(state)",
            "if self.state_path.exists():\n"
            "            return self._read()\n"
            '        state = {"count": int((start or {}).get("seed", 0))}\n'
            "        self._write(state)\n"
            "        return dict(state)",
        ),
        encoding="utf-8",
    )
    digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    phases = (
        "lock",
        "sync",
        "build",
        "tests",
        "public_contract",
        "source_determinism",
        "live_contract",
    )
    checks = tuple(CommandResult(phase, ("physical", phase), 0, "passed", "") for phase in phases)

    with pytest.raises(PreparationExecutionErrorV3) as caught:
        run_environment_conformance_v3_internal(
            CandidateBuild(actor, "fixture-thread", digest, "fixture", checks),
            tmp_path / "runtime",
            settings=_settings(),
        )

    assert caught.value.code == "diagnostic_reset_restoration"
