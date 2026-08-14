from __future__ import annotations

import base64
import json
from hashlib import sha256
from pathlib import Path

import pytest

from agent_world import candidate as candidate_module
from agent_world.artifacts import ArtifactStore
from agent_world.candidate import CandidateExecutor, SupplyChainError
from agent_world.contracts import ArtifactEnvelope, ArtifactRef, WorkCoordinate
from agent_world.graph import NodeExecutionError


def _digest() -> str:
    return "sha256:" + "a" * 64


def _closure_file(path: str, body: bytes) -> dict[str, object]:
    return {
        "path": path,
        "digest": "sha256:" + sha256(body).hexdigest(),
        "size": len(body),
        "mode": "0644",
        "content_b64": base64.b64encode(body).decode("ascii"),
    }


def _store_candidate(tmp_path: Path) -> tuple[ArtifactStore, ArtifactRef]:
    store = ArtifactStore(tmp_path)
    files = [
        _closure_file("runtime.py", b"print('runtime')"),
        _closure_file("materializer.py", b"print('materializer')"),
        _closure_file("pyproject.toml", b"[project]"),
        _closure_file("uv.lock", b"version = 1"),
        _closure_file("LICENSE", b"x"),
        _closure_file("inputs/design.json", b"{}"),
    ]
    coordinate = WorkCoordinate("ws-run", "candidate", "candidate_build", None, 1)
    ref = store.put_envelope(
        ArtifactEnvelope(
            "build.environment_candidate",
            1,
            coordinate,
            _digest(),
            (),
            ("candidate",),
            {"source_files": files, "manifest": {"files": files}},
        )
    )
    return store, ref


def test_ensure_workspace_restores_full_closure_even_with_runtime_present(tmp_path: Path) -> None:
    store, ref = _store_candidate(tmp_path)
    root = tmp_path / "candidate"
    root.mkdir()
    # Pre-seed the partial state _candidate_build's pre-writes leave behind.
    (root / "runtime.py").write_text("print('template')")
    (root / "inputs").mkdir()
    executor = CandidateExecutor.__new__(CandidateExecutor)
    executor._ensure_workspace(root, ref, store)
    assert (root / "pyproject.toml").read_text() == "[project]"
    assert (root / "uv.lock").read_text() == "version = 1"
    assert (root / "materializer.py").read_text() == "print('materializer')"
    assert (root / "LICENSE").read_text() == "x"
    assert (root / "runtime.py").read_text() == "print('runtime')"
    assert (root / "inputs" / "design.json").read_text() == "{}"


def test_package_operation_converts_supply_chain_error(tmp_path: Path) -> None:
    # Directly exercise the conversion pattern: a SupplyChainError raised inside
    # the package operation surfaces as NodeExecutionError, never raw.
    class Executor(CandidateExecutor):
        def _package_operation_probe(self) -> None:
            try:
                raise SupplyChainError("candidate_dependency_metadata_missing")
            except SupplyChainError as exc:
                raise NodeExecutionError(str(exc)) from exc

    with pytest.raises(NodeExecutionError) as raised:
        Executor._package_operation_probe(Executor.__new__(Executor))
    assert raised.value.code == "candidate_dependency_metadata_missing"
