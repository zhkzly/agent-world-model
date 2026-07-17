from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_world.contracts import ArtifactRef, MutationIntent, ReachabilityPolicy


def _parent_ref() -> ArtifactRef:
    digest = "sha256:" + "a" * 64
    return ArtifactRef(
        artifact_id="package:parent",
        revision_id=digest,
        artifact_type="environment_package_manifest",
        content_hash=digest,
        media_type="application/json",
        size_bytes=1,
    )


@pytest.mark.parametrize(
    ("forged_field", "forged_value"),
    [
        ("identity_intent", "new_package"),
        ("expected_behavior_descriptors", ["claimed_novelty"]),
    ],
)
def test_policy_cannot_claim_identity_or_behavior_descriptors(
    forged_field: str,
    forged_value: object,
) -> None:
    parent = _parent_ref()
    payload = {
        "intent_id": "intent:malicious-policy",
        "parent_refs": [parent.model_dump(mode="json")],
        "primary_parent_ref": parent.model_dump(mode="json"),
        "operator": "tool_semantics",
        "operator_version": "1",
        "seed": 9,
        "target_coverage_dimensions": ["tool_semantics"],
        forged_field: forged_value,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MutationIntent.model_validate(payload)


def test_multiple_parents_are_only_a_composite_proposal() -> None:
    first = _parent_ref()
    second = first.model_copy(
        update={
            "artifact_id": "package:second",
            "revision_id": "sha256:" + "b" * 64,
            "content_hash": "sha256:" + "b" * 64,
        }
    )

    with pytest.raises(ValidationError, match="multiple parents require a composite operator"):
        MutationIntent(
            intent_id="intent:invalid-multi-parent",
            parent_refs=(first, second),
            primary_parent_ref=first,
            operator="tool_surface",
            operator_version="1",
            seed=1,
            target_coverage_dimensions=("tool_surface",),
        )


def test_unimplemented_serve_certification_cannot_enter_a_release_contract() -> None:
    with pytest.raises(ValidationError, match="Input should be 'sampled_release'"):
        ReachabilityPolicy.model_validate({"mode": "certify_before_serve"})
