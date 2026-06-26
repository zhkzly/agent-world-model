from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeTypeDefinition:
    name: str
    dry_run_behavior: str


NODE_TYPE_REGISTRY: dict[str, NodeTypeDefinition] = {
    "awm.import_fixture": NodeTypeDefinition(
        name="awm.import_fixture",
        dry_run_behavior="planned",
    ),
    "awm.check_environment": NodeTypeDefinition(
        name="awm.check_environment",
        dry_run_behavior="planned",
    ),
    "rollout.scripted": NodeTypeDefinition(
        name="rollout.scripted",
        dry_run_behavior="blocked",
    ),
    "verification.deterministic": NodeTypeDefinition(
        name="verification.deterministic",
        dry_run_behavior="blocked",
    ),
    "verification.reward_record": NodeTypeDefinition(
        name="verification.reward_record",
        dry_run_behavior="blocked",
    ),
}
