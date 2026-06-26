from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from awmx.artifacts.schemas import RewardRecord, RunSpec, TaskSpec, ValidationError, VerifierSpec


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class VerificationContext:
    run_spec: RunSpec
    task: TaskSpec
    output_dir: Path


class DeterministicVerifier:
    def __init__(
        self,
        *,
        verifier_spec: VerifierSpec,
        verify_fn: Callable[[VerificationContext], dict[str, Any]],
    ) -> None:
        self.verifier_spec = verifier_spec
        self.verify_fn = verify_fn

    def verify(self, *, run_spec: RunSpec, task: TaskSpec, output_dir: Path) -> RewardRecord:
        if run_spec.task_id != task.id:
            raise ValidationError(f"run_spec.task_id {run_spec.task_id} does not match task {task.id}")
        if self.verifier_spec.target_task_id != task.id:
            raise ValidationError(
                f"verifier target_task_id {self.verifier_spec.target_task_id} does not match task {task.id}"
            )
        if self.verifier_spec.deterministic is not True:
            raise ValidationError("DeterministicVerifier requires verifier_spec.deterministic to be true")
        result = self.verify_fn(VerificationContext(run_spec=run_spec, task=task, output_dir=Path(output_dir)))
        if not isinstance(result.get("passed"), bool):
            raise ValidationError("deterministic verifier must return a boolean passed field")

        passed = result["passed"]
        score_key = "passed" if passed else "failed"
        score = float(self.verifier_spec.reward_mapping.get(score_key, 1.0 if passed else 0.0))
        verifier_source_uri = self.verifier_spec.source.get("uri")
        if not isinstance(verifier_source_uri, str) or not verifier_source_uri.strip():
            raise ValidationError("verifier source.uri is required to create a replayable reward")

        evidence: dict[str, Any] = {}
        if "checks" in result:
            evidence["checks"] = result["checks"]
        elif "verifier_outputs" in result:
            evidence["verifier_outputs"] = result["verifier_outputs"]
        else:
            raise ValidationError("deterministic verifier result must include checks or verifier_outputs")

        return RewardRecord(
            id=f"reward.{run_spec.id}",
            version="0.1.0",
            created_at=_utc_now(),
            source={
                "kind": "verifier",
                "uri": verifier_source_uri,
                "verifier_id": self.verifier_spec.id,
                "verifier_type": self.verifier_spec.verifier_type,
            },
            metadata={"deterministic": True},
            run_id=run_spec.id,
            task_id=task.id,
            verifier_id=self.verifier_spec.id,
            passed=passed,
            score=score,
            evidence=evidence,
            failure_reason=result.get("failure_reason"),
        )
