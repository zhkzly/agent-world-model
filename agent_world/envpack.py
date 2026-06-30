from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from agent_world.artifacts import stable_json
from agent_world.generated_project import run_packaged_generated_project_check


ENVPKG_SCHEMA_VERSION = "agent-world.envpkg.v1"
ENV_PACK_SCHEMA_VERSION = "agent-world.environment-pack.v1"
ENVIRONMENT_IDENTITY_KEY = ["environment_id", "version"]


def run_portable_envpkg_check(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    try:
        manifest = _read_json(package_dir / "manifest.json")
        runtime_index = _read_json(package_dir / "runtime" / "runtime_index.json")
        _validate_envpkg_identity(
            package_dir,
            expected_env_id=str(manifest.get("environment_id", "")),
            expected_version=str(manifest.get("version", "")),
        )
        file_errors = _validate_manifest_files(package_dir, manifest)
        package_check = run_packaged_generated_project_check(package_dir)
        success = not file_errors and package_check["success"] is True
        return {
            "check_id": "portable-envpkg-check",
            "success": success,
            "environment_id": manifest["environment_id"],
            "version": manifest["version"],
            "implementation_id": manifest["implementation_id"],
            "runtime_dir_ref": runtime_index["runtime_dir_ref"],
            "generated_project_package_check": package_check,
            "failure_class": "" if success else ("portable_envpkg_file_validation_failed" if file_errors else package_check.get("failure_class", "portable_envpkg_check_failed")),
            "recovery_suggestion": "" if success else ("; ".join(file_errors) if file_errors else package_check.get("recovery_suggestion", "")),
        }
    except Exception as exc:
        return {
            "check_id": "portable-envpkg-check",
            "success": False,
            "environment_id": "",
            "version": "",
            "implementation_id": "",
            "runtime_dir_ref": "",
            "generated_project_package_check": {},
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": str(exc),
        }


def assemble_environment_pack(envpkg_dirs: list[Path], *, out_dir: Path, pack_id: str) -> dict[str, Any]:
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    (out_dir / "packages").mkdir(parents=True, exist_ok=True)
    (out_dir / "archives").mkdir(parents=True, exist_ok=True)
    (out_dir / "exports").mkdir(parents=True, exist_ok=True)
    _write_runner_stub(out_dir)

    rows: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []
    verifier_rows: list[dict[str, Any]] = []
    release_rows: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for envpkg_dir in envpkg_dirs:
        source = Path(envpkg_dir)
        manifest = _read_json(source / "manifest.json")
        env_id = str(manifest["environment_id"])
        version = str(manifest["version"])
        identity = (env_id, version)
        if identity in seen:
            raise ValueError(f"duplicate environment identity: {env_id}@{version}")
        seen.add(identity)
        package_ref = f"packages/{env_id}/{version}/envpkg"
        dest = out_dir / package_ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest)
        _validate_envpkg_identity(dest, expected_env_id=env_id, expected_version=version)
        implementation_id = str(manifest.get("implementation_id", ""))
        row = {
            "environment_id": env_id,
            "version": version,
            "implementation_id": implementation_id,
            "package_ref": package_ref,
            "manifest_ref": f"{package_ref}/manifest.json",
            "runtime_index_ref": f"{package_ref}/runtime/runtime_index.json",
            "release_manifest_ref": f"{package_ref}/release/release_manifest.json",
            "contract_ref": f"{package_ref}/{manifest.get('contract_ref', 'runtime/project/contract.json')}",
            "split": manifest.get("split", "train"),
            "status": manifest.get("status", "packaged"),
        }
        rows.append(row)
        shutil.copy2(dest / "manifest.json", dest.parent / "manifest.json")
        task_rows.extend(_with_identity(_read_jsonl(dest / "spec" / "tasks.jsonl"), row))
        verifier_rows.extend(_with_identity(_read_jsonl(dest / "spec" / "verifiers.jsonl"), row))
        release_rows.append({**row, **_read_json(dest / "release" / "release_manifest.json")})
        check_rows.append({**row, **_read_json(dest / "checks" / "generated_project_package_check.json")})

    pack_manifest = {
        "schema_version": ENV_PACK_SCHEMA_VERSION,
        "pack_id": pack_id,
        "environment_count": len(rows),
        "environment_identity_key": list(ENVIRONMENT_IDENTITY_KEY),
        "index_refs": {
            "environments": "environments.jsonl",
            "tasks": "data/tasks.jsonl",
            "verifiers": "data/verifiers.jsonl",
            "releases": "data/releases.jsonl",
            "checks": "data/checks.jsonl",
        },
        "package_refs": [row["package_ref"] for row in rows],
        "runner": {"entrypoint": "runner/run.py", "commands": ["list", "load", "check", "replay", "export"]},
        "status": "packaged",
    }
    _write_json(out_dir / "pack.json", pack_manifest)
    _write_jsonl(out_dir / "environments.jsonl", rows)
    _write_jsonl(out_dir / "data" / "environments.jsonl", rows)
    _write_jsonl(out_dir / "data" / "tasks.jsonl", task_rows)
    _write_jsonl(out_dir / "data" / "verifiers.jsonl", verifier_rows)
    _write_jsonl(out_dir / "data" / "releases.jsonl", release_rows)
    _write_jsonl(out_dir / "data" / "checks.jsonl", check_rows)
    (out_dir / "README.md").write_text(_pack_readme(pack_id, len(rows)), encoding="utf-8")
    return {"success": True, "pack_id": pack_id, "environment_count": len(rows), "pack_dir": str(out_dir)}


def load_environment_pack(pack_dir: Path) -> dict[str, Any]:
    pack_dir = Path(pack_dir)
    return {"pack": _read_json(pack_dir / "pack.json"), "environments": _read_jsonl(pack_dir / "environments.jsonl")}


def run_environment_pack_check(pack_dir: Path) -> dict[str, Any]:
    pack_dir = Path(pack_dir)
    try:
        loaded = load_environment_pack(pack_dir)
        pack = loaded["pack"]
        environments = loaded["environments"]
        if pack.get("environment_count") != len(environments):
            return _pack_check_failure("environment_count_mismatch", "pack.json environment_count does not match environments.jsonl")
        seen: set[tuple[str, str]] = set()
        env_checks = []
        for row in environments:
            env_id = str(row.get("environment_id", ""))
            version = str(row.get("version", ""))
            identity = (env_id, version)
            if identity in seen:
                return _pack_check_failure("duplicate_environment_identity", f"duplicate environment identity: {env_id}@{version}")
            seen.add(identity)
            package_ref = str(row.get("package_ref", ""))
            expected_ref = f"packages/{env_id}/{version}/envpkg"
            if package_ref != expected_ref:
                return _pack_check_failure("package_ref_identity_mismatch", f"package_ref must be {expected_ref}")
            envpkg_dir = _safe_package_path(pack_dir, package_ref)
            _validate_envpkg_identity(envpkg_dir, expected_env_id=env_id, expected_version=version)
            env_checks.append(run_portable_envpkg_check(envpkg_dir))
        success = all(item.get("success") is True for item in env_checks)
        return {
            "check_id": "environment-pack-check",
            "success": success,
            "pack_id": pack.get("pack_id", ""),
            "environment_count": len(env_checks),
            "environment_checks": env_checks,
            "failure_class": "" if success else "environment_pack_envpkg_check_failed",
            "recovery_suggestion": "",
        }
    except Exception as exc:
        return _pack_check_failure(exc.__class__.__name__, str(exc))


def _validate_envpkg_identity(package_dir: Path, *, expected_env_id: str, expected_version: str) -> None:
    manifest = _read_json(package_dir / "manifest.json")
    runtime_index = _read_json(package_dir / "runtime" / "runtime_index.json")
    release = _read_json(package_dir / "release" / "release_manifest.json")
    for name, payload in [("manifest", manifest), ("runtime_index", runtime_index), ("release_manifest", release)]:
        if str(payload.get("environment_id")) != expected_env_id:
            raise ValueError(f"{name} environment_id mismatch: expected {expected_env_id}")
    if str(manifest.get("version")) != expected_version or str(runtime_index.get("version")) != expected_version or str(release.get("version")) != expected_version:
        raise ValueError(f"envpkg version mismatch: expected {expected_version}")
    implementation_id = str(manifest.get("implementation_id", ""))
    if implementation_id and str(runtime_index.get("project_id")) != implementation_id:
        raise ValueError("runtime_index implementation/project id mismatch")


def _validate_manifest_files(package_dir: Path, manifest: dict[str, Any]) -> list[str]:
    errors = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            errors.append("manifest files entries must be objects")
            continue
        rel = str(item.get("path", ""))
        try:
            path = _safe_package_path(package_dir, rel)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"missing file: {rel}")
            continue
        expected = str(item.get("sha256", ""))
        if expected and _file_sha256(path) != expected:
            errors.append(f"hash mismatch: {rel}")
    return errors


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_package_path(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise ValueError(f"unsafe package-relative path: {relative_path}")
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"package path escapes root: {relative_path}") from exc
    return path


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(value) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row must be an object: {path}")
        rows.append(value)
    return rows


def _pack_check_failure(failure_class: str, recovery: str) -> dict[str, Any]:
    return {
        "check_id": "environment-pack-check",
        "success": False,
        "pack_id": "",
        "environment_count": 0,
        "environment_checks": [],
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }


def _with_identity(items: list[dict[str, Any]], row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": row["environment_id"],
            "version": row["version"],
            "implementation_id": row["implementation_id"],
            **item,
        }
        for item in items
    ]


def _write_runner_stub(out_dir: Path) -> None:
    runner_dir = out_dir / "runner" / "agent_world_envpack"
    runner_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "runner" / "run.py").write_text(
        "from agent_world_envpack.cli import main\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    (runner_dir / "__init__.py").write_text('"""Portable Agent World environment pack runner."""\n', encoding="utf-8")
    (runner_dir / "cli.py").write_text(
        "def main(argv=None):\n    print('agent_world_envpack runner stub')\n    return 0\n",
        encoding="utf-8",
    )
    for name in ["loader.py", "checker.py", "replay.py"]:
        (runner_dir / name).write_text('"""Generated pack helper stub."""\n', encoding="utf-8")


def _pack_readme(pack_id: str, environment_count: int) -> str:
    return (
        "---\n"
        "tags:\n"
        "- agents\n"
        "- executable-environments\n"
        "---\n\n"
        f"# {pack_id}\n\n"
        f"Contains {environment_count} materialized Agent World generated environments.\n"
    )
