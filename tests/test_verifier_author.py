from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from openai_codex import ApprovalMode, Sandbox

import agent_env_foundry.verifier_author as verifier_author_module
from agent_env_foundry.builder import BuilderConfig, CommandResult
from agent_env_foundry.qualification_contracts import NativeVerificationRequest
from agent_env_foundry.semantics import TraceEvent
from agent_env_foundry.verifier_author import (
    VERIFIER_FACTORY,
    VerifierAuthorFailure,
    VerifierAuthorFinding,
    VerifierBuild,
    compute_verifier_project_digest,
    invoke_verifier_transition,
    repair_verifier_author,
    run_verifier_author,
)
from test_verifier_inputs import _workspace


def test_run_verifier_author_uses_one_fresh_codex_project_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    observed: dict[str, Any] = {}

    class Result:
        final_response = "narrative is not a verdict"

    class Thread:
        id = "verifier-thread"

        def run(self, prompt: str) -> Result:
            observed["prompt"] = prompt
            source = workspace.root / "src/generated_qualification_verifier/release.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("def make_verifier():\n    return object()\n")
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

    monkeypatch.setattr(verifier_author_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        verifier_author_module,
        "run_verifier_checks",
        lambda *_args, **_kwargs: (CommandResult("host_checks", ("host",), 0, "passed", ""),),
    )

    build = run_verifier_author(
        workspace,
        config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert build.thread_id == "verifier-thread"
    assert build.factory == VERIFIER_FACTORY
    assert build.project_digest
    assert observed["thread"]["approval_mode"] is ApprovalMode.deny_all
    assert observed["thread"]["sandbox"] is Sandbox.full_access
    assert set(observed["config"].env) == {"CODEX_HOME", "HOME", "UV_CACHE_DIR"}
    assert "TaskSemantics source" in observed["thread"]["base_instructions"]
    assert "verdict" not in observed["prompt"].casefold()
    workspace.verify_inputs()


def test_framework_rejects_actor_semantics_host_or_staged_view_runtime_access(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import generated_environment\n"
        "import generated_task_semantics\n"
        "import agent_env_foundry\n"
        "ACTOR_VIEW = 'actor-view'\n"
    )

    result = verifier_author_module._source_check(workspace.root)

    assert not result.passed
    assert "forbidden_import:generated_environment" in result.stderr
    assert "forbidden_import:generated_task_semantics" in result.stderr
    assert "forbidden_import:agent_env_foundry" in result.stderr
    assert "actor_view_runtime_access" in result.stderr


def test_framework_rejects_model_authored_authority_artifacts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_verifier():\n    return object()\n")
    (workspace.root / "qualification-receipt.json").write_text("{}")

    result = verifier_author_module._source_check(workspace.root)

    assert not result.passed
    assert "prohibited_output_artifact:receipt" in result.stderr


def test_model_completion_text_cannot_override_failed_framework_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    class Result:
        final_response = "done and passed"

    class Thread:
        id = "untrusted-verifier-thread"

        def run(self, prompt: str) -> Result:
            del prompt
            source = workspace.root / "src/generated_qualification_verifier/release.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("def make_verifier():\n    return object()\n")
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

    monkeypatch.setattr(verifier_author_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        verifier_author_module,
        "run_verifier_checks",
        lambda *_args, **_kwargs: (
            CommandResult("verifier_contract", ("host",), 1, "", "factory mismatch"),
        ),
    )

    with pytest.raises(VerifierAuthorFailure) as caught:
        run_verifier_author(
            workspace,
            config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "uv-cache"),
        )

    assert caught.value.code == "verifier_author_turns_exhausted"


def test_framework_runs_complete_verifier_gate_in_candidate_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_verifier():\n    return object()\n")
    (workspace.root / "tests").mkdir()
    observed: list[tuple[str, tuple[str, ...]]] = []

    def passed_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        phase: str,
        config: BuilderConfig,
        extra_env: dict[str, str] | None = None,
    ) -> CommandResult:
        del cwd, config, extra_env
        observed.append((phase, command))
        return CommandResult(phase, command, 0, "passed", "")

    own = workspace.root / "src/generated_qualification_verifier/__init__.py"
    monkeypatch.setattr(verifier_author_module, "_run", passed_run)
    monkeypatch.setattr(
        verifier_author_module,
        "_probe_origin",
        lambda _python, _project, module, _timeout: (
            own if module == "generated_qualification_verifier" else None
        ),
    )
    checks = verifier_author_module.run_verifier_checks(
        workspace,
        BuilderConfig(uv_cache_dir=tmp_path / "cache"),
    )

    assert [item.phase for item in checks] == [
        "source_contract",
        "lock",
        "sync",
        "import_separation",
        "build",
        "tests",
        "verifier_contract",
        "post_source_contract",
    ]
    tests_command = next(command for phase, command in observed if phase == "tests")
    assert tests_command[0] == str(workspace.root / ".venv/bin/python")
    assert tests_command[1:] == ("-m", "pytest", "-q")


def test_framework_rescans_authority_artifacts_after_generated_tests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_verifier():\n    return object()\n")
    (workspace.root / "tests").mkdir()

    def generated_test_side_effect(
        command: tuple[str, ...],
        *,
        cwd: Path,
        phase: str,
        config: BuilderConfig,
        extra_env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        del command, config, extra_env, input_text
        if phase == "tests":
            (cwd / "qualification-receipt.json").write_text("{}")
        return CommandResult(phase, ("fake",), 0, "passed", "")

    own = workspace.root / "src/generated_qualification_verifier/__init__.py"
    monkeypatch.setattr(verifier_author_module, "_run", generated_test_side_effect)
    monkeypatch.setattr(
        verifier_author_module,
        "_probe_origin",
        lambda _python, _project, module, _timeout: (
            own if module == "generated_qualification_verifier" else None
        ),
    )

    checks = verifier_author_module.run_verifier_checks(
        workspace,
        BuilderConfig(uv_cache_dir=tmp_path / "cache"),
    )

    assert checks[-1].phase == "post_source_contract"
    assert not checks[-1].passed
    assert "prohibited_output_artifact:receipt" in checks[-1].stderr


def test_provider_failure_is_infrastructure_not_verifier_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    class Thread:
        id = "failed-provider-thread"

        def run(self, prompt: str) -> None:
            del prompt
            raise TimeoutError("provider unavailable")

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

    monkeypatch.setattr(verifier_author_module, "Codex", FakeCodex)
    with pytest.raises(VerifierAuthorFailure) as caught:
        run_verifier_author(
            workspace,
            config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "cache"),
        )

    assert caught.value.phase == "infrastructure"
    assert caught.value.code == "verifier_provider_turn_failed"
    assert caught.value.details["original_code"] == "TimeoutError"


def test_verifier_digest_binds_file_mode(tmp_path: Path) -> None:
    source = tmp_path / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_verifier():\n    return object()\n")
    source.chmod(0o644)
    first = compute_verifier_project_digest(tmp_path)

    source.chmod(0o755)

    assert compute_verifier_project_digest(tmp_path) != first


def test_repair_resumes_same_verified_lineage_with_typed_findings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("VERSION = 1\ndef make_verifier():\n    return object()\n")
    codex_home = tmp_path / "verifier-codex-home"
    codex_home.mkdir()
    observed: dict[str, Any] = {}

    class Thread:
        id = "same-thread"

        def run(self, prompt: str) -> None:
            observed["prompt"] = prompt
            source.write_text("VERSION = 2\ndef make_verifier():\n    return object()\n")

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            del config

        def __enter__(self) -> FakeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def thread_resume(self, thread_id: str) -> Thread:
            observed["thread_id"] = thread_id
            return Thread()

    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(verifier_author_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        verifier_author_module,
        "run_verifier_checks",
        lambda *_args, **_kwargs: (CommandResult("host", ("host",), 0, "passed", ""),),
    )
    build = VerifierBuild(
        workspace.root,
        "same-thread",
        codex_home,
        VERIFIER_FACTORY,
        compute_verifier_project_digest(workspace.root),
        (),
    )
    finding = VerifierAuthorFinding(
        source="framework_check",
        code="REPORT_FIELDS_MISMATCH",
        condition="report fields match frozen semantics",
        expected=["deadline_utc"],
        actual=["deadline"],
        decisive_inputs={"capability_id": "CAP-001"},
    )

    repaired = repair_verifier_author(
        workspace,
        build,
        (finding,),
        config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "cache"),
    )

    assert observed["thread_id"] == "same-thread"
    assert "REPORT_FIELDS_MISMATCH" in observed["prompt"]
    assert repaired.project_digest != build.project_digest


def test_repair_rejects_untyped_findings_and_changed_project_digest(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace.root / "src/generated_qualification_verifier/release.py"
    source.parent.mkdir(parents=True)
    source.write_text("def make_verifier():\n    return object()\n")
    codex_home = tmp_path / "verifier-codex-home"
    codex_home.mkdir()
    finding = VerifierAuthorFinding(
        source="native_physical_check",
        code="AXIS_MISMATCH",
        condition="axes remain independent",
        expected=True,
        actual=False,
        decisive_inputs={},
    )
    changed_build = VerifierBuild(
        workspace.root,
        "thread",
        codex_home,
        VERIFIER_FACTORY,
        "0" * 64,
        (),
    )

    with pytest.raises(VerifierAuthorFailure) as digest_error:
        repair_verifier_author(
            workspace,
            changed_build,
            (finding,),
            config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "cache"),
        )
    assert digest_error.value.code == "verifier_repair_digest_mismatch"

    valid_build = VerifierBuild(
        workspace.root,
        "thread",
        codex_home,
        VERIFIER_FACTORY,
        compute_verifier_project_digest(workspace.root),
        (),
    )
    with pytest.raises(VerifierAuthorFailure) as type_error:
        repair_verifier_author(
            workspace,
            valid_build,
            ({"code": "untyped"},),  # type: ignore[arg-type]
            config=BuilderConfig(max_turns=1, uv_cache_dir=tmp_path / "cache"),
        )
    assert type_error.value.code == "verifier_repair_identity_mismatch"


def _native_request(before: Path, after: Path) -> NativeVerificationRequest:
    return NativeVerificationRequest(
        capability_id="CAP-001",
        start_case_id="START-001",
        public_descriptor={"item": "public-1"},
        public_trace=(
            TraceEvent(
                seq=1,
                tool_name="inspect_item",
                arguments={"item": "public-1"},
                observation={"ok": True, "data": {"item": "public-1"}, "error": None},
            ),
        ),
        final_answer={"item": "public-1"},
        before_instance_directory=before,
        after_instance_directory=after,
    )


def _native_result_document() -> dict[str, Any]:
    return {
        "initially_satisfied": False,
        "satisfied": True,
        "required_effects_ok": True,
        "collateral_ok": True,
        "answer_ok": True,
        "process_ok": True,
        "report_values": {"item": "public-1"},
        "failure_codes": [],
    }


def test_host_verifier_boundary_decodes_exact_result_and_proves_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "state.db").write_bytes(b"before")
    (after / "state.db").write_bytes(b"after")
    observed: dict[str, Any] = {}

    def execute(command: tuple[str, ...], **kwargs: Any) -> CommandResult:
        observed.update(kwargs)
        return CommandResult(
            "verifier_transition",
            command,
            0,
            json.dumps(_native_result_document()),
            "",
        )

    monkeypatch.setattr(verifier_author_module, "_run", execute)

    verifier = tmp_path / "verifier"
    verifier.mkdir()
    result = invoke_verifier_transition(
        verifier,
        _native_request(before, after),
        expected_verifier_project_digest=compute_verifier_project_digest(verifier),
        expected_report_field_ids=("item",),
        config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
    )

    assert result.satisfied
    assert result.initially_satisfied is False
    assert json.loads(observed["input_text"])["capability_id"] == "CAP-001"


def test_host_verifier_boundary_rejects_native_mutation_even_when_result_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "state.db").write_bytes(b"before")
    (after / "state.db").write_bytes(b"after")

    def mutate(command: tuple[str, ...], **kwargs: Any) -> CommandResult:
        del kwargs
        (after / "marker").write_text("mutated")
        return CommandResult(
            "verifier_transition",
            command,
            0,
            json.dumps(_native_result_document()),
            "",
        )

    monkeypatch.setattr(verifier_author_module, "_run", mutate)

    verifier = tmp_path / "verifier"
    verifier.mkdir()
    with pytest.raises(VerifierAuthorFailure) as caught:
        invoke_verifier_transition(
            verifier,
            _native_request(before, after),
            expected_verifier_project_digest=compute_verifier_project_digest(verifier),
            expected_report_field_ids=("item",),
            config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
        )

    assert caught.value.code == "verifier_instance_mutation"


def test_host_verifier_boundary_rejects_report_field_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()

    def alias(command: tuple[str, ...], **kwargs: Any) -> CommandResult:
        del kwargs
        payload = _native_result_document()
        payload["report_values"] = {"deadline": "2026-02-01T00:00:00Z"}
        return CommandResult("verifier_transition", command, 0, json.dumps(payload), "")

    monkeypatch.setattr(verifier_author_module, "_run", alias)

    verifier = tmp_path / "verifier"
    verifier.mkdir()
    with pytest.raises(VerifierAuthorFailure) as caught:
        invoke_verifier_transition(
            verifier,
            _native_request(before, after),
            expected_verifier_project_digest=compute_verifier_project_digest(verifier),
            expected_report_field_ids=("deadline_utc",),
            config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
        )

    assert caught.value.code == "verifier_report_fields_mismatch"
    assert caught.value.details["missing"] == ["deadline_utc"]
    assert caught.value.details["unexpected"] == ["deadline"]


def test_host_verifier_boundary_accepts_neutral_null_report_on_unresolved_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()

    def unresolved(command: tuple[str, ...], **kwargs: Any) -> CommandResult:
        del kwargs
        payload = _native_result_document()
        payload["satisfied"] = False
        payload["required_effects_ok"] = False
        payload["answer_ok"] = False
        payload["report_values"] = {"item": None}
        payload["failure_codes"] = ["UNSUPPORTED_REFERENT"]
        return CommandResult("verifier_transition", command, 0, json.dumps(payload), "")

    monkeypatch.setattr(verifier_author_module, "_run", unresolved)

    verifier = tmp_path / "verifier"
    verifier.mkdir()
    result = invoke_verifier_transition(
        verifier,
        _native_request(before, after),
        expected_verifier_project_digest=compute_verifier_project_digest(verifier),
        expected_report_field_ids=("item",),
        config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
    )

    assert result.satisfied is False
    assert result.report_values == {"item": None}
    assert result.failure_codes == ("UNSUPPORTED_REFERENT",)


def test_verifier_contract_states_exact_report_and_referent_rules() -> None:
    contract = (
        Path(__file__).resolve().parents[1]
        / "src/agent_env_foundry/runtime_skills/qualification-verifier-codegen/"
        "QUALIFICATION_VERIFIER_CONTRACT.md"
    ).read_text()

    assert "exactly the declared" in contract
    assert "`null`" in contract
    assert "authoritative intended referent" in " ".join(contract.split())


def test_host_verifier_boundary_rejects_verifier_project_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verifier = tmp_path / "verifier"
    before = tmp_path / "before"
    after = tmp_path / "after"
    verifier.mkdir()
    before.mkdir()
    after.mkdir()

    def mutate_project(command: tuple[str, ...], **kwargs: Any) -> CommandResult:
        del kwargs
        (verifier / "qualification-receipt.json").write_text("{}")
        return CommandResult(
            "verifier_transition",
            command,
            0,
            json.dumps(_native_result_document()),
            "",
        )

    monkeypatch.setattr(verifier_author_module, "_run", mutate_project)

    with pytest.raises(VerifierAuthorFailure) as caught:
        invoke_verifier_transition(
            verifier,
            _native_request(before, after),
            expected_verifier_project_digest=compute_verifier_project_digest(verifier),
            expected_report_field_ids=("item",),
            config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
        )

    assert caught.value.code == "verifier_instance_mutation"
    assert "verifier_project" in caught.value.details["changed"]


def test_host_verifier_boundary_binds_accepted_digest_and_resolved_instances(
    tmp_path: Path,
) -> None:
    verifier = tmp_path / "verifier"
    before = tmp_path / "before"
    verifier.mkdir()
    before.mkdir()
    after_alias = tmp_path / "after-alias"
    after_alias.symlink_to(before, target_is_directory=True)

    with pytest.raises(VerifierAuthorFailure) as digest_error:
        invoke_verifier_transition(
            verifier,
            _native_request(before, tmp_path / "distinct"),
            expected_verifier_project_digest="0" * 64,
            expected_report_field_ids=("item",),
            config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
        )
    assert digest_error.value.code == "verifier_project_digest_mismatch"

    with pytest.raises(VerifierAuthorFailure) as alias_error:
        invoke_verifier_transition(
            verifier,
            _native_request(before, after_alias),
            expected_verifier_project_digest=compute_verifier_project_digest(verifier),
            expected_report_field_ids=("item",),
            config=BuilderConfig(uv_cache_dir=tmp_path / "cache"),
        )
    assert alias_error.value.code == "verifier_instance_alias"
