"""Slice 3 Builder mechanics; fake SDK paths never prove a product candidate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from codex_cli_bin import bundled_codex_path
from openai_codex import ApprovalMode

import agent_env_foundry.builder as builder_module
from agent_env_foundry.builder import (
    BuilderConfig,
    BuilderFailure,
    CommandResult,
    compute_candidate_digest,
    prepare_builder_workspace,
    run_builder,
    run_candidate_checks,
)
from agent_env_foundry.research import BuilderProjection


@pytest.fixture(autouse=True)
def _builder_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-key")


def projection() -> BuilderProjection:
    return BuilderProjection(
        frozen_need={
            "original_need": "Create a resettable stateful environment.",
            "clauses": [{"clause_id": "NEED-001", "text": "Persist state."}],
        },
        selected_world={
            "scope": "One bounded synthetic world.",
            "assumptions": [],
            "exclusions": [],
            "residual_limitations": [],
        },
        requirements=(
            {
                "id": "REQ-001",
                "need_origins": ["NEED-001"],
                "authority": "need",
                "kind": "workflows",
                "state_relation": "A write changes persistent state.",
                "observable_relation": "A later read returns the new value.",
                "precondition": "The instance has been reset.",
                "postcondition": "The value is persisted in the instance directory.",
                "falsifiable_consequence": "A later read returns the old value.",
                "evidence_refs": [],
            },
        ),
        initial_world_relations=(
            {
                "id": "REQ-002",
                "need_origins": ["NEED-001"],
                "authority": "need",
                "state_relation": "The default world has one readable record.",
                "observable_relation": "Reset returns that record.",
                "falsifiable_consequence": "Reset creates an empty world.",
                "evidence_refs": [],
            },
        ),
        cited_evidence=(),
    )


def test_prepare_workspace_has_no_domain_source_and_one_projection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    prepared = prepare_builder_workspace(
        workspace,
        projection(),
        uv_cache_dir=tmp_path / "uv-cache",
    )

    assert prepared.root == workspace
    assert (workspace / "pyproject.toml").is_file()
    assert not list((workspace / "src").rglob("*.py"))
    assert json.loads((workspace / "BUILDER_PROJECTION.json").read_text()) == (
        projection().to_document()
    )
    contract = (workspace / "ENVIRONMENT_CONTRACT.md").read_text()
    for required in (
        "reset",
        "tools",
        "invoke",
        "close",
        "ToolObservation",
        "instance directory",
        "prohibited mutation",
    ):
        assert required in contract
    prepared.verify_inputs()

    (workspace / "BUILDER_PROJECTION.json").chmod(0o600)
    (workspace / "BUILDER_PROJECTION.json").write_text("{}")
    with pytest.raises(BuilderFailure, match="Builder input"):
        prepared.verify_inputs()

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "user.txt").write_text("preserve me")
    with pytest.raises(BuilderFailure, match="empty"):
        prepare_builder_workspace(occupied, projection(), uv_cache_dir=tmp_path / "uv-cache")
    assert (occupied / "user.txt").read_text() == "preserve me"


def test_prepare_workspace_resolves_relative_target_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_project = tmp_path / "pyproject.toml"
    host_project.write_text('[project]\nname = "host-project"\nversion = "0.1.0"\n')
    original_host_project = host_project.read_bytes()
    monkeypatch.chdir(tmp_path)

    prepared = prepare_builder_workspace(
        Path("runs/run-001/candidate"),
        projection(),
        uv_cache_dir=Path("cache"),
    )

    assert prepared.root == (tmp_path / "runs/run-001/candidate").resolve()
    assert (prepared.root / "BUILDER_PROJECTION.json").is_file()
    assert not (prepared.root / "runs/run-001/candidate").exists()
    assert host_project.read_bytes() == original_host_project


def test_candidate_digest_excludes_inputs_and_build_caches_but_binds_source(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    prepare_builder_workspace(workspace, projection(), uv_cache_dir=tmp_path / "uv-cache")
    source = workspace / "src/generated_environment/runtime.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("VALUE = 1\n")
    first = compute_candidate_digest(workspace)

    (workspace / "BUILDER_PROJECTION.json").chmod(0o600)
    (workspace / "BUILDER_PROJECTION.json").write_text("{}")
    (workspace / ".venv/cache.bin").parent.mkdir(parents=True)
    (workspace / ".venv/cache.bin").write_bytes(b"cache")
    (workspace / ".venv/lib").mkdir()
    (workspace / ".venv/lib64").symlink_to("lib", target_is_directory=True)
    (workspace / "dist/archive.whl").parent.mkdir()
    (workspace / "dist/archive.whl").write_bytes(b"build")
    assert compute_candidate_digest(workspace) == first

    source.write_text("VALUE = 2\n")
    assert compute_candidate_digest(workspace) != first

    source_link = workspace / "src/generated_environment/linked.py"
    source_link.symlink_to("runtime.py")
    with pytest.raises(BuilderFailure) as caught:
        compute_candidate_digest(workspace)
    assert caught.value.code == "candidate_symlink_forbidden"
    assert caught.value.details["path"] == "src/generated_environment/linked.py"


class FakeResult:
    final_response = "fake mechanical result"


class FakeThread:
    id = "fake-thread"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.prompts: list[str] = []

    def run(self, prompt: str) -> FakeResult:
        self.prompts.append(prompt)
        generated = self.workspace / "src/generated_environment/runtime.py"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(f"TURN = {len(self.prompts)}\n")
        return FakeResult()


class FakeCodex:
    instances: list[FakeCodex] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.thread_kwargs: dict[str, Any] = {}
        self.thread: FakeThread | None = None
        self.__class__.instances.append(self)

    def __enter__(self) -> FakeCodex:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def thread_start(self, **kwargs: Any) -> FakeThread:
        self.thread_kwargs = kwargs
        self.thread = FakeThread(Path(kwargs["cwd"]))
        return self.thread


def test_builder_uses_official_sdk_shape_and_same_thread_factual_repair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeCodex.instances.clear()
    monkeypatch.setattr(builder_module, "Codex", FakeCodex)
    attempts = 0

    def checks(root: Path, config: BuilderConfig) -> tuple[CommandResult, ...]:
        nonlocal attempts
        attempts += 1
        return (
            CommandResult(
                phase="tests",
                command=(str(root / ".venv" / "bin" / "python"), "-m", "pytest", "-q"),
                exit_code=1 if attempts == 1 else 0,
                stdout="",
                stderr="first factual failure" if attempts == 1 else "",
            ),
        )

    monkeypatch.setattr(builder_module, "run_candidate_checks", checks)
    result = run_builder(
        projection(),
        tmp_path / "candidate",
        config=BuilderConfig(max_turns=2, uv_cache_dir=tmp_path / "uv-cache"),
    )

    sdk = FakeCodex.instances[-1]
    assert sdk.thread_kwargs["cwd"] == str(tmp_path / "candidate")
    assert sdk.thread_kwargs["model"] == "gpt-5.6-luna"
    assert sdk.thread_kwargs["sandbox"].value == "full-access"
    assert sdk.thread is not None and len(sdk.thread.prompts) == 2
    assert "first factual failure" in sdk.thread.prompts[1]
    assert result.thread_id == "fake-thread"
    assert result.checks[-1].exit_code == 0


def test_unchanged_failed_candidate_is_typed_stall(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class StalledThread(FakeThread):
        def run(self, prompt: str) -> FakeResult:
            self.prompts.append(prompt)
            return FakeResult()

    class StalledCodex(FakeCodex):
        def thread_start(self, **kwargs: Any) -> StalledThread:
            self.thread_kwargs = kwargs
            self.thread = StalledThread(Path(kwargs["cwd"]))
            return self.thread

    monkeypatch.setattr(builder_module, "Codex", StalledCodex)
    monkeypatch.setattr(
        builder_module,
        "run_candidate_checks",
        lambda root, config: (CommandResult("build", ("uv", "build"), 1, "", "build failed"),),
    )

    with pytest.raises(BuilderFailure) as caught:
        run_builder(
            projection(),
            tmp_path / "candidate",
            config=BuilderConfig(max_turns=2, uv_cache_dir=tmp_path / "uv-cache"),
        )
    assert caught.value.code == "builder_stalled"
    assert caught.value.details["phase"] == "build"


def test_sequential_runs_use_distinct_ephemeral_codex_homes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeCodex.instances.clear()
    monkeypatch.setattr(builder_module, "Codex", FakeCodex)
    inherited = tmp_path / "inherited-global-codex-home"
    inherited.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(inherited))
    homes: list[Path] = []
    listings: list[list[str]] = []

    def checks(root: Path, config: BuilderConfig) -> tuple[CommandResult, ...]:
        home = Path(FakeCodex.instances[-1].config.env["CODEX_HOME"])
        homes.append(home)
        listings.append(sorted(os.listdir(home)))
        if len(homes) == 1:
            (home / "prior-run-state").write_text("sentinel from run one")
        return (CommandResult("build", ("uv", "build"), 0, "", ""),)

    monkeypatch.setattr(builder_module, "run_candidate_checks", checks)
    config = BuilderConfig(uv_cache_dir=tmp_path / "uv-cache")

    run_builder(projection(), tmp_path / "one", config=config)
    run_builder(projection(), tmp_path / "two", config=config)

    first_home, second_home = homes
    assert first_home != second_home
    assert listings == [["home"], ["home"]]
    assert not first_home.exists()
    assert not second_home.exists()
    assert not first_home.is_relative_to(tmp_path / "one")
    assert not second_home.is_relative_to(tmp_path / "two")
    sdk = FakeCodex.instances[-1]
    assert Path(sdk.config.env["CODEX_HOME"]) != inherited
    assert Path(sdk.config.env["CODEX_HOME"]) != Path.home() / ".codex"
    assert Path(sdk.config.env["HOME"]).parent == Path(sdk.config.env["CODEX_HOME"])
    assert not Path(sdk.config.env["HOME"]).exists()
    assert sdk.thread_kwargs["sandbox"].value == "full-access"
    assert sdk.thread_kwargs["approval_mode"] == ApprovalMode.deny_all
    assert "OPENAI_API_KEY" not in sdk.config.env
    assert "OPENAI_BASE_URL" not in sdk.config.env


def test_sdk_uses_explicit_custom_provider_without_copying_key_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeCodex.instances.clear()
    monkeypatch.setattr(builder_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        builder_module,
        "run_candidate_checks",
        lambda root, config: (CommandResult("build", ("uv", "build"), 0, "", ""),),
    )

    run_builder(
        projection(),
        tmp_path / "candidate",
        config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    sdk = FakeCodex.instances[-1]
    assert sdk.config.config_overrides == (
        'model_provider="foundry_runtime"',
        'model_providers.foundry_runtime.name="Foundry runtime"',
        'model_providers.foundry_runtime.base_url="http://provider.invalid/v1"',
        'model_providers.foundry_runtime.env_key="OPENAI_API_KEY"',
        'model_providers.foundry_runtime.wire_api="responses"',
        "model_providers.foundry_runtime.supports_websockets=true",
        "project_root_markers=[]",
        "features.plugins=false",
        "features.multi_agent=false",
        "features.skill_search=false",
    )
    assert "test-provider-key" not in repr(sdk.config.config_overrides)
    assert set(sdk.config.env) == {"CODEX_HOME", "HOME", "UV_CACHE_DIR"}
    assert Path(sdk.config.env["HOME"]).parent == Path(sdk.config.env["CODEX_HOME"])


def test_product_codex_prompt_input_excludes_parent_and_user_guidance(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    workspace = repository / "runs/candidate"
    workspace.mkdir(parents=True)
    repository.joinpath(".git").mkdir()
    repository.joinpath("AGENTS.md").write_text("PARENT_AGENT_SENTINEL")
    repository.joinpath(".agents/skills/forbidden").mkdir(parents=True)
    repository.joinpath(".agents/skills/forbidden/SKILL.md").write_text(
        "---\nname: forbidden\ndescription: PARENT_SKILL_SENTINEL\n---\n"
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    env = dict(os.environ)
    env.update(builder_module._isolated_codex_env(codex_home, tmp_path / "uv-cache"))
    command = [str(bundled_codex_path())]
    for override in builder_module._codex_provider_overrides():
        command.extend(("--config", override))
    command.extend(("debug", "prompt-input", "context boundary probe"))

    result = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "PARENT_AGENT_SENTINEL" not in result.stdout
    assert "PARENT_SKILL_SENTINEL" not in result.stdout
    assert str(Path.home() / ".agents/skills") not in result.stdout


@pytest.mark.parametrize(
    ("missing", "expected_code"),
    [
        ("OPENAI_BASE_URL", "provider_base_url_missing"),
        ("OPENAI_API_KEY", "provider_api_key_missing"),
    ],
)
def test_builder_rejects_missing_explicit_provider_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing: str,
    expected_code: str,
) -> None:
    FakeCodex.instances.clear()
    monkeypatch.setattr(builder_module, "Codex", FakeCodex)
    monkeypatch.setattr(
        builder_module,
        "run_candidate_checks",
        lambda root, config: (CommandResult("build", ("uv", "build"), 0, "", ""),),
    )
    monkeypatch.delenv(missing)

    with pytest.raises(BuilderFailure) as caught:
        run_builder(
            projection(),
            tmp_path / missing.lower(),
            config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
        )

    assert caught.value.phase == "builder_provider"
    assert caught.value.code == expected_code
    assert not FakeCodex.instances


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


_UV_FAKE = """#!/bin/sh
{
  echo "ARGV: $*"
  echo "VIRTUAL_ENV=$VIRTUAL_ENV"
  echo "PYTHONPATH=$PYTHONPATH"
  echo "PYTHONHOME=$PYTHONHOME"
  echo "UV_CACHE_DIR=$UV_CACHE_DIR"
} >> "$FAKE_TOOLCHAIN_LOG"
case "$1" in
  sync)
    mkdir -p .venv/bin
    cp "$FAKE_VENV_PYTHON" .venv/bin/python
    chmod +x .venv/bin/python
    ;;
  run)
    shift
    while [ "$1" = "--frozen" ]; do shift; done
    exec "$@"
    ;;
esac
exit 0
"""

_AMBIENT_PYTEST_FAKE = """#!/bin/sh
echo "AMBIENT_PYTEST_EXECUTED: $*" >> "$FAKE_TOOLCHAIN_LOG"
exit 0
"""

_VENV_PYTHON_WITH_PYTEST = """#!/bin/sh
{
  echo "ARGV: $*"
  echo "VIRTUAL_ENV=$VIRTUAL_ENV"
  echo "PYTHONPATH=$PYTHONPATH"
  echo "PYTHONHOME=$PYTHONHOME"
} >> "$FAKE_TOOLCHAIN_LOG"
exit 0
"""

_VENV_PYTHON_WITHOUT_PYTEST = """#!/bin/sh
{
  echo "ARGV: $*"
  echo "VIRTUAL_ENV=$VIRTUAL_ENV"
  echo "PYTHONPATH=$PYTHONPATH"
  echo "PYTHONHOME=$PYTHONHOME"
} >> "$FAKE_TOOLCHAIN_LOG"
echo "candidate python: No module named pytest" >&2
exit 1
"""


def _wire_fake_toolchain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    venv_python_body: str,
) -> Path:
    bin_dir = tmp_path / "bin"
    log = tmp_path / "toolchain.log"
    venv_python = tmp_path / "candidate-venv-python"
    _write_executable(bin_dir / "uv", _UV_FAKE)
    _write_executable(bin_dir / "pytest", _AMBIENT_PYTEST_FAKE)
    _write_executable(venv_python, venv_python_body)
    monkeypatch.setenv("FAKE_TOOLCHAIN_LOG", str(log))
    monkeypatch.setenv("FAKE_VENV_PYTHON", str(venv_python))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "ambient-venv"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "ambient-site-packages"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "ambient-pythonhome"))
    return log


def _candidate_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_smoke.py").write_text("def test_smoke() -> None:\n    pass\n")
    schemas = root / "docs/schemas"
    schemas.mkdir(parents=True)
    schema = json.dumps({"type": "object"})
    (schemas / "start.json").write_text(schema)
    (schemas / "reset.json").write_text(schema)
    return root


def test_host_preparation_owns_installation_and_scrubs_ambient_python_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = _wire_fake_toolchain(monkeypatch, tmp_path, _VENV_PYTHON_WITH_PYTEST)
    root = _candidate_root(tmp_path, "candidate")
    config = BuilderConfig(uv_cache_dir=tmp_path / "uv-cache")

    results = run_candidate_checks(root, config)

    assert all(item.passed for item in results), [item.to_document() for item in results]
    assert [item.phase for item in results] == [
        "lock",
        "sync",
        "build",
        "tests",
        "public_contract",
    ]
    lines = log.read_text().splitlines()
    argv = [line for line in lines if line.startswith("ARGV:")]
    assert argv[:4] == [
        "ARGV: lock",
        "ARGV: sync --frozen --all-groups",
        "ARGV: build",
        "ARGV: -m pytest -q",
    ]
    assert "AMBIENT_PYTEST_EXECUTED" not in lines
    for prefix in ("VIRTUAL_ENV=", "PYTHONPATH=", "PYTHONHOME="):
        values = [line for line in lines if line.startswith(prefix)]
        assert values == [prefix] * 4
    assert f"UV_CACHE_DIR={config.uv_cache_dir}" in lines


def test_ambient_host_pytest_cannot_satisfy_candidate_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = _wire_fake_toolchain(monkeypatch, tmp_path, _VENV_PYTHON_WITHOUT_PYTEST)
    root = _candidate_root(tmp_path, "candidate")
    config = BuilderConfig(uv_cache_dir=tmp_path / "uv-cache")

    results = run_candidate_checks(root, config)

    assert not all(item.passed for item in results)
    tests_result = results[-1]
    assert tests_result.phase == "tests"
    assert tests_result.command[0] == str(root / ".venv" / "bin" / "python")
    assert "-m" in tests_result.command and "pytest" in tests_result.command
    assert not tests_result.passed
    assert "No module named pytest" in tests_result.stderr
    assert "AMBIENT_PYTEST_EXECUTED" not in log.read_text()


def test_candidate_checks_reject_noncanonical_schema_handoff_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _wire_fake_toolchain(monkeypatch, tmp_path, _VENV_PYTHON_WITH_PYTEST)
    root = _candidate_root(tmp_path, "candidate")
    schemas = root / "docs/schemas"
    (schemas / "start.json").rename(schemas / "reset_start.schema.json")
    (schemas / "reset.json").rename(schemas / "reset_observation.schema.json")

    results = run_candidate_checks(
        root,
        BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    public_contract = results[-1]
    assert public_contract.phase == "public_contract"
    assert not public_contract.passed
    assert "docs/schemas/start.json" in public_contract.stderr
    assert "docs/schemas/reset.json" in public_contract.stderr


_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/agent_env_foundry/runtime_skills/environment-codegen/ENVIRONMENT_CONTRACT.md"
)


def test_contract_document_keeps_release_assembly_out_of_builder() -> None:
    text = _CONTRACT_PATH.read_text(encoding="utf-8")
    assert "plain mapping" in text
    assert "Every emitted public leaf" in text
    assert "reset-only beginning situation" in text
    assert "every accepted workflow precondition" in text
    assert "hidden setup" in text
    assert "generated_environment.release:make_environment" in text
    assert "`docs/schemas/start.json`" in text
    assert "`docs/schemas/reset.json`" in text
    assert "Do not write `release.json`" in text
    assert "Host combines this project" in text
    assert "EnvironmentRelease v2" in text


def test_candidate_identity_binds_post_lock_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeCodex.instances.clear()
    monkeypatch.setattr(builder_module, "Codex", FakeCodex)

    def checks_writing(lock_content: str) -> Any:
        def checks(root: Path, config: BuilderConfig) -> tuple[CommandResult, ...]:
            (root / "uv.lock").write_text(lock_content)
            return (CommandResult("lock", ("uv", "lock"), 0, "", ""),)

        return checks

    monkeypatch.setattr(builder_module, "run_candidate_checks", checks_writing("lock-bytes-A\n"))
    first = run_builder(
        projection(),
        tmp_path / "one",
        config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    monkeypatch.setattr(builder_module, "run_candidate_checks", checks_writing("lock-bytes-B\n"))
    second = run_builder(
        projection(),
        tmp_path / "two",
        config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert first.candidate_digest == compute_candidate_digest(tmp_path / "one")
    assert second.candidate_digest == compute_candidate_digest(tmp_path / "two")
    assert first.candidate_digest != second.candidate_digest
