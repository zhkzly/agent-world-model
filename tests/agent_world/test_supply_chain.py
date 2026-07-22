from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from v3_fixture import build_judge_candidate_graph

from agent_world.artifact_store import ArtifactStore
from agent_world.builder import CandidateWorkspaceError, CandidateWorkspaceValidator
from agent_world.contracts import (
    ArtifactRef,
    EnvPackageMetadata,
    PackageFile,
    SbomLicenseMetadata,
    compile_environment_sbom,
    parse_envpkg_metadata_toml,
    sha256_digest,
)
from agent_world.judge import CleanCandidateBuilder, IsolationPolicy, IsolationUnavailable
from agent_world.judge.assurance import inspect_supply_chain


def _root_project() -> tuple[dict[str, object], dict[str, object]]:
    return (
        {
            "project": {
                "name": "supply-chain-probe",
                "version": "0.1.0",
                "requires-python": ">=3.12,<3.13",
                "dependencies": [],
            },
            "tool": {"uv": {"package": False}},
        },
        {
            "version": 1,
            "requires-python": "==3.12.*",
            "package": [
                {
                    "name": "supply-chain-probe",
                    "version": "0.1.0",
                    "source": {"virtual": "."},
                }
            ],
        },
    )


def _validate(pyproject: dict[str, object], lock: dict[str, object]) -> None:
    CandidateWorkspaceValidator._validate_dependency_policy(
        pyproject=pyproject,
        lock=lock,
        project_name="supply-chain-probe",
    )


def test_builder_accepts_only_the_virtual_non_installed_root_without_dependencies() -> None:
    pyproject, lock = _root_project()
    _validate(pyproject, lock)


def test_builder_rejects_an_editable_root_project() -> None:
    pyproject, lock = _root_project()
    packages = lock["package"]
    assert isinstance(packages, list)
    root = packages[0]
    assert isinstance(root, dict)
    root["source"] = {"editable": "."}

    with pytest.raises(CandidateWorkspaceError, match="virtual, non-installed root"):
        _validate(pyproject, lock)


def test_builder_requires_pyproject_to_declare_a_virtual_root() -> None:
    pyproject, lock = _root_project()
    pyproject.pop("tool")

    with pytest.raises(CandidateWorkspaceError, match="package=false"):
        _validate(pyproject, lock)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("build-system", "build-system hooks are prohibited"),
        ("direct-url", "direct URL/path dependency is prohibited"),
        ("custom-index", "dependency source configuration is prohibited"),
        ("git-lock", "path/Git/URL/editable sources are prohibited"),
        ("private-wheel", "approved files.pythonhosted.org HTTPS origin"),
    ),
)
def test_builder_rejects_unapproved_dependency_and_build_sources(
    mutation: str,
    message: str,
) -> None:
    pyproject, lock = _root_project()
    project = pyproject["project"]
    assert isinstance(project, dict)
    packages = lock["package"]
    assert isinstance(packages, list)
    if mutation == "build-system":
        pyproject["build-system"] = {
            "requires": ["setuptools"],
            "build-backend": "malicious_backend",
        }
    elif mutation == "direct-url":
        project["dependencies"] = ["evil @ https://evil.example/evil.whl"]
    elif mutation == "custom-index":
        pyproject["tool"] = {
            "uv": {"index-url": "https://packages.example/simple"}
        }
    else:
        project["dependencies"] = ["evil==1.0"]
        source = (
            {"git": "https://example.invalid/evil.git"}
            if mutation == "git-lock"
            else {"registry": "https://pypi.org/simple"}
        )
        wheel_url = (
            "https://files.pythonhosted.org/packages/aa/evil-1.0-py3-none-any.whl"
            if mutation == "git-lock"
            else "https://127.0.0.1/packages/aa/evil-1.0-py3-none-any.whl"
        )
        packages.append(
            {
                "name": "evil",
                "version": "1.0",
                "source": source,
                "wheels": [
                    {
                        "url": wheel_url,
                        "hash": f"sha256:{'1' * 64}",
                        "size": 10,
                    }
                ],
            }
        )
    with pytest.raises(CandidateWorkspaceError, match=message):
        _validate(pyproject, lock)


def test_envpkg_sbom_binds_exact_uv_inputs_without_inventing_license_facts() -> None:
    pyproject_bytes = b"""[project]
name = "portable-runtime"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["attrs==25.3.0"]

[tool.uv]
package = false
"""
    wheel_hash = f"sha256:{'1' * 64}"
    lock_bytes = f'''version = 1
requires-python = "==3.12.*"

[[package]]
name = "portable-runtime"
version = "0.1.0"
source = {{ virtual = "." }}

[[package]]
name = "attrs"
version = "25.3.0"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "https://files.pythonhosted.org/packages/attrs.whl", hash = "{wheel_hash}", size = 42 }},
]
'''.encode()
    license_bytes = b"candidate project license text\n"
    files = (
        PackageFile(
            path="pyproject.toml",
            role="configuration",
            content_hash=sha256_digest(pyproject_bytes),
            size_bytes=len(pyproject_bytes),
        ),
        PackageFile(
            path="uv.lock",
            role="dependency_lock",
            content_hash=sha256_digest(lock_bytes),
            size_bytes=len(lock_bytes),
        ),
        PackageFile(
            path="LICENSE",
            role="license",
            content_hash=sha256_digest(license_bytes),
            size_bytes=len(license_bytes),
        ),
    )

    sbom = compile_environment_sbom(
        package_id="env:portable-runtime",
        version="1.0.0",
        files=files,
        pyproject_bytes=pyproject_bytes,
        uv_lock_bytes=lock_bytes,
    )

    assert sbom.virtual_root.source == "virtual:."
    assert sbom.virtual_root.license.status == "unknown"
    assert sbom.virtual_root.license.expression is None
    assert len(sbom.registry_dependencies) == 1
    dependency = sbom.registry_dependencies[0]
    assert dependency.name == "attrs"
    assert dependency.registry == "https://pypi.org/simple"
    assert dependency.wheels[0].content_hash == wheel_hash
    assert dependency.wheels[0].size_bytes == 42
    assert dependency.license.status == "unknown"
    assert sbom.candidate_license_files[0].path == "LICENSE"
    assert sbom.candidate_license_files[0].content_hash == sha256_digest(license_bytes)


def test_sbom_license_contract_can_express_judge_verified_metadata_but_not_self_assert_it() -> None:
    evidence_ref = ArtifactRef(
        artifact_id="judge:supply-chain-license",
        revision_id=sha256_digest(b"license-evidence-revision"),
        artifact_type="judge.supply_chain_evidence",
        content_hash=sha256_digest(b"license-evidence-content"),
        media_type="application/json",
        size_bytes=64,
    )
    verified = SbomLicenseMetadata(
        status="verified",
        expression="MIT",
        evidence_refs=(evidence_ref,),
    )
    assert verified.status == "verified"

    with pytest.raises(ValueError, match="unknown license metadata"):
        SbomLicenseMetadata(status="unknown", expression="MIT")
    with pytest.raises(ValueError, match="requires expression and Judge evidence"):
        SbomLicenseMetadata(status="verified", expression="MIT")


@pytest.mark.asyncio
async def test_supply_gate_rejects_a_real_installed_component_absent_from_uv_lock(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = ArtifactStore(state_root / "artifacts")
    graph = build_judge_candidate_graph(state_root, store)
    isolation = IsolationPolicy(purpose="build")
    try:
        await isolation.ensure_available()
    except IsolationUnavailable as exc:
        pytest.skip(f"real bubblewrap isolation unavailable: {exc.code}: {exc}")
    builder = CleanCandidateBuilder(
        build_isolation=isolation,
        uv_path=graph.uv_path,
        uv_cache_dir=graph.uv_cache_dir,
        timeout_seconds=60,
    )

    async with builder.materialize(
        graph.workspace,
        expected_source_files=graph.candidate_manifest.files,
        expected_source_tree_digest=graph.candidate_manifest.candidate_source_tree_digest,
    ) as clean:
        site_packages = next((clean.root / ".venv").glob("lib/python*/site-packages"))
        rogue = site_packages / "rogue-1.0.dist-info"
        rogue.mkdir()
        metadata = (
            b"Metadata-Version: 2.4\n"
            b"Name: rogue\n"
            b"Version: 1.0\n"
            b"License-Expression: MIT\n\n"
        )
        (rogue / "METADATA").write_bytes(metadata)
        evidence = inspect_supply_chain(
            evidence_id="evidence:real-installed-lock-mismatch",
            candidate_ref=graph.candidate_ref,
            root=clean.root,
            manifest=graph.candidate_manifest,
            implementation_lineage_ref=graph.candidate_manifest.implementation_lineage_ref,
            implementation_lineage=graph.implementation_lineage,
            installed_tree_hash=sha256_digest(
                clean.installed_tree_hash.encode("utf-8") + metadata
            ),
        )

    assert evidence.status == "fail"
    assert not evidence.lock_install_closed
    assert "supply_installed_not_locked" in evidence.failure_codes
    assert "supply_installed_closure_mismatch" in evidence.failure_codes


def test_envpkg_toml_has_a_strict_canonical_round_trip_without_manifest_hash_cycle() -> None:
    digest = sha256_digest(b"portable-metadata-commitment")
    metadata = EnvPackageMetadata(
        package_id="env:portable-runtime",
        version="1.0.0",
        runtime_launch_hash=digest,
        runtime_argv=(".venv/bin/python", "runtime.py"),
        runtime_workdir=".",
        runtime_paths=("runtime.py",),
        task_materializer_descriptor_hash=digest,
        task_materializer_entrypoint="task_materializer:materialize",
        task_materializer_path="task_materializer.py",
        public_self_check_descriptor_hash=digest,
        public_self_check_path="public_check.py",
        world_spec_hash=digest,
        world_boundary_hash=digest,
        candidate_source_tree_digest=digest,
        dependency_lock_hash=digest,
        judge_report_revision_id=digest,
        judge_report_content_hash=digest,
        integration_report_revision_id=digest,
        integration_report_content_hash=digest,
        release_dossier_revision_id=digest,
        release_dossier_content_hash=digest,
        telemetry_summary_revision_id=digest,
        telemetry_summary_content_hash=digest,
        provenance_hash=digest,
        assurance_hash=digest,
        fidelity_hash=digest,
        sbom_hash=digest,
    )
    raw = metadata.stable_toml_bytes()

    assert parse_envpkg_metadata_toml(raw) == metadata
    assert b"manifest_hash" not in raw
    with pytest.raises(ValueError, match="canonical flat TOML"):
        parse_envpkg_metadata_toml(raw.replace(b"format =", b"format  =", 1))


@pytest.mark.asyncio
async def test_real_build_sandbox_denies_a_hook_that_mutates_candidate_source(
    tmp_path: Path,
) -> None:
    isolation = IsolationPolicy(purpose="build")
    try:
        await isolation.ensure_available()
    except IsolationUnavailable as exc:
        pytest.skip(f"real bubblewrap isolation unavailable: {exc.code}: {exc}")

    source = tmp_path / "source"
    source.mkdir()
    original = b"SOURCE_BYTES_MUST_NOT_CHANGE\n"
    (source / "runtime.py").write_bytes(original)
    (source / "malicious_build_hook.py").write_text(
        """from pathlib import Path
try:
    Path('/workspace/runtime.py').write_text('MUTATED')
except OSError as exc:
    Path('/state/mutation-result').write_text(type(exc).__name__)
    raise
""",
        encoding="utf-8",
    )
    (source / ".venv").mkdir()
    state = tmp_path / "state"
    state.mkdir()
    command = isolation.wrap_command(
        workspace=source,
        cwd_relative=".",
        argv=("/usr/bin/python3", "malicious_build_hook.py"),
        state_dir=state,
        visible_workspace_paths=("runtime.py", "malicious_build_hook.py"),
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin"},
        start_new_session=True,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

    assert process.returncode not in {None, 0}, (stdout, stderr)
    assert (state / "mutation-result").read_text(encoding="utf-8") in {
        "OSError",
        "PermissionError",
    }
    assert (source / "runtime.py").read_bytes() == original
    assert os.stat(source / "runtime.py", follow_symlinks=False).st_nlink == 1
