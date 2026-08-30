from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import agent_env_foundry.qualification_runner as runner_module
from agent_env_foundry.qualification_contracts import (
    NativeVerificationResult,
    PublicSurfaceManifest,
)
from agent_env_foundry.qualification_runner import QualificationBudget
from agent_env_foundry.qualification_v2 import validate_qualification_case_outcome
from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    AtomCheckResult,
    CapabilitySpec,
    PublicValueSource,
    RenderingSpec,
    TraceEvent,
)


def test_noop_qualification_accepts_unchanged_collateral_but_not_task_completion() -> None:
    semantic = AtomCheckResult(
        initially_satisfied=False,
        satisfied=False,
        required_effects_ok=False,
        collateral_ok=True,
        answer_ok=False,
        process_ok=False,
        report_values={},
        failure_codes=("REQUIRED_EFFECT_MISSING",),
    )
    verifier = NativeVerificationResult(
        required_effects_ok=False,
        collateral_ok=True,
        failure_codes=("REQUIRED_EFFECT_MISSING",),
    )

    validate_qualification_case_outcome("noop", semantic, verifier)

    for bad_semantic, bad_verifier in (
        (replace(semantic, collateral_ok=False), verifier),
        (semantic, replace(verifier, collateral_ok=False)),
    ):
        with pytest.raises(runner_module.QualificationV2Error) as caught:
            validate_qualification_case_outcome("noop", bad_semantic, bad_verifier)
        assert caught.value.code == "qualification_case_outcome_invalid"


def test_answer_source_evidence_is_required_only_for_a_satisfied_positive_case() -> None:
    failed = AtomCheckResult(
        initially_satisfied=False,
        satisfied=False,
        required_effects_ok=True,
        collateral_ok=True,
        answer_ok=False,
        process_ok=False,
        report_values={"code": "PATH_NOT_FOUND"},
        failure_codes=("PROCESS_EVIDENCE_MISSING",),
    )
    passed = replace(
        failed,
        satisfied=True,
        answer_ok=True,
        process_ok=True,
        failure_codes=(),
    )
    verifier = NativeVerificationResult(True, True, ())

    assert runner_module._answer_evidence_required("positive", passed, verifier)
    assert not runner_module._answer_evidence_required("positive", failed, verifier)
    assert not runner_module._answer_evidence_required("noop", failed, verifier)


def test_qualification_budget_is_bounded_and_positive() -> None:
    budget = QualificationBudget(
        start_seed=7,
        start_limit=3,
        max_provider_turns=9,
    )
    assert budget.start_seed == 7
    assert budget.start_limit == 3
    assert budget.max_provider_turns == 9

    for field in ("start_limit", "max_provider_turns"):
        values = {
            "start_seed": 0,
            "start_limit": 1,
            "max_provider_turns": 1,
        }
        values[field] = 0
        with pytest.raises(ValueError, match=field):
            QualificationBudget(**values)


def test_task_kind_must_match_observed_semantic_state_change() -> None:
    unchanged = {"count": 1}
    changed = {"count": 2}
    query = SimpleNamespace(capability_id="query", task_kind="query")
    process = SimpleNamespace(capability_id="process", task_kind="process")
    state_change = SimpleNamespace(capability_id="state", task_kind="state_change")

    runner_module._validate_task_kind_transition(query, unchanged, unchanged)
    runner_module._validate_task_kind_transition(process, unchanged, unchanged)
    runner_module._validate_task_kind_transition(state_change, unchanged, changed)

    for capability, before, after in (
        (query, unchanged, changed),
        (process, unchanged, changed),
        (state_change, unchanged, unchanged),
    ):
        with pytest.raises(runner_module.QualificationV2Error) as caught:
            runner_module._validate_task_kind_transition(capability, before, after)
        assert caught.value.code == "qualification_task_kind_mismatch"


def _answer_surface() -> PublicSurfaceManifest:
    return PublicSurfaceManifest(
        start_schema={"type": "object", "additionalProperties": True},
        reset_observation_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        tool_specs=(
            {
                "name": "increment",
                "description": "Increment the public counter.",
                "input_schema": {
                    "type": "object",
                    "properties": {"amount": {"type": "integer", "const": 1}},
                    "required": ["amount"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "audit",
                "description": "Read an optional audit value.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        ),
        public_documents_digest="a" * 64,
    )


def _answer_capability(
    fields: tuple[AnswerFieldSpec, ...],
) -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="increment",
        requirement_ids=("REQ-1",),
        workflow_ids=("counter",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="increment the counter",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={
            "type": "object",
            "properties": {"expected_count": {"type": "integer"}},
            "required": ["expected_count"],
            "additionalProperties": False,
        },
        facets=(),
        conditions=(),
        answer_fields=fields,
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("increment", "counter", "report the public count"),
    )


def _field(field_id: str, source: PublicValueSource) -> AnswerFieldSpec:
    return AnswerFieldSpec(
        field_id,
        {"type": ["integer", "null"]},
        field_id.replace("_", " "),
        source,
    )


def test_answer_source_contract_uses_the_full_observation_root() -> None:
    count = _field(
        "count",
        PublicValueSource("tool_observation", "increment", "/data/count", None),
    )
    descriptor = _field(
        "descriptor_count",
        PublicValueSource("task_descriptor", None, "/expected_count", None),
    )
    reset = _field("reset_count", PublicValueSource("reset", None, "/count", None))
    constant = _field(
        "fixed_amount",
        PublicValueSource("tool_schema_constant", "increment", "/amount", 1),
    )
    capability = _answer_capability((count, descriptor, reset, constant))

    runner_module._validate_answer_field_source_contract((capability,), _answer_surface())

    old_data_root = replace(
        capability,
        answer_fields=(
            replace(
                count,
                public_source=PublicValueSource("tool_observation", "increment", "/count", None),
            ),
            descriptor,
            reset,
            constant,
        ),
    )
    with pytest.raises(runner_module.QualificationV2Error) as pointer_error:
        runner_module._validate_answer_field_source_contract((old_data_root,), _answer_surface())
    assert pointer_error.value.code == "qualification_answer_source_pointer_invalid"


def test_answer_source_evidence_binds_report_value_to_real_public_occurrence() -> None:
    count = _field(
        "count",
        PublicValueSource("tool_observation", "increment", "/data/count", None),
    )
    optional = _field(
        "optional_audit",
        PublicValueSource("tool_observation", "audit", "/data/value", None),
    )
    capability = _answer_capability((count, optional))
    trace = (
        TraceEvent(
            1,
            "increment",
            {"amount": 1},
            {"ok": True, "data": {"count": 1}, "error": None},
        ),
    )

    evidence = runner_module._answer_field_evidence(
        capability,
        SimpleNamespace(public_descriptor={"expected_count": 1}),
        {"count": 0},
        trace,
        {"count": 1, "optional_audit": None},
    )
    count_evidence = next(item for item in evidence if item["field_id"] == "count")
    assert count_evidence["occurrences"] == [
        {
            "kind": "tool_observation",
            "trace_event_seq": 1,
            "json_pointer": "/data/count",
            "value": 1,
        }
    ]

    with pytest.raises(runner_module.QualificationV2Error) as mismatch:
        runner_module._answer_field_evidence(
            capability,
            SimpleNamespace(public_descriptor={"expected_count": 1}),
            {"count": 0},
            trace,
            {"count": 2, "optional_audit": None},
        )
    assert mismatch.value.code == "qualification_answer_source_value_mismatch"
