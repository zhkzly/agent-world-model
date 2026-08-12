from __future__ import annotations

import zipfile
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess
from typing import Literal

import pytest

from agent_world.supply_chain import (
    AdmittedLockClosure,
    SupplyChainError,
    compile_sbom,
    offline_uv_argv,
    prepare_candidate,
    validate_candidate_dependencies,
)


def _metadata(root: Path, dependencies: tuple[str, ...] = (), lock: str = "version = 1\n") -> None:
    dependency_lines = "".join(f'"{dependency}", ' for dependency in dependencies)
    (root / "pyproject.toml").write_text(
        f"[project]\nname = 'candidate'\nversion = '0'\ndependencies = [{dependency_lines}]\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(lock, encoding="utf-8")


def test_offline_uv_policy_is_fixed_and_scrubs_ambient_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("UV_INDEX_URL", "https://ambient.invalid")
    venv, sync, env = offline_uv_argv(
        "/python",
        tmp_path / "venv",
        tmp_path / "cache",
        tmp_path / "empty.toml",
        tmp_path / "verified-wheels",
        tmp_path / "requirements.txt",
        "/framework/bin/uv",
    )
    assert venv == [
        "/framework/bin/uv",
        "venv",
        "--no-project",
        "--python",
        "/python",
        "--no-python-downloads",
        "--config-file",
        str(tmp_path / "empty.toml"),
        str(tmp_path / "venv"),
    ]
    assert {
        "--offline",
        "--no-build",
        "--strict",
        "--allow-empty-requirements",
        "--require-hashes",
        "--no-index",
        "--find-links",
    }.issubset(sync)
    assert sync[-1] == str(tmp_path / "requirements.txt")
    assert "UV_INDEX_URL" not in env
    assert set(env) == {"PATH"}


@pytest.mark.parametrize(
    "lock",
    [
        "source = 'git+https://example.invalid/x'",
        "\n".join(
            (
                "[[package]]",
                "name = 'fixture-pkg'",
                "version = '1'",
                "source = { git = 'https://example.invalid/x' }",
            )
        ),
        "\n".join(
            (
                "[[package]]",
                "name = 'fixture-pkg'",
                "version = '1'",
                "source = { registry = 'https://mirror.invalid/simple' }",
            )
        ),
        "\n".join(
            (
                "[[package]]",
                "name = 'fixture-pkg'",
                "version = '1'",
                "source = { registry = 'https://pypi.org/simple' }",
                "sdist = { url = 'https://files.pythonhosted.org/x.tar.gz' }",
            )
        ),
    ],
)
def test_dependency_preflight_rejects_untrusted_sources_before_execution(
    tmp_path: Path, lock: str
) -> None:
    _metadata(tmp_path, lock=lock)
    with pytest.raises(SupplyChainError):
        validate_candidate_dependencies(tmp_path)


@pytest.mark.parametrize(
    "project_extra",
    [
        "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n",
        "[tool.uv.sources]\nfixture-pkg = { path = '../fixture-pkg' }\n",
        "[dependency-groups]\ntest = ['pytest']\n",
    ],
)
def test_candidate_build_groups_and_sources_fail_before_uv(
    tmp_path: Path, project_extra: str
) -> None:
    _metadata(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8") + project_extra, encoding="utf-8")

    with pytest.raises(SupplyChainError, match="candidate_dependency_source_forbidden"):
        validate_candidate_dependencies(tmp_path)


@pytest.mark.parametrize(
    "dependency",
    [
        "fixture-pkg; python_version >= '3.12'",
        "fixture-pkg[extra]==1.0",
        "fixture-pkg>=1.0",
    ],
)
def test_marker_extra_and_nonexact_requirements_fail_before_uv(
    tmp_path: Path, dependency: str
) -> None:
    _metadata(tmp_path, (dependency,))
    with pytest.raises(SupplyChainError, match="candidate_dependency_source_forbidden"):
        validate_candidate_dependencies(tmp_path)


def _wheel(store: Path) -> tuple[str, str, int]:
    store.mkdir()
    filename = "fixture_pkg-1.0-py3-none-any.whl"
    path = store / filename
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixture_pkg/__init__.py", "VALUE = 'trusted'\n")
        archive.writestr(
            "fixture_pkg-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: fixture-pkg\nVersion: 1.0\n",
        )
        archive.writestr(
            "fixture_pkg-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("fixture_pkg-1.0.dist-info/RECORD", "")
    return filename, f"sha256:{sha256(path.read_bytes()).hexdigest()}", path.stat().st_size


def _locked_wheel(root: Path, digest: str, size: int) -> None:
    _metadata(
        root,
        ("fixture-pkg==1.0",),
        "version = 1\n"
        "revision = 1\n"
        "requires-python = '>=3.12'\n"
        "\n[[package]]\n"
        "name = 'candidate'\n"
        "version = '0'\n"
        "source = { virtual = '.' }\n"
        "dependencies = [{ name = 'fixture-pkg' }]\n"
        "\n[[package]]\n"
        "name = 'fixture-pkg'\n"
        "version = '1.0'\n"
        "source = { registry = 'https://pypi.org/simple' }\n"
        "wheels = [{ "
        "url = 'https://files.pythonhosted.org/packages/fixture_pkg-1.0-py3-none-any.whl', "
        f"hash = '{digest}', size = {size} }}]\n",
    )


def _source_files(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_locked_wheel_is_hash_size_verified_and_installed_from_run_local_store(
    tmp_path: Path,
) -> None:
    store = tmp_path / "trusted-store"
    _, digest, size = _wheel(store)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _locked_wheel(candidate, digest, size)
    source_before = _source_files(candidate)

    closure = validate_candidate_dependencies(candidate)
    assert isinstance(closure, AdmittedLockClosure)
    assert closure.distributions == {("fixture-pkg", "1.0")}
    assert closure.entries[0].wheels[0].filename == "fixture_pkg-1.0-py3-none-any.whl"
    assert compile_sbom(candidate) == {
        "schema_version": "sbom@1",
        "root": {"name": "candidate", "version": "0", "license_state": "unknown"},
        "dependencies": [
            {
                "name": "fixture-pkg",
                "version": "1.0",
                "license_state": "unknown",
                "wheels": [
                    {
                        "filename": "fixture_pkg-1.0-py3-none-any.whl",
                        "digest": digest,
                        "size": size,
                    }
                ],
            }
        ],
        "admitted_lock_closure": {
            "entries": [
                {
                    "name": "fixture-pkg",
                    "version": "1.0",
                    "wheels": [
                        {
                            "filename": "fixture_pkg-1.0-py3-none-any.whl",
                            "digest": digest,
                            "size": size,
                        }
                    ],
                }
            ]
        },
    }

    with prepare_candidate(candidate, store) as prepared:
        assert prepared.admitted_lock_closure == closure
        result = __import__("subprocess").run(
            [prepared.python, "-c", "import fixture_pkg; assert fixture_pkg.VALUE == 'trusted'"],
            check=False,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    assert source_before == _source_files(candidate)


def test_empty_stdlib_only_closure_passes_without_a_wheel_store(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _metadata(candidate)

    assert validate_candidate_dependencies(candidate).entries == ()
    assert compile_sbom(candidate) == {
        "schema_version": "sbom@1",
        "root": {"name": "candidate", "version": "0", "license_state": "unknown"},
        "dependencies": [],
        "admitted_lock_closure": {"entries": []},
    }
    with prepare_candidate(candidate) as prepared:
        assert prepared.admitted_lock_closure.entries == ()
        result = __import__("subprocess").run(
            [prepared.python, "-c", "import json; assert json.dumps({'ok': True})"],
            check=False,
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0, result.stderr


def test_prepare_uses_only_framework_cwd_and_two_fixed_uv_commands(
    tmp_path: Path, monkeypatch
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _metadata(candidate)
    import agent_world.supply_chain as supply_chain

    original_run = supply_chain.subprocess.run
    commands: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def recording_run(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        capture_output: bool = False,
        text: Literal[True],
        check: bool = False,
        timeout: float | None = None,
    ) -> CompletedProcess[str]:
        commands.append((list(argv), cwd, env))
        return original_run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=capture_output,
            text=text,
            check=check,
            timeout=timeout,
        )

    monkeypatch.setattr(supply_chain.subprocess, "run", recording_run)
    with prepare_candidate(candidate):
        pass

    uv_commands = [item for item in commands if item[0][0].endswith("/uv")]
    assert [command[0][1:3] for command in uv_commands] == [
        ["--version"],
        ["venv", "--no-project"],
        ["pip", "sync"],
    ]
    for argv, cwd, env in uv_commands[1:]:
        assert cwd is not None and cwd != candidate
        assert str(candidate) not in argv
        assert env == {"PATH": __import__("os").defpath}


def test_duplicate_lock_version_fails_before_wheel_admission(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _metadata(
        candidate,
        ("fixture-pkg==1.0",),
        "version = 1\n"
        "\n[[package]]\nname = 'candidate'\nversion = '0'\nsource = { virtual = '.' }\n"
        "dependencies = [{ name = 'fixture-pkg' }]\n"
        "\n[[package]]\nname = 'fixture-pkg'\nversion = '1.0'\n"
        "source = { registry = 'https://pypi.org/simple' }\nwheels = []\n"
        "\n[[package]]\nname = 'fixture-pkg'\nversion = '2.0'\n"
        "source = { registry = 'https://pypi.org/simple' }\nwheels = []\n",
    )

    with pytest.raises(SupplyChainError, match="candidate_dependency_closure_ambiguous"):
        validate_candidate_dependencies(candidate)


def test_missing_or_tampered_trusted_wheel_fails_before_uv_sync(
    tmp_path: Path, monkeypatch
) -> None:
    store = tmp_path / "trusted-store"
    _, digest, size = _wheel(store)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _locked_wheel(candidate, digest, size)
    (store / "fixture_pkg-1.0-py3-none-any.whl").write_bytes(b"tampered")
    called = False

    def unexpected_run(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("uv must not execute")

    monkeypatch.setattr("agent_world.supply_chain.subprocess.run", unexpected_run)
    with pytest.raises(SupplyChainError, match="candidate_trusted_wheel_mismatch"):
        with prepare_candidate(candidate, store):
            pass
    assert not called
