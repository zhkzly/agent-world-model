"""Physical ``environment_load`` Builder check: real smoke in candidate Python.

The fake toolchain keeps lock/sync/build light, but the candidate venv python
wrapper re-execs the real interpreter, so ``python -m agent_env_foundry._smoke``
genuinely runs the standard loader against the mechanical fixture release in a
fresh subprocess. This proves wiring, not product completion (PRD F8).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_env_foundry.builder import BuilderConfig, run_candidate_checks
from release_factory import DEFAULT_RESET_OBSERVATION_SCHEMA, build_release

_SRC = Path(__file__).resolve().parents[1] / "src"
_TESTS_DIR = Path(__file__).resolve().parent
_FIXTURES = _TESTS_DIR / "fixtures"

# Requires a top-level ``scenario`` the mechanical fixture never returns, so a
# reset result shaped like a ToolObservation (or any other mismatch) is RED.
SCENARIO_ONLY_RESET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"scenario": {"type": "string"}},
    "required": ["scenario"],
    "additionalProperties": False,
}


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
  pip)
    target=""
    shift
    while [ $# -gt 0 ]; do
      case "$1" in
        --target) target="$2"; shift; shift ;;
        *) shift ;;
      esac
    done
    [ -n "$target" ] && mkdir -p "$target"
    ;;
esac
exit 0
"""

_UV_FAKE_PIP_FAILS = """#!/bin/sh
{
  echo "ARGV: $*"
} >> "$FAKE_TOOLCHAIN_LOG"
case "$1" in
  sync)
    mkdir -p .venv/bin
    cp "$FAKE_VENV_PYTHON" .venv/bin/python
    chmod +x .venv/bin/python
    ;;
  pip)
    echo "loader staging failed" >&2
    exit 1
    ;;
esac
exit 0
"""

_AMBIENT_PYTEST_FAKE = """#!/bin/sh
echo "AMBIENT_PYTEST_EXECUTED: $*" >> "$FAKE_TOOLCHAIN_LOG"
exit 0
"""

# Fake candidate venv python: records the scrubbed environment the Host check
# passed, then executes the real interpreter so _smoke actually runs.
_VENV_PYTHON_REAL = """#!/bin/sh
{
  echo "ARGV: $*"
  echo "VIRTUAL_ENV=$VIRTUAL_ENV"
  echo "PYTHONPATH=$PYTHONPATH"
  echo "PYTHONHOME=$PYTHONHOME"
} >> "$FAKE_TOOLCHAIN_LOG"
export PYTHONPATH="$PYTHONPATH:$SMOKE_EXTRA_PATH"
exec "$SMOKE_PYTHON" "$@"
"""


def _wire_smoke_toolchain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, uv_body: str = _UV_FAKE
) -> Path:
    bin_dir = tmp_path / "bin"
    log = tmp_path / "toolchain.log"
    venv_python = tmp_path / "candidate-venv-python"
    _write_executable(bin_dir / "uv", uv_body)
    _write_executable(bin_dir / "pytest", _AMBIENT_PYTEST_FAKE)
    _write_executable(venv_python, _VENV_PYTHON_REAL)
    monkeypatch.setenv("FAKE_TOOLCHAIN_LOG", str(log))
    monkeypatch.setenv("FAKE_VENV_PYTHON", str(venv_python))
    monkeypatch.setenv("SMOKE_PYTHON", sys.executable)
    monkeypatch.setenv("SMOKE_EXTRA_PATH", os.pathsep.join((str(_TESTS_DIR), str(_FIXTURES))))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "ambient-venv"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "ambient-site-packages"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "ambient-pythonhome"))
    return log


def _candidate(tmp_path: Path, name: str, *, reset_observation_schema: Any = None) -> Path:
    root = tmp_path / name
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_smoke.py").write_text("def test_smoke() -> None:\n    pass\n")
    build_release(
        root,
        reset_observation_schema=(reset_observation_schema or DEFAULT_RESET_OBSERVATION_SCHEMA),
    )
    return root


def _phases(results: tuple[Any, ...]) -> list[str]:
    return [item.phase for item in results]


def test_environment_load_smoke_green_in_candidate_python_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = _wire_smoke_toolchain(monkeypatch, tmp_path)
    root = _candidate(tmp_path, "candidate")
    config = BuilderConfig(uv_cache_dir=tmp_path / "uv-cache")

    results = run_candidate_checks(root, config)

    assert _phases(results) == [
        "lock",
        "sync",
        "build",
        "tests",
        "release_contract",
        "environment_load",
    ]
    assert all(item.passed for item in results), [item.to_document() for item in results]
    load = results[-1]
    candidate_python = root / ".venv" / "bin" / "python"
    assert load.command == (
        str(candidate_python),
        "-m",
        "agent_env_foundry._smoke",
        str(root),
    )
    assert "environment_load_ok" in load.stdout

    lines = log.read_text().splitlines()
    argv_lines = [line for line in lines if line.startswith("ARGV:")]
    assert any(
        re.fullmatch(r"ARGV: pip install --python \S+ --target \S+ rfc8785 jsonschema", line)
        for line in argv_lines
    )
    assert f"ARGV: -m agent_env_foundry._smoke {root}" in argv_lines
    assert "AMBIENT_PYTEST_EXECUTED" not in lines

    # Ambient PYTHONPATH is replaced, not extended: exactly one non-empty
    # PYTHONPATH observation, built from Host src plus the temp loader target.
    explicit = [line for line in lines if line.startswith("PYTHONPATH=") and line != "PYTHONPATH="]
    assert len(explicit) == 1
    parts = explicit[0][len("PYTHONPATH=") :].split(os.pathsep)
    assert parts[0] == str(_SRC)
    assert parts[1].endswith("/site")
    assert not any("ambient" in part for part in parts)
    assert lines.count("VIRTUAL_ENV=") == 6
    assert lines.count("PYTHONHOME=") == 6


def test_environment_load_red_on_reset_schema_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The observed defect class: reset result outside the published schema."""
    log = _wire_smoke_toolchain(monkeypatch, tmp_path)
    root = _candidate(tmp_path, "candidate", reset_observation_schema=SCENARIO_ONLY_RESET_SCHEMA)

    results = run_candidate_checks(root, BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"))

    assert _phases(results) == [
        "lock",
        "sync",
        "build",
        "tests",
        "release_contract",
        "environment_load",
    ]
    assert all(item.passed for item in results[:-1]), [item.to_document() for item in results]
    rejected = results[-1]
    assert not rejected.passed
    assert "reset observation violates the published reset_observation_schema" in rejected.stderr
    assert "scenario" in rejected.stderr
    assert "environment_load_ok" not in rejected.stdout
    assert f"ARGV: -m agent_env_foundry._smoke {root}" in log.read_text().splitlines()


def test_loader_staging_failure_attributed_to_environment_load_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = _wire_smoke_toolchain(monkeypatch, tmp_path, uv_body=_UV_FAKE_PIP_FAILS)
    root = _candidate(tmp_path, "candidate")

    results = run_candidate_checks(root, BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"))

    assert _phases(results)[-1] == "environment_load"
    assert all(item.passed for item in results[:-1])
    failed = results[-1]
    assert not failed.passed
    assert failed.command[:3] == ("uv", "pip", "install")
    assert "--target" in failed.command
    assert "loader staging failed" in failed.stderr
    assert "-m agent_env_foundry._smoke" not in log.read_text()


def test_smoke_module_rejects_empty_tool_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agent_env_foundry import _smoke

    class EmptyCatalogEnvironment:
        closed = False

        def reset(self, start: dict[str, Any] | None = None) -> dict[str, Any]:
            return {}

        def tools(self) -> tuple[Any, ...]:
            return ()

        def close(self) -> None:
            self.closed = True

    empty = EmptyCatalogEnvironment()
    monkeypatch.setattr(_smoke, "load_environment", lambda release, instance: empty)

    assert _smoke.main(["_smoke", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "empty catalog" in captured.err
    assert empty.closed
