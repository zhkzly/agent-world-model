from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from openai_codex import ApprovalMode, Sandbox

import agent_env_foundry.semantics_author as semantics_author_module
from agent_env_foundry.author_finding import AuthorFinding
from agent_env_foundry.builder import BuilderConfig, CommandResult, compute_candidate_digest
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.semantics import capability_from_document, validate_catalog
from agent_env_foundry.semantics_author import (
    SemanticsAuthorFailure,
    SemanticsBuild,
    compute_semantics_project_digest,
    repair_semantics_author,
    run_semantics_author,
)
from agent_env_foundry.semantics_inputs import (
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    TASK_SEMANTICS_CONTRACT_NAME,
    TASK_SEMANTICS_WIRE_NAME,
    VIEW_MANIFEST_NAME,
    CandidateViewManifest,
    PreparedSemanticsAuthorWorkspace,
    prepare_semantics_author_workspace,
)
from agent_env_foundry.semantics_wire import semantics_wire_document


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _surface() -> PublicSurfaceManifest:
    return PublicSurfaceManifest(
        start_schema={"type": "object"},
        reset_observation_schema={"type": "object"},
        tool_specs=(),
        public_documents_digest="b" * 64,
    )


def test_host_stages_exact_v2_semantics_inputs_and_actor_view(tmp_path: Path) -> None:
    actor = tmp_path / "actor"
    source = actor / "src/generated_environment/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_environment(path):\n    return object()\n")
    (actor / "pyproject.toml").write_text("[project]\nname='actor'\nversion='0.1.0'\n")
    (actor / "uv.lock").write_text("version = 1\n")
    actor_digest = compute_candidate_digest(actor)
    expected = b'{"format":"expected-task-semantics/1"}'

    prepared = prepare_semantics_author_workspace(
        tmp_path / "prepared",
        actor_root=actor,
        actor_digest=actor_digest,
        expected_semantics_payload=expected,
        expected_semantics_digest=_sha(expected),
        public_surface=_surface(),
    )

    prepared.verify_inputs()
    assert json.loads((prepared.root / PUBLIC_SURFACE_NAME).read_text())["format"] == (
        "public-surface/2"
    )
    assert (prepared.root / "candidate-view/src/generated_environment/release.py").is_file()
    assert not (prepared.root / "VERIFIER_PROJECT").exists()

    with pytest.raises(ValueError, match="Actor project digest"):
        prepare_semantics_author_workspace(
            tmp_path / "bad",
            actor_root=actor,
            actor_digest="0" * 64,
            expected_semantics_payload=expected,
            expected_semantics_digest=_sha(expected),
            public_surface=_surface(),
        )


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
                    "qualification_goal": (
                        "Increase the selected counter and report the resulting public value."
                    ),
                    "answer_fields": [],
                }
            ],
            "composition_rules": [],
            "conditions": [],
        },
        PUBLIC_SURFACE_NAME: _surface().to_document(),
        TASK_SEMANTICS_WIRE_NAME: semantics_wire_document(),
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
    assert observed["thread"]["sandbox"] is Sandbox.full_access
    assert set(observed["config"].env) == {"CODEX_HOME", "HOME", "UV_CACHE_DIR"}
    assert Path(observed["config"].env["HOME"]).parent == result.codex_home
    assert Path(observed["config"].env["HOME"]).is_dir()
    instructions = observed["thread"]["base_instructions"]
    assert "Do not write manifests, digests, verdicts, Tasks, rewards" in instructions
    assert "write the tasksemantics project" in observed["prompt"].casefold()
    assert "verdict" not in observed["prompt"].casefold()
    assert stat.S_IMODE((workspace.root / PUBLIC_SURFACE_NAME).stat().st_mode) == 0o444
    workspace.verify_inputs()


def test_task_semantics_contract_separates_initial_truth_from_eligibility() -> None:
    contract = (
        Path(__file__).resolve().parents[1]
        / "src/agent_env_foundry/runtime_skills/task-semantics-codegen/"
        "TASK_SEMANTICS_CONTRACT.md"
    ).read_text()

    assert "entire Task goal" in contract
    assert "not capability eligibility" in contract
    assert "`public_sources` is an array" in contract
    assert 'field_pointer="/public_descriptor/charge_reference"' in contract
    assert "exactly the declared answer field IDs" in contract
    assert "`null`" in contract
    assert "native refusal relation" in contract
    assert "`required_effects_ok=true` and `collateral_ok=true`" in contract
    assert "every process/refusal capability" in contract
    assert "unscoped enumeration" in contract
    assert "Do not pre-filter the complete trace by target arguments" in contract


def test_semantics_repair_binds_same_thread_current_digest_and_typed_finding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_task_semantics/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("VERSION = 1\ndef make_semantics():\n    return object()\n")
    codex_home = tmp_path / "semantics-codex-home"
    codex_home.mkdir()
    finding = AuthorFinding(
        source="native_physical_check",
        code="COLLATERAL_AXIS_MISMATCH",
        condition="selected required effect is not collateral",
        expected=True,
        actual=False,
        decisive_inputs={"capability_id": "CAP-002"},
    )
    changed = SemanticsBuild(
        workspace.root,
        "same-thread",
        codex_home,
        "generated_task_semantics.release:make_semantics",
        "0" * 64,
        (),
    )
    with pytest.raises(SemanticsAuthorFailure) as digest_error:
        repair_semantics_author(
            workspace,
            changed,
            (finding,),
            config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "cache"),
        )
    assert digest_error.value.code == "semantics_author_digest_mismatch"

    observed: dict[str, Any] = {}

    class Thread:
        id = "same-thread"

        def run(self, prompt: str) -> None:
            observed["prompt"] = prompt
            source.write_text("VERSION = 2\ndef make_semantics():\n    return object()\n")

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            del config

        def __enter__(self) -> FakeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def thread_resume(self, thread_id: str, **kwargs: Any) -> Thread:
            del kwargs
            observed["thread_id"] = thread_id
            return Thread()

    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(semantics_author_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        semantics_author_module,
        "run_semantics_checks",
        lambda *_args, **_kwargs: (CommandResult("host", ("host",), 0, "passed", ""),),
    )
    build = replace(changed, project_digest=compute_semantics_project_digest(workspace.root))

    repaired = repair_semantics_author(
        workspace,
        build,
        (finding,),
        config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "cache"),
    )

    assert observed["thread_id"] == "same-thread"
    assert "COLLATERAL_AXIS_MISMATCH" in observed["prompt"]
    assert repaired.project_digest != build.project_digest


def test_semantics_digest_binds_file_mode(tmp_path: Path) -> None:
    source = tmp_path / "src/generated_task_semantics/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_semantics():\n    return object()\n")
    source.chmod(0o644)
    first = compute_semantics_project_digest(tmp_path)

    source.chmod(0o755)

    assert compute_semantics_project_digest(tmp_path) != first


def test_framework_rejects_actor_or_host_imports_in_semantics_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_task_semantics/release.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import generated_environment\n"
        "import generated_qualification_verifier\n"
        "import agent_env_foundry\n"
    )

    result = semantics_author_module._source_check(workspace.root)

    assert not result.passed
    assert "forbidden_import:generated_environment" in result.stderr
    assert "forbidden_import:generated_qualification_verifier" in result.stderr
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


def test_frozen_catalog_feedback_reports_every_capability_field_together(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    expected = json.loads((workspace.root / EXPECTED_TASK_SEMANTICS_NAME).read_text())
    capability = capability_from_document(
        {
            "capability_id": "increment",
            "requirement_ids": ["REQ-001"],
            "workflow_ids": ["other-workflow"],
            "composition_rules": [],
            "actor_role": "operator",
            "task_kind": "state_change",
            "intent_label": "increment the counter",
            "protected_binding_schema": {"type": "object", "additionalProperties": True},
            "public_descriptor_schema": {"type": "object", "additionalProperties": True},
            "facets": [],
            "conditions": [],
            "answer_fields": [
                {
                    "field_id": "unexpected",
                    "schema": {"type": "string"},
                    "public_label": "Unexpected",
                    "public_source": {
                        "kind": "task_literal",
                        "tool_name": None,
                        "json_pointer": None,
                        "value": None,
                    },
                }
            ],
            "supported_goal_kinds": ["atom"],
            "rendering": {
                "imperative": "increment",
                "target_noun": "counter",
                "answer_phrase": None,
            },
        }
    )
    catalog = validate_catalog((capability,))

    with pytest.raises(ValueError) as caught:
        semantics_author_module._align_expected_catalog(expected, catalog)

    message = str(caught.value)
    assert "workflow_ids" in message
    assert "answer_fields" in message


def test_runtime_import_probe_requires_own_source_and_rejects_actor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    own = workspace.root / "src/generated_task_semantics/__init__.py"
    actor = tmp_path / "actor/generated_environment/__init__.py"
    verifier = tmp_path / "verifier/generated_qualification_verifier/__init__.py"

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
            if module == "generated_environment"
            else verifier
            if module == "generated_qualification_verifier"
            else None
        ),
    )
    rejected = semantics_author_module._import_separation_check(workspace, config)
    assert not rejected.passed
    assert "generated_environment" in rejected.stderr
    assert "generated_qualification_verifier" in rejected.stderr


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
