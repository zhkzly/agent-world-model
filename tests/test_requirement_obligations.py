from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.release import validate_requirement_obligation_references
from agent_env_foundry.requirement_obligations import (
    ObligationApplicability,
    RequirementObligation,
    RequirementObligationError,
    requirement_obligation_from_clause,
    requirement_obligations_from_expected_document,
)
from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    CapabilitySpec,
    ConditionSpec,
    FacetSpec,
    PublicValueSource,
    RenderingSpec,
    StartCase,
)

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="CAP-GIT-UPDATE-COMMIT-PERSIST",
        requirement_ids=("REQ-GIT-002",),
        workflow_ids=("WF-GIT-UPDATE",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="update and commit",
        protected_binding_schema=OBJECT_SCHEMA,
        public_descriptor_schema=OBJECT_SCHEMA,
        facets=(FacetSpec("editable", "editable", {"type": "boolean"}, ("eq",)),),
        conditions=(
            ConditionSpec(
                "COND-GIT-CLEAN",
                "repository is clean",
                "world",
                ("CAP-GIT-UPDATE-COMMIT-PERSIST",),
                (),
                None,
                PublicValueSource("reset", None, "/clean", None),
            ),
        ),
        answer_fields=(
            AnswerFieldSpec(
                "commit_id",
                {"type": "string"},
                "commit identifier",
                PublicValueSource(
                    "tool_observation",
                    "commit",
                    "/data/commit_id",
                    None,
                ),
            ),
        ),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("update", "file", "report commit identifier"),
    )


def test_framework_derives_stable_obligation_identity_from_semantics() -> None:
    obligation = RequirementObligation(
        requirement_id="REQ-GIT-002",
        kind="process",
        canonical_text="Publicly confirm the created commit after reopening.",
        applicability=ObligationApplicability(
            kind="binding_eligible",
            capability_id="CAP-GIT-UPDATE-COMMIT-PERSIST",
        ),
    )

    document = obligation.to_document()
    assert len(obligation.obligation_id) == 64
    assert len(obligation.canonical_text_digest) == 64
    assert document["obligation_id"] == obligation.obligation_id
    assert document["applicability_handle"] == {
        "kind": "binding_eligible",
        "case_id": None,
        "capability_id": "CAP-GIT-UPDATE-COMMIT-PERSIST",
        "condition_id": None,
        "branch": None,
        "facet_name": None,
        "operator": None,
        "public_literal": None,
    }
    variants = (
        replace(obligation, requirement_id="REQ-GIT-003"),
        replace(obligation, kind="effect"),
        replace(obligation, canonical_text="Confirm a different relation."),
        replace(obligation, applicability=ObligationApplicability("always")),
    )
    assert all(item.obligation_id != obligation.obligation_id for item in variants)

    with pytest.raises(RequirementObligationError, match="JSON scalar"):
        ObligationApplicability(
            "facet_predicate",
            capability_id="CAP-GIT-UPDATE-COMMIT-PERSIST",
            facet_name="metadata",
            operator="eq",
            public_literal={"nested": True},
        )


@pytest.mark.parametrize("field", ("obligation_id", "canonical_text_digest"))
def test_canonical_clause_rejects_tampered_framework_identity(field: str) -> None:
    obligation = RequirementObligation(
        requirement_id="REQ-GIT-002",
        kind="effect",
        canonical_text="Exactly the selected file is updated and staged.",
        applicability=ObligationApplicability(
            kind="binding_eligible",
            capability_id="CAP-GIT-UPDATE-COMMIT-PERSIST",
        ),
    )
    clause = obligation.to_clause_document()
    clause[field] = "f" * 64

    with pytest.raises(RequirementObligationError, match="identity|digest"):
        requirement_obligation_from_clause(
            requirement_id=obligation.requirement_id,
            kind=obligation.kind,
            value=clause,
        )


def test_old_expected_semantics_format_has_no_compatibility_reader() -> None:
    with pytest.raises(RequirementObligationError, match="expected-task-semantics/2"):
        requirement_obligations_from_expected_document(
            {
                "format": "expected-task-semantics/1",
                "requirements": [],
                "capabilities": [],
                "composition_rules": [],
                "conditions": [],
            }
        )


def test_release_validates_obligation_handles_against_sealed_semantics() -> None:
    capability = _capability()
    obligations = (
        RequirementObligation(
            "REQ-GIT-002",
            "precondition",
            "The selected path is editable.",
            ObligationApplicability(
                "facet_predicate",
                capability_id=capability.capability_id,
                facet_name="editable",
                operator="eq",
                public_literal=True,
            ),
        ),
        RequirementObligation(
            "REQ-GIT-002",
            "process",
            "Confirm persistence after reopen.",
            ObligationApplicability(
                "condition_branch",
                condition_id="COND-GIT-CLEAN",
                branch="true",
            ),
        ),
        RequirementObligation(
            "REQ-GIT-002",
            "effect",
            "The initial regime is clean.",
            ObligationApplicability("start_case", case_id="clean-start"),
        ),
    )
    expected = {
        "conditions": [
            {
                "condition_id": "COND-GIT-CLEAN",
                "requirement_ids": ["REQ-GIT-002"],
            }
        ]
    }

    validate_requirement_obligation_references(
        obligations,
        (capability,),
        (StartCase("clean-start", None, ("clean",)),),
        expected,
    )

    with pytest.raises(RequirementObligationError, match="unknown StartCase"):
        validate_requirement_obligation_references(
            (
                replace(
                    obligations[2],
                    applicability=ObligationApplicability("start_case", case_id="missing"),
                ),
            ),
            (capability,),
            (StartCase("clean-start", None, ("clean",)),),
            expected,
        )

    broken = (
        replace(
            obligations[0],
            applicability=ObligationApplicability(
                "binding_eligible",
                capability_id="missing-capability",
            ),
        ),
        replace(
            obligations[2],
            applicability=ObligationApplicability("start_case", case_id="missing"),
        ),
    )
    with pytest.raises(RequirementObligationError) as caught:
        validate_requirement_obligation_references(
            broken,
            (capability,),
            (StartCase("clean-start", None, ("clean",)),),
            expected,
        )
    message = str(caught.value)
    assert "unknown capability" in message
    assert "unknown StartCase" in message
