from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _seed_failed_direct_job(config_path: Path) -> str:
    state_root = config_path.parent / "state"
    config_path.write_text('state_root = "state"\n', encoding="utf-8")
    job_id = "generate-job:" + "a" * 24
    blob = json.dumps({"job_id": job_id, "kind": "generate"}).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()
    blob_path = state_root / "artifacts" / "blobs" / "sha256" / digest[:2] / digest
    blob_path.parent.mkdir(parents=True)
    blob_path.write_bytes(blob)
    head_path = state_root / "direct-jobs" / "heads" / ("b" * 64 + ".json")
    head_path.parent.mkdir(parents=True)
    head_path.write_text(
        json.dumps(
            {
                "status": "failed",
                "job_ref": {
                    "artifact_type": "control.environment_job",
                    "content_hash": f"sha256:{digest}",
                    "size_bytes": len(blob),
                },
            }
        ),
        encoding="utf-8",
    )
    return job_id


def _run_hook(script_name: str, config_path: Path) -> str:
    environment = os.environ.copy()
    environment["AGENT_WORLD_CONFIG"] = str(config_path)
    environment["TRELLIS_HOOKS"] = "1"
    environment.pop("TRELLIS_DISABLE_HOOKS", None)
    environment.pop("CODEX_NON_INTERACTIVE", None)
    result = subprocess.run(  # noqa: S603 - parameterized fixed repository hook filenames
        [sys.executable, str(_REPOSITORY_ROOT / ".codex" / "hooks" / script_name)],
        input=json.dumps({"cwd": str(_REPOSITORY_ROOT)}),
        text=True,
        capture_output=True,
        cwd=_REPOSITORY_ROOT,
        env=environment,
        check=True,
    )
    payload = json.loads(result.stdout)
    return payload["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize(
    "script_name",
    ("session-start.py", "inject-workflow-state.py"),
)
def test_failed_direct_job_injects_a_safe_observe_scene_pointer(
    tmp_path: Path,
    script_name: str,
) -> None:
    config_path = tmp_path / "config.toml"
    job_id = _seed_failed_direct_job(config_path)

    context = _run_hook(script_name, config_path)

    assert "<current-state>" in context
    assert f"observe scene {job_id}" in context
    assert "先读 scene.md" in context


def test_session_start_exposes_a_compact_navigation_map(tmp_path: Path) -> None:
    context = _run_hook("session-start.py", tmp_path / "config.toml")

    assert f"Project root: {_REPOSITORY_ROOT}" in context
    assert "## Phase Index" in context
    assert "Phase 1: Plan" in context
    assert "Request Triage" not in context
    assert "Planning Artifacts" not in context
    assert len(context) < 3_000


def test_session_start_caps_the_injected_spec_index_list() -> None:
    module = runpy.run_path(str(_REPOSITORY_ROOT / ".codex" / "hooks" / "session-start.py"))
    cap = module["_MAX_SESSION_START_SPEC_INDEXES"]
    bounded = module["_bounded_spec_index_paths"]
    paths = [f".trellis/spec/package-{index}/index.md" for index in range(cap + 3)]

    shown, omitted = bounded(paths)

    assert shown == paths[:cap]
    assert omitted == 3
