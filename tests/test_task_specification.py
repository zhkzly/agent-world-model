from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.requirement_obligations import (
    ObligationApplicability,
    RequirementObligation,
)
from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    CapabilitySpec,
    PublicValueSource,
    RenderingSpec,
)
from agent_env_foundry.task_specification import (
    CandidateTaskProposal,
    PublicEvidenceRef,
    PublicSlotProposal,
    SamplerDescriptor,
    TaskSpecificationError,
    compile_direct_proposals,
    compile_task_semantic_section,
    compile_verifier_bundle,
)

RELEASE_ID = "a" * 64
CAPABILITY_ID = "CAP-GIT-UPDATE-COMMIT-PERSIST"
REQUIREMENT_ID = "REQ-GIT-002"
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id=CAPABILITY_ID,
        requirement_ids=(REQUIREMENT_ID,),
        workflow_ids=("WF-GIT-UPDATE",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="update and commit a tracked file",
        protected_binding_schema=OBJECT_SCHEMA,
        public_descriptor_schema=OBJECT_SCHEMA,
        facets=(),
        conditions=(),
        answer_fields=(
            AnswerFieldSpec(
                "created_commit_id",
                {"type": "string"},
                "created commit identifier",
                PublicValueSource(
                    "tool_observation",
                    "commit",
                    "/data/commit_id",
                    None,
                ),
            ),
        ),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("update and commit", "tracked file", "report commit id"),
    )


def _obligations() -> tuple[RequirementObligation, ...]:
    applicability = ObligationApplicability(
        "binding_eligible",
        capability_id=CAPABILITY_ID,
    )
    return (
        RequirementObligation(
            REQUIREMENT_ID,
            "effect",
            "Exactly the selected file is updated.",
            applicability,
        ),
        RequirementObligation(
            REQUIREMENT_ID,
            "effect",
            "One real commit contains the selected update.",
            applicability,
        ),
        RequirementObligation(
            REQUIREMENT_ID,
            "process",
            "The created commit is publicly confirmed after reopening.",
            applicability,
        ),
    )


def _proposal(
    obligations: tuple[RequirementObligation, ...],
    *,
    sampler_kind: str = "direct",
    evidence_digest: str = "b" * 64,
) -> CandidateTaskProposal:
    return CandidateTaskProposal(
        sampler=SamplerDescriptor(sampler_kind, "1"),
        release_id=RELEASE_ID,
        requirement_ids=(REQUIREMENT_ID,),
        obligation_ids=tuple(item.obligation_id for item in obligations),
        objective="Update one selected tracked file, commit it, and confirm persistence.",
        goal_shape="atom",
        capability_ids=(CAPABILITY_ID,),
        composition_rule_id=None,
        condition_id=None,
        public_slots=(PublicSlotProposal("target", CAPABILITY_ID, "one", ()),),
        public_evidence_refs=(PublicEvidenceRef("qualified_capability", evidence_digest),),
    )


def test_missing_requirement_obligation_is_rejected_before_witness_search() -> None:
    obligations = _obligations()
    incomplete = _proposal(obligations[:2])

    with pytest.raises(TaskSpecificationError) as caught:
        compile_task_semantic_section(
            incomplete,
            capabilities=(_capability(),),
            obligations=obligations,
        )

    assert caught.value.code == "applicable_obligation_coverage_mismatch"
    assert caught.value.details["missing_obligation_ids"] == [obligations[2].obligation_id]

    complete = _proposal(obligations)
    invented = replace(
        complete,
        obligation_ids=(*complete.obligation_ids, "f" * 64),
    )
    with pytest.raises(TaskSpecificationError) as invented_error:
        compile_task_semantic_section(
            invented,
            capabilities=(_capability(),),
            obligations=obligations,
        )
    assert invented_error.value.details["unexpected_obligation_ids"] == ["f" * 64]


def test_sampler_lineage_changes_proposal_evidence_but_not_task_truth() -> None:
    obligations = _obligations()
    direct = _proposal(obligations)
    graph = _proposal(
        obligations,
        sampler_kind="graph",
        evidence_digest="c" * 64,
    )

    assert direct.proposal_id != graph.proposal_id
    direct_semantics = compile_task_semantic_section(
        direct,
        capabilities=(_capability(),),
        obligations=obligations,
    )
    graph_semantics = compile_task_semantic_section(
        graph,
        capabilities=(_capability(),),
        obligations=obligations,
    )
    assert direct_semantics.semantic_digest == graph_semantics.semantic_digest

    verifier = compile_verifier_bundle(
        direct_semantics,
        capabilities=(_capability(),),
        obligations=obligations,
    )
    steps = {item.axis: item for item in verifier.steps}
    assert set(steps) == {
        "applicability",
        "required_effects",
        "answer",
        "process",
        "initial_non_vacuity",
    }
    assert len(steps["required_effects"].obligation_ids) == 2
    assert steps["process"].obligation_ids == (obligations[2].obligation_id,)
    assert steps["answer"].qualified_operation_ids == (f"{CAPABILITY_ID}:answer:created_commit_id",)

    assert replace(direct, sampler=SamplerDescriptor("programmatic", "1")).proposal_id

    semantic_variants = (
        replace(direct_semantics, objective="A different objective."),
        replace(direct_semantics, obligation_ids=direct_semantics.obligation_ids[:-1]),
        replace(
            direct_semantics,
            answer_operation_ids=(f"{CAPABILITY_ID}:answer:other",),
        ),
    )
    assert all(
        item.semantic_digest != direct_semantics.semantic_digest for item in semantic_variants
    )
    assert replace(verifier, steps=verifier.steps[:-1]).verifier_id != verifier.verifier_id


def test_direct_baseline_emits_the_same_common_proposal_boundary() -> None:
    obligations = _obligations()
    proposals = compile_direct_proposals(
        release_id=RELEASE_ID,
        capabilities=(_capability(),),
        obligations=obligations,
        task_goals={
            CAPABILITY_ID: ("Update one selected tracked file, commit it, and confirm persistence.")
        },
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.to_document()["format"] == "candidate-task-proposal/1"
    assert proposal.sampler.kind == "direct"
    assert set(proposal.obligation_ids) == {item.obligation_id for item in obligations}
    compile_task_semantic_section(
        proposal,
        capabilities=(_capability(),),
        obligations=obligations,
    )
