from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest
from openai_codex import ApprovalMode

import agent_env_foundry.semantics_author as semantics_author_module
from agent_env_foundry.builder import (
    BuilderConfig,
    CommandResult,
    _codex_workspace_permission_overrides,
)
from agent_env_foundry.qualification import (
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    TASK_SEMANTICS_CONTRACT_NAME,
    VIEW_MANIFEST_NAME,
    CandidateViewManifest,
    PreparedSemanticsAuthorWorkspace,
)
from agent_env_foundry.semantics import StartCase, capability_from_document, validate_catalog
from agent_env_foundry.semantics_author import SemanticsAuthorFailure, run_semantics_author


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _workspace(tmp_path: Path) -> PreparedSemanticsAuthorWorkspace:
    root = tmp_path / "semantics-author"
    root.mkdir()
    view = root / "candidate-view"
    view.mkdir()
    view.chmod(0o555)
    manifest = CandidateViewManifest("a" * 64, (), _sha(b"empty-view"))
    documents = {
        EXPECTED_TASK_SEMANTICS_NAME: {
            "format": "expected-task-semantics/1",
            "requirements": [
                {
                    "requirement_id": "REQ-001",
                    "disposition": "Taskable",
                    "rationale": "public state change",
                    "preconditions": ["world exists"],
                    "outcomes": ["count increases"],
                    "refusals": [],
                    "collateral_constraints": [],
                    "workflow_ids": ["counter"],
                }
            ],
            "capabilities": [
                {
                    "capability_id": "increment",
                    "requirement_ids": ["REQ-001"],
                    "workflow_ids": ["counter"],
                    "actor_role": "operator",
                    "task_kind": "state_change",
                    "intent_label": "increment the counter",
                    "answer_fields": [],
                }
            ],
            "composition_rules": [],
            "conditions": [],
        },
        PUBLIC_SURFACE_NAME: {
            "format": "public-surface/1",
            "candidate_digest": "a" * 64,
            "candidate_view_digest": manifest.view_digest,
            "actor_factory": "generated_actor.release:make_environment",
            "start_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "reset_observation_schema": {"type": "object"},
            "tool_specs": [],
            "public_probe_facts": [],
            "public_documents": [],
        },
    }
    inputs: dict[str, str] = {}
    for name, document in documents.items():
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o444)
        inputs[name] = _sha(payload)
    contract = root / TASK_SEMANTICS_CONTRACT_NAME
    contract.write_text("immutable TaskSemantics contract\n")
    contract.chmod(0o444)
    inputs[TASK_SEMANTICS_CONTRACT_NAME] = _sha(contract.read_bytes())
    manifest_path = root / VIEW_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "format": "candidate-view/1",
                "candidate_digest": manifest.candidate_digest,
                "files": [],
                "view_digest": manifest.view_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    manifest_path.chmod(0o444)
    inputs[VIEW_MANIFEST_NAME] = _sha(manifest_path.read_bytes())
    return PreparedSemanticsAuthorWorkspace(root, inputs, manifest)


def test_run_semantics_author_uses_codex_only_for_semantic_project_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    observed: dict[str, Any] = {}

    class Result:
        final_response = "model narrative is not a verdict"

    class Thread:
        id = "semantics-thread"

        def run(self, prompt: str) -> Result:
            observed["prompt"] = prompt
            assert (workspace.root / "pyproject.toml").is_file()
            source = workspace.root / "src/generated_task_semantics/release.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("def make_semantics():\n    return object()\n")
            return Result()

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            observed["config"] = config

        def __enter__(self) -> FakeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def thread_start(self, **kwargs: Any) -> Thread:
            observed["thread"] = kwargs
            return Thread()

    monkeypatch.setattr(semantics_author_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        semantics_author_module,
        "run_semantics_checks",
        lambda *_args, **_kwargs: (CommandResult("host_checks", ("host",), 0, "passed", ""),),
    )

    result = run_semantics_author(
        workspace,
        config=BuilderConfig(
            max_turns=1,
            uv_cache_dir=tmp_path / "uv-cache",
        ),
    )

    assert result.thread_id == "semantics-thread"
    assert result.codex_home.is_dir()
    assert result.factory == "generated_task_semantics.release:make_semantics"
    assert result.project_digest
    assert observed["thread"]["approval_mode"] is ApprovalMode.deny_all
    assert "sandbox" not in observed["thread"]
    assert set(observed["config"].env) == {"CODEX_HOME", "HOME", "UV_CACHE_DIR"}
    assert Path(observed["config"].env["HOME"]).parent == result.codex_home
    assert Path(observed["config"].env["HOME"]).is_dir()
    assert observed["config"].config_overrides[-4:] == _codex_workspace_permission_overrides(
        "foundry_semantics",
        workspace.root,
    )
    instructions = observed["thread"]["base_instructions"]
    assert "Do not write manifests, digests, verdicts, Tasks, rewards" in instructions
    assert "write the tasksemantics project" in observed["prompt"].casefold()
    assert "verdict" not in observed["prompt"].casefold()
    assert stat.S_IMODE((workspace.root / PUBLIC_SURFACE_NAME).stat().st_mode) == 0o444
    workspace.verify_inputs()


def test_framework_rejects_actor_or_host_imports_in_semantics_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_task_semantics/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("import generated_actor\nimport agent_env_foundry\n")

    result = semantics_author_module._source_check(workspace.root)

    assert not result.passed
    assert "forbidden_import:generated_actor" in result.stderr
    assert "forbidden_import:agent_env_foundry" in result.stderr


def test_framework_compares_generated_catalog_to_frozen_semantics(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    expected = json.loads((workspace.root / EXPECTED_TASK_SEMANTICS_NAME).read_text())
    capability = capability_from_document(
        {
            "capability_id": "increment",
            "requirement_ids": ["REQ-001"],
            "workflow_ids": ["counter"],
            "composition_rules": [],
            "actor_role": "operator",
            "task_kind": "state_change",
            "intent_label": "increment the counter",
            "protected_binding_schema": {"type": "object", "additionalProperties": True},
            "public_descriptor_schema": {"type": "object", "additionalProperties": True},
            "facets": [],
            "conditions": [],
            "answer_fields": [],
            "read_scopes": ["counter"],
            "write_scopes": ["counter"],
            "supported_goal_kinds": ["atom"],
            "rendering": {
                "imperative": "increment",
                "target_noun": "counter",
                "answer_phrase": None,
            },
        }
    )
    catalog = validate_catalog((capability,))
    semantics_author_module._align_expected_catalog(expected, catalog)

    expected["capabilities"][0]["task_kind"] = "query"
    with pytest.raises(ValueError, match="task_kind"):
        semantics_author_module._align_expected_catalog(expected, catalog)

    expected["capabilities"][0]["task_kind"] = "state_change"
    expected["capabilities"][0]["answer_fields"] = [
        {"field_id": "unexpected", "public_label": "Unexpected"}
    ]
    with pytest.raises(ValueError, match="answer_fields"):
        semantics_author_module._align_expected_catalog(expected, catalog)


def test_runtime_import_probe_requires_own_source_and_rejects_actor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    own = workspace.root / "src/generated_task_semantics/__init__.py"
    actor = tmp_path / "actor/generated_actor/__init__.py"

    def clean_probe(python: Path, project: Path, module: str, timeout: float) -> Path | None:
        del python, project, timeout
        return own if module == "generated_task_semantics" else None

    monkeypatch.setattr(semantics_author_module, "_probe_origin", clean_probe)
    config = BuilderConfig(uv_cache_dir=tmp_path / "cache")
    assert semantics_author_module._import_separation_check(workspace, config).passed

    monkeypatch.setattr(
        semantics_author_module,
        "_probe_origin",
        lambda _python, _project, module, _timeout: (
            own
            if module == "generated_task_semantics"
            else actor
            if module == "generated_actor"
            else None
        ),
    )
    rejected = semantics_author_module._import_separation_check(workspace, config)
    assert not rejected.passed
    assert "generated_actor" in rejected.stderr


def test_start_cases_cover_real_public_reset_inputs() -> None:
    public = {
        "public_probe_facts": [
            {"operation": "reset", "arguments": {"start": None}},
            {
                "operation": "reset",
                "arguments": {"start": {"now": "2025-01-05T08:30:00Z"}},
            },
        ]
    }
    with pytest.raises(ValueError, match="public reset inputs"):
        semantics_author_module._validate_start_case_coverage(
            (StartCase("baseline", None, ("baseline",)),),
            public,
        )

    semantics_author_module._validate_start_case_coverage(
        (
            StartCase("baseline", None, ("baseline",)),
            StartCase(
                "early",
                {"now": "2025-01-05T08:30:00Z"},
                ("early-clock",),
            ),
        ),
        public,
    )


def test_model_completion_text_cannot_override_failed_framework_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    class Result:
        final_response = "done and passed"

    class Thread:
        id = "untrusted-thread"

        def run(self, prompt: str) -> Result:
            del prompt
            source = workspace.root / "src/generated_task_semantics/release.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("def make_semantics():\n    return object()\n")
            return Result()

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            del config

        def __enter__(self) -> FakeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def thread_start(self, **kwargs: Any) -> Thread:
            del kwargs
            return Thread()

    monkeypatch.setattr(semantics_author_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        semantics_author_module,
        "run_semantics_checks",
        lambda *_args, **_kwargs: (
            CommandResult("semantics_contract", ("host",), 1, "", "catalog mismatch"),
        ),
    )

    with pytest.raises(SemanticsAuthorFailure) as caught:
        run_semantics_author(
            workspace,
            config=BuilderConfig(
                max_turns=1,
                uv_cache_dir=tmp_path / "uv-cache",
            ),
        )

    assert caught.value.code == "semantics_author_turns_exhausted"
