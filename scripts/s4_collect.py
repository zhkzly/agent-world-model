"""Collect one frozen formal teacher batch through the existing S3 runtime."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Sequence
from pathlib import Path

from agent_env_foundry.episode_batch import run_episode_batch
from agent_env_foundry.learning_data import (
    LearningDataError,
    TeacherCohort,
    _read_persisted_manifest_views,
    read_s4_core_config,
    read_teacher_cohort,
    select_teacher_cohort,
    write_teacher_cohort,
)
from agent_env_foundry.preparation import prepare_release
from agent_env_foundry.public_agent import ResponsesPolicyDriver


def collect(
    *,
    config_path: Path,
    release_root: Path,
    task_store_root: Path,
    corpus_manifest_path: Path,
    output_root: Path,
) -> TeacherCohort:
    """Collect one exact S3 batch and publish its cold-valid teacher cohort."""

    config = read_s4_core_config(config_path)
    root = Path(output_root)
    if root.exists() or root.is_symlink():
        raise LearningDataError("OUTPUT_FINAL", "collection output root must be absent")
    with tempfile.TemporaryDirectory(prefix="agent-env-foundry-s4-prepare-") as cache:
        prepared = prepare_release(Path(release_root), Path(cache))
        if prepared.identity.release_id != config.release_id:
            raise LearningDataError(
                "RELEASE_MISMATCH", "prepared release_id differs from S4 config"
            )

        def fresh_driver() -> ResponsesPolicyDriver:
            return ResponsesPolicyDriver(policy_spec=config.teacher_policy)

        manifest = run_episode_batch(
            prepared,
            Path(task_store_root),
            Path(corpus_manifest_path),
            config.corpus_id,
            root,
            policy_spec=config.teacher_policy,
            policy_driver_factory=fresh_driver,
            rollouts_per_task=config.rollouts_per_task,
        )

    persisted_manifest, views = _read_persisted_manifest_views(root, manifest.batch_id)
    cohort = select_teacher_cohort(config, persisted_manifest, views)
    write_teacher_cohort(root, cohort)
    return read_teacher_cohort(root, config)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--task-store-root", required=True, type=Path)
    parser.add_argument("--corpus-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    collect(
        config_path=arguments.config,
        release_root=arguments.release_root,
        task_store_root=arguments.task_store_root,
        corpus_manifest_path=arguments.corpus_manifest,
        output_root=arguments.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
