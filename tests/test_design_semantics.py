from __future__ import annotations

import json
from dataclasses import replace
from itertools import chain
from types import MethodType, SimpleNamespace
from typing import Any, cast

import pytest

from agent_world import candidate as candidate_module
from agent_world.artifacts import ArtifactStore
from agent_world.candidate import CandidateExecutor
from agent_world.config import FoundrySettings
from agent_world.contracts import (
    ArtifactEnvelope,
    ArtifactRef,
    CandidateManifest,
    CitationCatalog,
    CitationCatalogItem,
    CorrectionPacket,
    EnvironmentRequest,
    EvidenceClaim,
    EvidenceGraph,
    GateResult,
    JudgeReport,
    ResearchPlan,
    SafeFailure,
    WorkCoordinate,
    digest_value,
    json_value,
)
from agent_world.design import (
    _RULE_DRAFT_SHAPE,
    _TASK_RULE_DRAFT_SHAPE,
    DesignError,
    DesignExecutor,
    _compile_rules,
    _direct_feedback,
    _text,
)
from agent_world.graph import design_graph
from agent_world.invocation import (
    CodexAgentBackend,
    DirectChatBackend,
    InvocationError,
    InvocationResult,
    _DirectFormatFailure,
)


def _digest() -> str:
    return "sha256:" + "a" * 64


def _rule(target: int, *, citation: bool = True) -> dict[str, Any]:
    return {
        "when": [],
        "effects": [{"target_semantic_index": target, "operation": "set", "value": "ok"}],
        "error_kind": None,
        "rationale": "bounded business rule",
        "citation_indexes": [1] if citation else [],
    }


def _task_rule(target: int, *, citation: bool = True) -> dict[str, Any]:
    rule = _rule(target, citation=citation)
    rule.pop("error_kind")
    return rule


def _task_requirement_source(target: int = 1) -> dict[str, Any]:
    return {
        "public_goal_fields": [target],
        "initial_rules": [_task_rule(target)],
        "success_rules": [_task_rule(target)],
        "failure_rules": [_task_rule(target)],
        "terminal_rules": [_task_rule(target)],
    }


def _architecture(tools: int = 2) -> dict[str, Any]:
    return {
        "boundary": {
            "name": "support",
            "purpose": "manage handoffs",
            "system_of_record": "support_db",
            "authority": "operator",
            "actors": ["operator"],
        },
        "entities": [
            {
                "name": "handoff",
                "purpose": "one work handoff",
                "fields": [
                    {
                        "name": "request_id",
                        "category": "identifier",
                        "required": True,
                    }
                ],
            }
        ],
        "tools": [
            {
                "name": f"tool_{index}",
                "purpose": f"perform handoff action {index}",
                "actor_names": ["operator"],
                "argument_fields": [
                    {
                        "name": f"request_{index}",
                        "category": "identifier",
                        "required": True,
                    }
                ],
                "result_fields": [
                    {
                        "name": f"status_{index}",
                        "category": "text",
                        "required": True,
                    }
                ],
            }
            for index in range(1, tools + 1)
        ],
        "known_divergences": [],
    }


def _shared() -> dict[str, Any]:
    return {
        "atomicity": [[1, 2]],
        "concurrency": [[1, 2]],
        "idempotency": [[1, 2]],
        "ordering": [],
        "compensation": [],
        "error_policy": "reject invalid requests",
    }


def _compiled_shared() -> dict[str, Any]:
    return {
        "tool_indexes": [1, 2],
        **_shared(),
        "error_policy": [
            {"tool_index": 1, "policy": "reject invalid requests"},
            {"tool_index": 2, "policy": "reject invalid requests"},
        ],
    }


@pytest.mark.parametrize(
    ("value", "condition"),
    (
        ([], "value must be a string"),
        ("   ", "value must be nonempty after stripping"),
        ("123456", "value must use at most 5 code points"),
    ),
)
def test_text_feedback_preserves_acceptance_and_names_exact_rejection(
    value: object, condition: str
) -> None:
    with pytest.raises(DesignError) as raised:
        _text(value, "example_invalid", 5, path="$.field")

    assert raised.value.correction is not None
    assert raised.value.correction.path == "$.field"
    assert raised.value.correction.violated_condition == condition
    assert raised.value.correction.expected_category == "string"
    assert _text(" value ", "example_invalid", 5, path="$.field") == "value"


def _curriculum_source(value: Any) -> dict[str, Any]:
    return {
        "families": [
            {
                "task_family_id": family["task_family_id"],
                "objective": family["objective"],
                "actor_index": family["actor_index"],
                "tool_indexes": family["tool_indexes"],
                "dimensions": family["difficulty_schema"]["dimensions"],
                "sampling_intent": family["sampling_intent"],
                "citation_indexes": family["citation_indexes"],
            }
            for family in json_value(value)["families"]
        ]
    }


class _Agent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.acquired_plans: list[ResearchPlan] = []
        self.synthesis_inputs: list[dict[str, Any]] = []
        self.values = iter(
            (
                {
                    "queries": ["support handoff api"],
                    "questions_to_resolve": ["Which state transitions are supported?"],
                },
                {
                    "claims": [
                        {
                            "statement": "The API records handoffs.",
                            "kind": "observed",
                            "citation_indexes": [1],
                        }
                    ],
                    "conflicts": [],
                    "gaps": ["Concurrent delivery is not proven."],
                },
            )
        )

    def invoke_json(self, **kwargs: Any) -> InvocationResult:
        self.calls.append(kwargs)
        if kwargs["work"] == "research_synthesis":
            self.synthesis_inputs.append(
                json.loads((kwargs["workspace"] / "evidence.json").read_text())
            )
        return InvocationResult(next(self.values), "agent-test", None, _digest())


class _Direct:
    def __init__(self, tool_count: int = 2) -> None:
        self.calls: list[dict[str, str]] = []
        proposals: list[dict[str, Any]] = [_architecture(tool_count)]
        if tool_count > 1:
            proposals.append(_shared())
        for index in range(1, tool_count + 1):
            result_index = 4 * (index - 1) + 4
            proposals.append(
                {
                    "preconditions": [_rule(result_index)],
                    "transitions": [_rule(result_index)],
                    "postconditions": [],
                    "errors": [],
                }
            )
        proposals.extend(
            (
                {"initial_rules": [], "invariants": []},
                {
                    "families": [
                        {
                            "task_family_id": "primary",
                            "objective": "complete a handoff",
                            "actor_index": 1,
                            "tool_indexes": list(range(tool_count, 0, -1)),
                            "dimensions": [
                                {
                                    "name": "urgency",
                                    "meaning": "business priority",
                                    "levels": [
                                        {"name": "normal", "meaning": "normal"},
                                        {"name": "urgent", "meaning": "urgent"},
                                    ],
                                }
                            ],
                            "sampling_intent": "sample public handoffs",
                            "citation_indexes": [1],
                        },
                        {
                            "task_family_id": "secondary",
                            "objective": "verify a handoff",
                            "actor_index": 1,
                            "tool_indexes": [tool_count],
                            "dimensions": [
                                {
                                    "name": "urgency_secondary",
                                    "meaning": "business priority",
                                    "levels": [
                                        {"name": "normal", "meaning": "normal"},
                                        {"name": "urgent", "meaning": "urgent"},
                                    ],
                                }
                            ],
                            "sampling_intent": "sample public checks",
                            "citation_indexes": [1],
                        },
                    ]
                },
            )
        )
        for _ in range(2):
            proposals.append(
                {
                    "public_goal_fields": [1],
                    "initial_rules": [],
                    "success_rules": [_task_rule(1)],
                    "failure_rules": [],
                    "terminal_rules": [_task_rule(1)],
                }
            )
        self.proposals = iter(proposals)

    def invoke_json(self, **kwargs: str) -> InvocationResult:
        self.calls.append(kwargs)
        return InvocationResult(next(self.proposals), "direct-test")


def _executor(
    monkeypatch: pytest.MonkeyPatch, tool_count: int = 2
) -> tuple[DesignExecutor, _Agent, _Direct]:
    agent, direct = _Agent(), _Direct(tool_count)
    executor = DesignExecutor(
        cast(FoundrySettings, SimpleNamespace(research=SimpleNamespace())),
        cast(DirectChatBackend, direct),
        cast(CodexAgentBackend, agent),
    )

    def acquire(
        self: DesignExecutor,
        plan: ResearchPlan,
        store: ArtifactStore,
        graph: object,
        run_id: str,
        plan_ref: ArtifactRef,
    ) -> tuple[tuple[dict[str, Any], ...], ArtifactRef, ArtifactRef]:
        agent.acquired_plans.append(plan)
        node = design_graph().execute(
            store,
            run_id,
            "research_acquire",
            {"research_plan": (plan_ref,)},
            "design.research_acquire",
            lambda _: ({"sources": 1},),
            lambda proposal: proposal,
            {"frozen": True},
        )
        return (
            (
                {
                    "url": "https://example.test/evidence",
                    "content_digest": _digest(),
                    "content_length": 24,
                    "text": "A safe staged evidence excerpt.",
                },
            ),
            node.artifact,
            node.work,
        )

    monkeypatch.setattr(executor, "_research_acquire", MethodType(acquire, executor))
    return executor, agent, direct


def _architecture_context(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    DesignExecutor,
    _Direct,
    ArtifactStore,
    EnvironmentRequest,
    EvidenceGraph,
    ArtifactRef,
    ArtifactRef,
]:
    executor, _, direct = _executor(monkeypatch)
    store = ArtifactStore(tmp_path)
    request = EnvironmentRequest.create("Build a support handoff environment.")
    request_ref = store.put_json("control.design_request", {"need_digest": request.need_digest})
    evidence_ref = store.put_envelope(
        ArtifactEnvelope(
            "design.evidence_graph",
            1,
            WorkCoordinate("architecture-contract", "design", "research_synthesis", None, 1),
            _digest(),
            (),
            ("evidence", "coverage"),
            {"safe": True},
        )
    )
    evidence = EvidenceGraph(
        (EvidenceClaim("The API records handoffs.", "observed", (1,)),),
        (),
        (),
        CitationCatalog(
            (CitationCatalogItem(1, "support api", "https://example.test/evidence", "excerpt"),)
        ),
        evidence_ref,
    )
    return executor, direct, store, request, evidence, request_ref, evidence_ref


_SEMANTIC_FEEDBACK_PREFIX = (
    "Continue the same task with the original frozen input and complete output contract. "
    "The immediately preceding complete proposal was rejected for one safe framework-observed "
    "issue: code "
)
_SEMANTIC_FEEDBACK_SUFFIX = (
    ". The path identifies exactly one framework-observed occurrence. Change the response at that "
    "path to correct that occurrence, then inspect the complete immediately preceding proposal and "
    "correct every occurrence governed by the same condition and expected category. "
    "Do not treat this as evidence that the framework "
    "observed any other occurrence. "
    "Return one complete replacement as exactly one JSON object, not a patch, explanation, or "
    "Markdown. Before answering, self-check the whole replacement object against the complete "
    "output contract."
)


def _semantic_feedback(packet: dict[str, Any]) -> str:
    return (
        _SEMANTIC_FEEDBACK_PREFIX
        + str(packet["code"])
        + "; path "
        + str(packet["path"])
        + "; condition "
        + str(packet["violated_condition"])
        + "; expected category "
        + str(packet["expected_category"])
        + _SEMANTIC_FEEDBACK_SUFFIX
    )


def _feedback_packet(call: dict[str, Any]) -> dict[str, Any]:
    feedback = call["feedback"]
    assert isinstance(feedback, str)
    assert feedback.startswith(_SEMANTIC_FEEDBACK_PREFIX)
    assert feedback.endswith(_SEMANTIC_FEEDBACK_SUFFIX)
    body = feedback[len(_SEMANTIC_FEEDBACK_PREFIX) : -len(_SEMANTIC_FEEDBACK_SUFFIX)]
    code, remainder = body.split("; path ", maxsplit=1)
    path, remainder = remainder.split("; condition ", maxsplit=1)
    condition, expected_category = remainder.rsplit("; expected category ", maxsplit=1)
    return {
        "code": code,
        "path": path,
        "violated_condition": condition,
        "expected_category": expected_category,
    }


def test_direct_feedback_keeps_format_root_wide_and_semantic_whole_condition() -> None:
    semantic = _direct_feedback(
        CorrectionPacket(
            "tool_semantics_invalid",
            "$.transitions[3].effects[2].value",
            "effect value must satisfy the closed semantic draft",
            "semantic_draft",
        )
    )
    format_feedback = _direct_feedback(
        CorrectionPacket(
            "direct_response_not_json",
            "$",
            "response is wrapped in a Markdown code fence",
            "object",
        )
    )

    assert "path $.transitions[3].effects[2].value" in semantic
    assert "exactly one framework-observed occurrence" in semantic
    assert "Change the response at that path to correct that occurrence" in semantic
    assert "inspect the complete immediately preceding proposal" in semantic
    assert (
        "correct every occurrence governed by the same condition and expected category" in semantic
    )
    assert (
        "Do not treat this as evidence that the framework observed any other occurrence" in semantic
    )
    assert "one complete replacement as exactly one JSON object" in semantic
    assert (
        "self-check the whole replacement object against the complete output contract" in semantic
    )
    for control_field in (
        "owner_node",
        "target_node",
        "budget",
        "route",
        "gate_results",
        "release_ref",
        "invalidates",
    ):
        assert control_field not in semantic

    assert "code direct_response_not_json" in format_feedback
    assert "path $" in format_feedback
    assert "response is wrapped in a Markdown code fence" in format_feedback
    assert (
        "Replace the entire immediately preceding answer with one parseable JSON object"
        in format_feedback
    )
    assert "Delete all prose, labels, Markdown fences, and second JSON values" in format_feedback
    assert "Its first and last non-whitespace characters must be { and }" in format_feedback
    assert "exactly one framework-observed occurrence" not in format_feedback
    assert "every occurrence governed by the same condition" not in format_feedback


def _architecture_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    proposal: dict[str, Any],
) -> tuple[DesignError, _Direct, ArtifactStore]:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((proposal, proposal))
    with pytest.raises(DesignError) as raised:
        executor._direct_architecture(
            request,
            evidence,
            store,
            design_graph(),
            "architecture-contract",
            request_ref,
            evidence_ref,
        )
    return raised.value, direct, store


def test_shared_tool_recipient_discloses_exact_grammar_and_preserves_consumers(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "shared-tool-recipient",
    )

    shape = "output={atomicity|concurrency|idempotency:1..group_size arrays of nonempty frozen-index arrays partitioning input.tool_indexes exactly once;unless evidence requires a finer split,use one domain containing the complete ordered input.tool_indexes (example input [1,2,3] -> [[1,2,3]]);ordering:0..8 stripped nonempty text items<=500 code points;compensation:0..8 stripped nonempty text items<=160 code points;error_policy:one stripped nonempty shared-policy string<=500 code points applying to the complete group}. Objective:return compact complete semantics for the frozen group,cover every member exactly once in each shared dimension,and recheck the whole object after correction. Do not return IDs,indexes outside the disclosed group,digests,Artifact refs,schemas,gates,Judge,or release facts."  # noqa: E501
    payloads = [json.loads(call["user"]) for call in direct.calls]
    shared_payload = next(
        payload for payload in payloads if payload["node"] == "shared_tool_semantics"
    )
    contract = result.design.shared_tool_contracts[0]
    assert shared_payload["input"]["tool_indexes"] == [1, 2]
    assert shared_payload["output_shape"] == shape
    assert contract.digest == digest_value(_compiled_shared())
    assert contract.atomicity == contract.concurrency == contract.idempotency == ((1, 2),)
    assert set(_shared()) == {
        "atomicity",
        "concurrency",
        "idempotency",
        "ordering",
        "compensation",
        "error_policy",
    }
    assert contract.error_policy == ((1, "reject invalid requests"), (2, "reject invalid requests"))

    shared_projection = json_value(contract)
    shared_projection.pop("artifact")
    tool_payloads = [payload for payload in payloads if payload["node"] == "tool_semantics"]
    assert [payload["input"]["shared_contract"] for payload in tool_payloads] == [
        shared_projection,
        shared_projection,
    ]
    assert tuple(tool.shared_contract_digest for tool in result.design.tools) == (
        contract.digest,
        contract.digest,
    )

    shared_node = graph.node("shared_tool_semantics")
    shared_work = next(
        store.read_json(work)
        for work in result.work_refs
        if store.read_json(work)["coordinate"]["node_id"] == "shared_tool_semantics"
    )
    semantic_material = {
        "effective_projection": shared_payload["input"],
        "output_shape": shape,
        "prompt_identity": shared_node.prompt_id,
    }
    assert shared_work["semantic_revision_digest"] == graph.semantic_revision(
        shared_node, semantic_material
    )
    assert graph.semantic_revision(shared_node, semantic_material) != graph.semantic_revision(
        shared_node,
        {
            **semantic_material,
            "output_shape": "{tool_indexes,atomicity,concurrency,idempotency,ordering,"
            "compensation,error_policy}",
        },
    )
    assert (
        shared_node.owner,
        shared_node.execution_kind,
        shared_node.route,
        shared_node.skill,
        shared_node.local_corrections,
    ) == ("designer", "direct_llm", "direct", None, 1)
    assert {
        node.id: (node.owner, node.execution_kind, node.route, node.skill)
        for node in graph.nodes
        if node.execution_kind == "direct_llm"
    } == {
        "world_architecture": ("designer", "direct_llm", "direct", None),
        "shared_tool_semantics": ("designer", "direct_llm", "direct", None),
        "tool_semantics": ("designer", "direct_llm", "direct", None),
        "world_rules": ("designer", "direct_llm", "direct", None),
        "curriculum_plan": ("designer", "direct_llm", "direct", None),
        "task_requirement": ("designer", "direct_llm", "direct", None),
    }


def test_rule_draft_shape_is_byte_identical_and_source_echoes_are_framework_owned(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    design = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        ArtifactStore(tmp_path),
        design_graph(),
        "shared-rule-shape",
    ).design
    shapes = {
        node: [
            json.loads(call["user"])["output_shape"]
            for call in direct.calls
            if json.loads(call["user"])["node"] == node
        ]
        for node in ("tool_semantics", "world_rules", "task_requirement")
    }

    assert all(_RULE_DRAFT_SHAPE in shape for shape in shapes["tool_semantics"])
    assert all(_RULE_DRAFT_SHAPE in shape for shape in shapes["world_rules"])
    assert all(_TASK_RULE_DRAFT_SHAPE in shape for shape in shapes["task_requirement"])
    assert all("error_kind" in shape for shape in shapes["tool_semantics"])
    assert all("error_kind" in shape for shape in shapes["world_rules"])
    assert all("error_kind" not in shape for shape in shapes["task_requirement"])
    assert "errors-only" in shapes["tool_semantics"][0]
    assert "citation_indexes=[]" in shapes["world_rules"][0]
    assert "task_family_index" not in shapes["task_requirement"][0]
    assert "tool_index" not in shapes["tool_semantics"][0]
    assert "shared_contract" not in shapes["tool_semantics"][0]
    assert tuple(tool.tool_index for tool in design.tools) == (1, 2)
    assert (
        tuple(tool.shared_contract_digest for tool in design.tools)
        == (design.shared_tool_contracts[0].digest,) * 2
    )
    assert tuple(task.task_family_index for task in design.task_requirements) == (1, 2)

    generic_rule = _task_rule(1)
    for code, path in (
        ("tool_semantics_invalid", "$.preconditions[0]"),
        ("world_rules_invalid", "$.initial_rules[0]"),
    ):
        with pytest.raises(DesignError) as raised:
            _compile_rules(
                [generic_rule],
                design.architecture.catalog.bindings,
                {1},
                code,
                path=path.removesuffix("[0]"),
                minimum=0,
                maximum=8,
                errors_only=False,
            )
        assert raised.value.correction is not None
        assert raised.value.correction.path == path
        assert raised.value.correction.violated_condition == (
            "object must contain exactly these fields and no others: "
            "citation_indexes, effects, error_kind, rationale, when"
        )

    error_rule = _rule(1)
    error_rule["error_kind"] = "invalid_request"
    assert (
        _compile_rules(
            [error_rule],
            design.architecture.catalog.bindings,
            {1},
            "tool_semantics_invalid",
            path="$.errors",
            minimum=0,
            maximum=8,
            errors_only=True,
        )[0].error_kind
        == "invalid_request"
    )


def test_task_requirement_rules_omit_error_kind_and_compile_framework_none_in_all_sections(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "task-rule-none-compiled",
    )
    tool_refs = tuple(
        ArtifactRef(**store.read_json(work)["output_refs"][0])
        for work in result.work_refs
        if store.read_json(work)["coordinate"]["node_id"] == "tool_semantics"
    )
    source = _task_requirement_source()
    direct.proposals = iter((source, source))

    requirements, _, _ = executor._direct_tasks(
        result.design.architecture,
        result.design.tools,
        result.design.world_rules,
        result.design.curriculum,
        result.design.evidence,
        store,
        graph,
        "task-rule-none",
        result.design.architecture.artifact,
        tool_refs,
        result.design.curriculum.artifact,
        result.design.world_rules.artifact,
        result.design.evidence.artifact,
    )

    for requirement in requirements:
        for rules in (
            requirement.initial_rules,
            requirement.success_rules,
            requirement.failure_rules,
            requirement.terminal_rules,
        ):
            assert len(rules) == 1
            assert rules[0].error_kind is None


@pytest.mark.parametrize(
    ("section", "error_kind"),
    tuple(
        (section, error_kind)
        for section in ("initial_rules", "success_rules", "failure_rules", "terminal_rules")
        for error_kind in (None, "model_owned_error")
    ),
)
def test_task_requirement_rejects_any_model_supplied_error_kind(
    tmp_path, monkeypatch: pytest.MonkeyPatch, section: str, error_kind: object
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "task-rule-extra",
    )
    tool_refs = tuple(
        ArtifactRef(**store.read_json(work)["output_refs"][0])
        for work in result.work_refs
        if store.read_json(work)["coordinate"]["node_id"] == "tool_semantics"
    )
    source = _task_requirement_source()
    source[section][0]["error_kind"] = error_kind
    direct.proposals = iter((source, source))

    with pytest.raises(DesignError) as raised:
        executor._direct_tasks(
            result.design.architecture,
            result.design.tools,
            result.design.world_rules,
            result.design.curriculum,
            result.design.evidence,
            store,
            graph,
            "task-rule-extra-compiled",
            result.design.architecture.artifact,
            tool_refs,
            result.design.curriculum.artifact,
            result.design.world_rules.artifact,
            result.design.evidence.artifact,
        )

    assert raised.value.correction is not None
    assert raised.value.correction.path == f"$.{section}[0]"
    assert raised.value.correction.violated_condition == (
        "object must contain exactly these fields and no others: "
        "citation_indexes, effects, rationale, when"
    )


def test_task_requirement_projection_is_one_copy_semantic_and_revision_bound(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "task-projection",
    )
    design = result.design
    task_payload = next(
        json.loads(call["user"])
        for call in direct.calls
        if json.loads(call["user"])["node"] == "task_requirement"
    )
    projection = task_payload["input"]
    family = design.curriculum.families[0]
    expected_family = {
        "objective": family.objective,
        "actor_index": family.actor_index,
        "tool_indexes": list(family.tool_indexes),
        "difficulty_schema": {
            "dimensions": json_value(family.difficulty_schema.dimensions),
        },
        "sampling_intent": family.sampling_intent,
        "citation_indexes": list(family.citation_indexes),
    }
    assert projection["family"] == expected_family
    assert projection["semantic_catalog"] == {
        "bindings": json_value(design.architecture.catalog.bindings),
    }
    assert projection["tools"] == [
        {
            "surface": json_value(design.tools[index - 1].surface),
            "preconditions": json_value(design.tools[index - 1].preconditions),
            "transitions": json_value(design.tools[index - 1].transitions),
            "postconditions": json_value(design.tools[index - 1].postconditions),
            "errors": json_value(design.tools[index - 1].errors),
        }
        for index in family.tool_indexes
    ]
    assert projection["world_rules"] == {
        "initial_rules": json_value(design.world_rules.initial_rules),
        "invariants": json_value(design.world_rules.invariants),
    }
    assert projection["citation_catalog"] == json_value(design.evidence.catalog)
    assert projection["reachability_policy"] == {
        "action_tool_indexes": list(family.tool_indexes),
    }

    def keys(value: object) -> list[str]:
        if isinstance(value, dict):
            return list(value) + [key for item in value.values() for key in keys(item)]
        if isinstance(value, list):
            return [key for item in value for key in keys(item)]
        return []

    projection_keys = keys(projection)
    assert projection_keys.count("bindings") == 1
    assert projection_keys.count("difficulty_schema") == 1
    assert not {
        key
        for key in projection_keys
        if key in {"artifact", "work_refs"} or key == "digest" or key.endswith("_digest")
    }
    assert "error_kind" not in task_payload["output_shape"]
    assert _TASK_RULE_DRAFT_SHAPE in task_payload["output_shape"]

    task_work = next(
        store.read_json(work)
        for work in result.work_refs
        if store.read_json(work)["coordinate"]["node_id"] == "task_requirement"
    )
    node = graph.node("task_requirement")
    semantic_material = {
        "effective_projection": projection,
        "output_shape": task_payload["output_shape"],
        "prompt_identity": node.prompt_id,
    }
    assert task_work["semantic_revision_digest"] == graph.semantic_revision(node, semantic_material)
    changed_projection = json.loads(json.dumps(projection))
    changed_projection["family"]["objective"] = "changed task objective"
    assert task_work["semantic_revision_digest"] != graph.semantic_revision(
        node,
        {**semantic_material, "effective_projection": changed_projection},
    )


def test_tool_semantics_rule_root_correction_commits_bounded_error_kind(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    architecture_source = _architecture()
    architecture_source["tools"][0]["name"] = "register_member"
    direct.proposals = iter((architecture_source,))
    graph = design_graph()
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, graph, "tool-rule-correction", request_ref, evidence_ref
    )
    direct.proposals = iter((_shared(),))
    shared, shared_refs, _ = executor._shared_tool_shards(
        architecture,
        evidence,
        store,
        graph,
        "tool-rule-correction",
        architecture_ref,
        evidence_ref,
    )

    malformed = {
        "preconditions": [{"when": []}],
        "transitions": [_rule(4)],
        "postconditions": [],
        "errors": [],
    }
    bounded_error_kind = "a" + "b" * 63
    repaired = {
        "preconditions": [_rule(4)],
        "transitions": [_rule(4)],
        "postconditions": [],
        "errors": [
            {
                **_rule(4),
                "effects": [{"target_semantic_index": 4, "operation": "reject", "value": None}],
                "error_kind": bounded_error_kind,
            }
        ],
    }
    second_tool = {
        "preconditions": [_rule(8)],
        "transitions": [_rule(8)],
        "postconditions": [],
        "errors": [],
    }
    direct.calls.clear()
    direct.proposals = iter((malformed, repaired, second_tool))

    tools, _, works = executor._direct_tools(
        architecture,
        shared,
        evidence,
        store,
        graph,
        "tool-rule-correction",
        architecture_ref,
        shared_refs,
        evidence_ref,
    )

    payloads = [json.loads(call["user"]) for call in direct.calls]
    assert len(payloads) == 3
    assert [payload["input"]["tool"]["name"] for payload in payloads] == [
        "register_member",
        "register_member",
        "tool_2",
    ]
    assert [payload["correction"] for payload in payloads[:2]] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "tool_semantics_invalid",
        "path": "$.preconditions[0]",
        "violated_condition": (
            "object must contain exactly these fields and no others: "
            "citation_indexes, effects, error_kind, rationale, when"
        ),
        "expected_category": "object",
    }
    assert tools[0].errors[0].error_kind == bounded_error_kind
    assert store.read_json(works[0])["status"] == "passed"


def test_tool_semantics_strict_progress_uses_ephemeral_four_message_feedback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    graph = design_graph()
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, graph, "tool-feedback-progress", request_ref, evidence_ref
    )
    direct.proposals = iter((_shared(),))
    shared, shared_refs, _ = executor._shared_tool_shards(
        architecture,
        evidence,
        store,
        graph,
        "tool-feedback-progress",
        architecture_ref,
        evidence_ref,
    )
    first_invalid = {
        "preconditions": [{"when": [], "rationale": "REJECTED_TOOL_A"}],
        "transitions": [_rule(4)],
        "postconditions": [],
        "errors": [],
    }
    second_invalid = {
        "preconditions": [_rule(4)],
        "transitions": [_rule(4)],
        "postconditions": [],
        "errors": [{**_rule(4), "rationale": "REJECTED_TOOL_B"}],
    }
    valid = {
        "preconditions": [_rule(4)],
        "transitions": [_rule(4)],
        "postconditions": [],
        "errors": [],
    }
    second_tool = {
        "preconditions": [_rule(8)],
        "transitions": [_rule(8)],
        "postconditions": [],
        "errors": [],
    }
    first_packet = {
        "code": "tool_semantics_invalid",
        "path": "$.preconditions[0]",
        "violated_condition": (
            "object must contain exactly these fields and no others: "
            "citation_indexes, effects, error_kind, rationale, when"
        ),
        "expected_category": "object",
    }
    second_packet = {
        "code": "tool_semantics_invalid",
        "path": "$.errors[0].error_kind",
        "violated_condition": "error rules require a bounded error kind",
        "expected_category": "string",
    }
    direct.calls.clear()
    direct.proposals = iter((first_invalid, second_invalid, valid, second_tool))

    tools, _, works = executor._direct_tools(
        architecture,
        shared,
        evidence,
        store,
        graph,
        "tool-feedback-progress",
        architecture_ref,
        shared_refs,
        evidence_ref,
    )

    assert len(tools) == 2
    assert len(direct.calls) == 4
    initial, first_feedback, second_feedback, next_tool = direct.calls
    assert (
        set(initial)
        == set(first_feedback)
        == set(second_feedback)
        == {
            "system",
            "user",
            "previous_assistant",
            "feedback",
        }
    )
    assert initial["system"] == first_feedback["system"] == second_feedback["system"]
    assert initial["user"] == first_feedback["user"] == second_feedback["user"]
    assert json.loads(initial["user"])["correction"] is None
    assert initial["previous_assistant"] is None
    assert initial["feedback"] is None
    assert first_feedback["previous_assistant"] == json.dumps(
        first_invalid, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert first_feedback["feedback"] == _semantic_feedback(first_packet)
    assert second_feedback["previous_assistant"] == json.dumps(
        second_invalid, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert second_feedback["feedback"] == _semantic_feedback(second_packet)
    assert "REJECTED_TOOL_A" not in first_feedback["feedback"]
    assert "REJECTED_TOOL_B" not in second_feedback["feedback"]
    assert json.loads(next_tool["user"])["input"]["tool"]["name"] == "tool_2"
    work = store.read_json(works[0])
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    attempts = [store.read_json(ref) for ref in assurance if ref.kind == "control.attempt"]
    operations = [store.read_json(ref) for ref in assurance if ref.kind == "assurance.operation"]
    assert [attempt["status"] for attempt in attempts] == [
        "correction_requested",
        "correction_requested",
        "passed",
    ]
    assert len(operations) == len(attempts) == 3
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert b"REJECTED_TOOL_A" not in persisted
    assert b"REJECTED_TOOL_B" not in persisted
    assert _SEMANTIC_FEEDBACK_PREFIX.encode() not in persisted


@pytest.mark.parametrize("third_valid", (True, False))
def test_tool_semantics_repeated_format_uses_immediately_previous_answer_and_stops(
    tmp_path, monkeypatch: pytest.MonkeyPatch, third_valid: bool
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    graph = design_graph()
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, graph, "tool-format-budget", request_ref, evidence_ref
    )
    direct.proposals = iter((_shared(),))
    shared, shared_refs, _ = executor._shared_tool_shards(
        architecture,
        evidence,
        store,
        graph,
        "tool-format-budget",
        architecture_ref,
        evidence_ref,
    )
    valid = {
        "preconditions": [_rule(4)],
        "transitions": [_rule(4)],
        "postconditions": [],
        "errors": [],
    }
    second_tool = {
        "preconditions": [_rule(8)],
        "transitions": [_rule(8)],
        "postconditions": [],
        "errors": [],
    }
    raw_answers = ("private format one", "private format two", "private format three")
    responses: list[InvocationResult | _DirectFormatFailure] = [
        _DirectFormatFailure(raw_answers[0], "direct-format", {"total_tokens": 3}),
        _DirectFormatFailure(raw_answers[1], "direct-format", {"total_tokens": 4}),
    ]
    if third_valid:
        responses.extend(
            (
                InvocationResult(valid, "direct-format", {"total_tokens": 5}),
                InvocationResult(second_tool, "direct-format", {"total_tokens": 6}),
            )
        )
    else:
        responses.append(_DirectFormatFailure(raw_answers[2], "direct-format", {"total_tokens": 5}))
    pending = iter(responses)
    direct.calls.clear()

    def invoke(**kwargs: Any) -> InvocationResult | _DirectFormatFailure:
        direct.calls.append(kwargs)
        return next(pending)

    monkeypatch.setattr(direct, "invoke_json", invoke)
    if third_valid:
        _, _, works = executor._direct_tools(
            architecture,
            shared,
            evidence,
            store,
            graph,
            "tool-format-budget",
            architecture_ref,
            shared_refs,
            evidence_ref,
        )
        work = store.read_json(works[0])
        assert len(direct.calls) == 4
    else:
        with pytest.raises(DesignError) as raised:
            executor._direct_tools(
                architecture,
                shared,
                evidence,
                store,
                graph,
                "tool-format-budget",
                architecture_ref,
                shared_refs,
                evidence_ref,
            )
        work = store.read_json(raised.value.artifact_refs[-1])
        assert raised.value.code == "direct_response_not_json"
        assert len(direct.calls) == 3

    initial, first_feedback, second_feedback = direct.calls[:3]
    assert initial["system"] == first_feedback["system"] == second_feedback["system"]
    assert initial["user"] == first_feedback["user"] == second_feedback["user"]
    assert initial["previous_assistant"] is None and initial["feedback"] is None
    assert first_feedback["previous_assistant"] == raw_answers[0]
    assert second_feedback["previous_assistant"] == raw_answers[1]
    for call, rejected in (
        (first_feedback, raw_answers[0]),
        (second_feedback, raw_answers[1]),
    ):
        assert "Replace the entire immediately preceding answer" in call["feedback"]
        assert (
            "Delete all prose, labels, Markdown fences, and second JSON values" in call["feedback"]
        )
        assert rejected not in call["feedback"]
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    attempts = [store.read_json(ref) for ref in assurance if ref.kind == "control.attempt"]
    assert [attempt["status"] for attempt in attempts] == [
        "correction_requested",
        "correction_requested",
        "passed" if third_valid else "failed",
    ]
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    for raw in raw_answers:
        assert raw.encode() not in persisted


@pytest.mark.parametrize(
    "partition",
    (
        [[1, []]],
        [[1, "two"]],
        [[1, 1], [2]],
        [[1], [1, 2]],
        [[1, 3]],
    ),
)
def test_shared_tool_source_partitions_are_typed_before_set_operations(
    tmp_path, monkeypatch: pytest.MonkeyPatch, partition: list[list[Any]]
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "shared-partition", request_ref, evidence_ref
    )
    proposal = _shared()
    proposal["atomicity"] = partition
    direct.proposals = iter((proposal, proposal))

    with pytest.raises(DesignError) as raised:
        executor._shared_tool_shards(
            architecture,
            evidence,
            store,
            design_graph(),
            "shared-partition",
            architecture_ref,
            evidence_ref,
        )

    assert raised.value.correction is not None
    assert raised.value.correction.path == "$.atomicity"
    assert len(direct.calls) == 3


@pytest.mark.parametrize("policy", (["repeated"], "", "x" * 501))
def test_shared_tool_source_policy_is_one_bounded_string(
    tmp_path, monkeypatch: pytest.MonkeyPatch, policy: object
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "shared-policy", request_ref, evidence_ref
    )
    proposal = _shared()
    proposal["error_policy"] = policy
    direct.proposals = iter((proposal, proposal))

    with pytest.raises(DesignError) as raised:
        executor._shared_tool_shards(
            architecture,
            evidence,
            store,
            design_graph(),
            "shared-policy",
            architecture_ref,
            evidence_ref,
        )

    assert raised.value.correction is not None
    assert raised.value.correction.path == "$.error_policy"
    assert raised.value.correction.expected_category == "string"
    assert len(direct.calls) == 3


def test_shared_tool_policy_bound_gets_exact_correction_and_commits(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "shared-policy-bound", request_ref, evidence_ref
    )
    invalid, corrected = _shared(), _shared()
    invalid["error_policy"] = "x" * 501
    corrected["error_policy"] = "x" * 500
    direct.calls.clear()
    direct.proposals = iter((invalid, corrected))

    contracts, _, works = executor._shared_tool_shards(
        architecture,
        evidence,
        store,
        design_graph(),
        "shared-policy-bound",
        architecture_ref,
        evidence_ref,
    )

    payloads = [json.loads(call["user"]) for call in direct.calls]
    assert len(payloads) == 2
    assert [payload["correction"] for payload in payloads] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "shared_tool_semantics_invalid",
        "path": "$.error_policy",
        "violated_condition": "value must use at most 500 code points",
        "expected_category": "string",
    }
    assert contracts[0].error_policy == ((1, "x" * 500), (2, "x" * 500))
    assert store.read_json(works[0])["status"] == "passed"


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"tool_indexes": ([1], 2)}, "shared_tool_members_invalid"),
        ({"atomicity": ((1, "two"),)}, "shared_tool_partition_invalid"),
        ({"concurrency": ((1, 1), (2,))}, "shared_tool_partition_invalid"),
        ({"idempotency": ((1,), (1, 2))}, "shared_tool_partition_invalid"),
        ({"atomicity": ((1, 3),)}, "shared_tool_partition_invalid"),
        (
            {"error_policy": ((2, "reject invalid requests"), (1, "reject invalid requests"))},
            "shared_tool_error_policy_invalid",
        ),
    ),
)
def test_shared_tool_contract_cold_read_rejects_nonexact_partitions(
    tmp_path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any], code: str
) -> None:
    executor, _, _ = _executor(monkeypatch)
    contract = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        ArtifactStore(tmp_path),
        design_graph(),
        "shared-cold",
    ).design.shared_tool_contracts[0]

    with pytest.raises(ValueError, match=code):
        replace(contract, **changes)


def test_rule_and_curriculum_validation_feedback_uses_exact_typed_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "index-types",
    )
    rule = _rule(1, citation=False)
    rule["citation_indexes"] = [{}]
    with pytest.raises(DesignError) as rule_error:
        _compile_rules(
            [rule],
            result.design.architecture.catalog.bindings,
            {1},
            "world_rules_invalid",
            path="$.initial_rules",
            minimum=0,
            maximum=8,
        )
    assert rule_error.value.correction is not None
    assert rule_error.value.correction.path == "$.initial_rules[0].citation_indexes"

    source = _curriculum_source(result.design.curriculum)
    missing_family_field = {"families": json.loads(json.dumps(source["families"]))}
    missing_family_field["families"][0].pop("sampling_intent")
    direct.proposals = iter((missing_family_field, missing_family_field))
    with pytest.raises(DesignError) as family_error:
        executor._direct_curriculum(
            result.design.architecture,
            result.design.world_rules,
            result.design.evidence,
            store,
            graph,
            "index-types-family-fields",
            result.design.architecture.artifact,
            result.design.world_rules.artifact,
            result.design.evidence.artifact,
        )
    assert family_error.value.correction is not None
    assert family_error.value.correction.path == "$.families[0]"
    assert family_error.value.correction.violated_condition == (
        "object must contain exactly these fields and no others: actor_index, citation_indexes, "
        "dimensions, objective, sampling_intent, task_family_id, tool_indexes"
    )
    assert family_error.value.correction.expected_category == "object"

    for field, invalid, path, condition, category in (
        (
            "task_family_id",
            "primary-id",
            "$.families[0].task_family_id",
            "task family id must use the declared grammar",
            "string",
        ),
        (
            "actor_index",
            2,
            "$.families[0].actor_index",
            "actor index must be one frozen actor index",
            "number",
        ),
        (
            "tool_indexes",
            [[]],
            "$.families[0].tool_indexes",
            "family tools must be unique frozen indexes",
            "array",
        ),
        (
            "citation_indexes",
            [{}],
            "$.families[0].citation_indexes",
            "family citations must be unique frozen indexes",
            "array",
        ),
    ):
        proposal = {"families": json.loads(json.dumps(source["families"]))}
        proposal["families"][0][field] = invalid
        direct.proposals = iter((proposal, proposal))
        with pytest.raises(DesignError) as curriculum_error:
            executor._direct_curriculum(
                result.design.architecture,
                result.design.world_rules,
                result.design.evidence,
                store,
                graph,
                f"index-types-{field}",
                result.design.architecture.artifact,
                result.design.world_rules.artifact,
                result.design.evidence.artifact,
            )
        assert curriculum_error.value.correction is not None
        assert curriculum_error.value.correction.path == path
        assert curriculum_error.value.correction.violated_condition == condition
        assert curriculum_error.value.correction.expected_category == category

    task = {
        "public_goal_fields": [{}],
        "initial_rules": [],
        "success_rules": [_task_rule(1)],
        "failure_rules": [],
        "terminal_rules": [_task_rule(1)],
    }
    tool_refs = tuple(
        ArtifactRef(**store.read_json(work)["output_refs"][0])
        for work in result.work_refs
        if store.read_json(work)["coordinate"]["node_id"] == "tool_semantics"
    )
    direct.proposals = iter((task, task))
    with pytest.raises(DesignError) as task_error:
        executor._direct_tasks(
            result.design.architecture,
            result.design.tools,
            result.design.world_rules,
            result.design.curriculum,
            result.design.evidence,
            store,
            graph,
            "index-types-task",
            result.design.architecture.artifact,
            tool_refs,
            result.design.curriculum.artifact,
            result.design.world_rules.artifact,
            result.design.evidence.artifact,
        )
    assert task_error.value.correction is not None
    assert task_error.value.correction.path == "$.public_goal_fields"


def test_curriculum_preserves_current_hyphenated_dimension_and_level_names(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "hyphen-base",
    )
    proposal = _curriculum_source(result.design.curriculum)
    for family in proposal["families"]:
        family["dimensions"][0]["name"] = "time-window"
        family["dimensions"][0]["levels"][0]["name"] = "same-day"
    direct.proposals = iter((proposal,))

    curriculum, _, _ = executor._direct_curriculum(
        result.design.architecture,
        result.design.world_rules,
        result.design.evidence,
        store,
        graph,
        "hyphenated-curriculum",
        result.design.architecture.artifact,
        result.design.world_rules.artifact,
        result.design.evidence.artifact,
    )

    assert [family.difficulty_schema.key_order for family in curriculum.families] == [
        ("time-window",),
        ("time-window",),
    ]
    assert all(
        family.difficulty_schema.dimensions[0].levels[0].name == "same-day"
        for family in curriculum.families
    )


def test_shared_tool_non_json_is_terminal_without_correction_or_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "shared-tool-not-json", request_ref, evidence_ref
    )
    direct.calls.clear()

    def non_json(**kwargs: str) -> InvocationResult:
        direct.calls.append(kwargs)
        raise InvocationError(SafeFailure("direct_response_not_json", "rejected"))

    monkeypatch.setattr(direct, "invoke_json", non_json)
    with pytest.raises(DesignError) as raised:
        executor._shared_tool_shards(
            architecture,
            evidence,
            store,
            design_graph(),
            "shared-tool-not-json",
            architecture_ref,
            evidence_ref,
        )

    assert raised.value.code == "direct_response_not_json"
    assert raised.value.correction is None
    assert len(direct.calls) == 1
    assert json.loads(direct.calls[0]["user"])["correction"] is None
    work = store.read_json(raised.value.artifact_refs[-1])
    finding = store.read_json(ArtifactRef(**work["finding_refs"][0]))
    assert work["status"] == "failed"
    assert work["safe_code"] == "direct_response_not_json"
    assert work["output_refs"] == []
    assert finding["blocks_release"] is True
    assert all(ref.kind != "design.shared_tool_semantics" for ref in raised.value.artifact_refs)


def test_shared_tool_format_feedback_reuses_only_ephemeral_rejected_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request,
        evidence,
        store,
        design_graph(),
        "shared-tool-format-feedback",
        request_ref,
        evidence_ref,
    )
    raw = "```json\nprivate rejected format content\n```"
    direct.calls.clear()
    responses = iter(
        (
            _DirectFormatFailure(raw, "direct-format", {"input_tokens": 3, "total_tokens": 3}),
            InvocationResult(_shared(), "direct-format", {"input_tokens": 5, "total_tokens": 5}),
        )
    )

    def format_then_valid(**kwargs: Any) -> InvocationResult | _DirectFormatFailure:
        direct.calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(direct, "invoke_json", format_then_valid)
    contracts, _, works = executor._shared_tool_shards(
        architecture,
        evidence,
        store,
        design_graph(),
        "shared-tool-format-feedback",
        architecture_ref,
        evidence_ref,
    )

    assert len(contracts) == 1
    assert len(direct.calls) == 2
    first, second = direct.calls
    assert second["system"] == first["system"]
    assert second["user"] == first["user"]
    assert first["previous_assistant"] is None
    assert first["feedback"] is None
    assert second["previous_assistant"] == raw
    feedback = second["feedback"]
    assert isinstance(feedback, str)
    assert "code direct_response_not_json" in feedback
    assert "path $" in feedback
    assert "response is wrapped in a Markdown code fence" in feedback
    assert "expected category object" in feedback
    assert (
        "Replace the entire immediately preceding answer with one parseable JSON object" in feedback
    )
    assert "Delete all prose, labels, Markdown fences, and second JSON values" in feedback
    assert "Its first and last non-whitespace characters must be { and }" in feedback
    assert "one complete replacement as exactly one JSON object" in feedback
    assert "not a patch, explanation, or Markdown" in feedback
    assert "self-check the whole replacement object" in feedback
    assert raw not in feedback
    assert json.loads(first["user"])["correction"] is None
    assert json.loads(second["user"])["correction"] is None
    work = store.read_json(works[0])
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    operations = [store.read_json(ref) for ref in assurance if ref.kind == "assurance.operation"]
    attempts = [store.read_json(ref) for ref in assurance if ref.kind == "control.attempt"]
    assert [operation["model"] for operation in operations] == ["direct-format", "direct-format"]
    assert [operation["usage"] for operation in operations] == [
        {"input_tokens": 3, "total_tokens": 3},
        {"input_tokens": 5, "total_tokens": 5},
    ]
    assert [attempt["status"] for attempt in attempts] == ["correction_requested", "passed"]
    assert attempts[0]["correction"] == {
        "code": "direct_response_not_json",
        "path": "$",
        "violated_condition": "response is wrapped in a Markdown code fence",
        "expected_category": "object",
    }
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert raw.encode() not in persisted


def test_shared_tool_second_format_failure_is_terminal_without_a_third_call(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request,
        evidence,
        store,
        design_graph(),
        "shared-tool-format-terminal",
        request_ref,
        evidence_ref,
    )
    first_raw, second_raw = "prose first", "prose second"
    direct.calls.clear()
    responses = iter(
        (
            _DirectFormatFailure(first_raw, "direct-format", {"total_tokens": 3}),
            _DirectFormatFailure(second_raw, "direct-format", {"total_tokens": 4}),
        )
    )

    def malformed_twice(**kwargs: Any) -> _DirectFormatFailure:
        direct.calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(direct, "invoke_json", malformed_twice)
    with pytest.raises(DesignError) as raised:
        executor._shared_tool_shards(
            architecture,
            evidence,
            store,
            design_graph(),
            "shared-tool-format-terminal",
            architecture_ref,
            evidence_ref,
        )

    assert raised.value.code == "direct_response_not_json"
    assert len(direct.calls) == 2
    assert direct.calls[1]["previous_assistant"] == first_raw
    work = store.read_json(raised.value.artifact_refs[-1])
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    operations = [store.read_json(ref) for ref in assurance if ref.kind == "assurance.operation"]
    assert len(operations) == 2
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert first_raw.encode() not in persisted
    assert second_raw.encode() not in persisted


def test_shared_tool_parsed_invalid_object_gets_one_correction_and_no_third_call(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request,
        evidence,
        store,
        design_graph(),
        "shared-tool-correction",
        request_ref,
        evidence_ref,
    )
    invalid = _shared()
    invalid["atomicity"] = [[1]]
    direct.calls.clear()
    direct.proposals = iter((invalid, invalid))

    with pytest.raises(DesignError) as raised:
        executor._shared_tool_shards(
            architecture,
            evidence,
            store,
            design_graph(),
            "shared-tool-correction",
            architecture_ref,
            evidence_ref,
        )

    payloads = [json.loads(call["user"]) for call in direct.calls]
    assert len(payloads) == 2
    assert [payload["correction"] for payload in payloads] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "shared_tool_semantics_invalid",
        "path": "$.atomicity",
        "violated_condition": (
            "use every input tool_indexes member exactly once; unless evidence requires a finer "
            "split, one domain containing the complete ordered group is valid"
        ),
        "expected_category": "array",
    }
    work = store.read_json(raised.value.artifact_refs[-1])
    assert raised.value.code == "shared_tool_semantics_invalid"
    assert work["status"] == "failed"
    assert work["output_refs"] == []


def test_shared_tool_ordering_bound_gets_exact_correction_and_commits(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "shared-ordering", request_ref, evidence_ref
    )
    invalid, corrected = _shared(), _shared()
    invalid["ordering"] = ["x" * 501]
    corrected["ordering"] = ["x" * 500]
    direct.calls.clear()
    direct.proposals = iter((invalid, corrected))

    contracts, _, works = executor._shared_tool_shards(
        architecture,
        evidence,
        store,
        design_graph(),
        "shared-ordering",
        architecture_ref,
        evidence_ref,
    )

    payloads = [json.loads(call["user"]) for call in direct.calls]
    assert len(payloads) == 2
    assert [payload["correction"] for payload in payloads] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "shared_tool_semantics_invalid",
        "path": "$.ordering",
        "violated_condition": "value must use at most 500 code points",
        "expected_category": "string",
    }
    assert contracts[0].ordering == ("x" * 500,)
    assert store.read_json(works[0])["status"] == "passed"


def test_shared_tool_compensation_bound_remains_160(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(),))
    architecture, architecture_ref, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "shared-compensation", request_ref, evidence_ref
    )
    invalid = _shared()
    invalid["compensation"] = ["x" * 161]
    direct.proposals = iter((invalid, invalid))

    with pytest.raises(DesignError) as raised:
        executor._shared_tool_shards(
            architecture,
            evidence,
            store,
            design_graph(),
            "shared-compensation",
            architecture_ref,
            evidence_ref,
        )

    assert raised.value.correction is not None
    assert raised.value.correction.path == "$.compensation"
    assert raised.value.correction.violated_condition == ("value must use at most 160 code points")


def test_typed_design_preserves_every_shard_and_uses_exact_visible_projections(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, agent, direct = _executor(monkeypatch)
    store = ArtifactStore(tmp_path)
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        design_graph(),
        "typed-design",
    )

    design = result.design
    assert len(agent.calls) == 2
    assert [call["skill_name"] for call in agent.calls] == [
        "research-world-evidence",
        "research-world-evidence",
    ]
    assert agent.calls[0]["instruction"] == (
        "Read request.json. Return ResearchPlanDraft exactly: "
        "{queries:[text] (1..6),questions_to_resolve:[text] (1..12)}."
    )
    assert agent.acquired_plans[0].queries == ("support handoff api",)
    assert agent.synthesis_inputs[0]["questions"] == ["Which state transitions are supported?"]
    plan_work = store.read_json(result.work_refs[0])
    plan = store.read_envelope(ArtifactRef(**plan_work["output_refs"][0]))["payload"]
    assert set(plan) == {"queries", "questions_to_resolve", "artifact"}
    assert plan["queries"] == ["support handoff api"]
    assert len(direct.calls) == 8  # architecture, shared, two tools, rules, curriculum, two tasks
    assert all("skill_name" not in call for call in direct.calls)
    assert len(design.shared_tool_contracts) == 1
    assert len(design.tools) == 2
    assert len(design.curriculum.families) == len(design.task_requirements) == 2
    assert [
        (recipe.task_family_index, recipe.tool_index) for recipe in design.assurance_recipes
    ] == [
        (1, 2),
        (1, 1),
        (2, 2),
    ]
    assert all("artifact" not in json.loads(call["user"])["input"] for call in direct.calls)
    assert all(
        "text" not in json.loads(call["user"])["input"].get("citation_catalog", {})
        for call in direct.calls
    )
    shared_input = json.loads(direct.calls[2]["user"])["input"]["shared_contract"]
    assert shared_input is not None and shared_input["tool_indexes"] == [1, 2]
    task_inputs = [
        json.loads(call["user"])["input"]
        for call in direct.calls
        if json.loads(call["user"])["node"] == "task_requirement"
    ]
    assert all(
        item["citation_catalog"] == json_value(design.evidence.catalog) for item in task_inputs
    )
    task_works = [
        store.read_json(work)
        for work in result.work_refs
        if store.read_json(work)["coordinate"]["node_id"] == "task_requirement"
    ]
    tool_ids = [
        ref["artifact_id"]
        for ref in store.read_json(result.work_refs[-1])["dependency_refs"]
        if store.read_envelope(ArtifactRef(**ref))["producer"]["node_id"] == "tool_semantics"
    ]
    assert [
        [ref["artifact_id"] for ref in work["dependency_refs"][1:-3]] for work in task_works
    ] == [[tool_ids[1], tool_ids[0]], [tool_ids[1]]]
    assert all(task.public_goal_fields for task in design.task_requirements)
    assert all(
        task.verification_requirements.required_recipe_digests for task in design.executable_tasks
    )


def test_research_questions_change_synthesis_semantic_revision(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def revision(question: str) -> str:
        executor, agent, _ = _executor(monkeypatch)
        agent.values = iter(
            (
                {"queries": ["support handoff api"], "questions_to_resolve": [question]},
                {
                    "claims": [
                        {
                            "statement": "The API records handoffs.",
                            "kind": "observed",
                            "citation_indexes": [1],
                        }
                    ],
                    "conflicts": [],
                    "gaps": ["Concurrent delivery is not proven."],
                },
            )
        )
        store = ArtifactStore(tmp_path / question)
        result = executor.run(
            EnvironmentRequest.create("Build a support handoff environment."),
            store,
            design_graph(),
            f"questions-{len(question)}",
        )
        return store.read_json(result.work_refs[2])["semantic_revision_digest"]

    assert revision("Which state transitions are supported?") != revision(
        "Which errors are externally visible?"
    )


def test_world_architecture_recipient_sees_sparse_field_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    invalid = _architecture()
    invalid["entities"][0]["fields"][0]["entity_ref"] = "external_relation"
    direct.proposals = iter((invalid, _architecture()))

    _, _, work = executor._direct_architecture(
        request,
        evidence,
        store,
        design_graph(),
        "architecture-contract",
        request_ref,
        evidence_ref,
    )

    payloads = [json.loads(call["user"]) for call in direct.calls]
    assert [payload["output_shape"] for payload in payloads] == [
        payloads[0]["output_shape"],
        payloads[0]["output_shape"],
    ]
    assert [payload["correction"] for payload in payloads] == [None, None]
    assert _feedback_packet(direct.calls[1])["path"] == "$.entities"
    shape = payloads[0]["output_shape"]
    assert (
        "Field={name:stripped_snake[1..64],category:text|integer|number|boolean|timestamp|identifier|enum|list,"
        in shape
    )
    assert (
        "required:boolean,values:enum|list=>unique_nonempty_text[1..16];otherwise=>omit," in shape
    )
    assert "values_char_limit:none" in shape
    assert "entity_ref:actual_relation=>untrimmed_snake[1..64];otherwise=>omit}" in shape
    assert "objective: return one coherent minimal JSON object" in shape
    assert "tools must be one coherent minimal JSON array[1..8]" in shape
    assert "combine related workflow actions when needed" in shape
    assert (
        "before returning and after any correction, recheck the complete object against every "
        "disclosed field, cardinality, uniqueness, reference, actor, and citation rule" in shape
    )
    assert (
        "boundary:{name|system_of_record|authority:stripped_text[1..160],"
        "purpose:stripped_text[1..4096_unicode_code_points],"
        "actors[1..8]:stripped_text[1..80]:unique_after_stripping}"
    ) in shape
    assert "entities[1..16]{name:stripped_text[1..64]:unique_in_entities," in shape
    assert "purpose:stripped_text[1..300],fields[1..24]:unique_names<Field;" in shape
    assert (
        "fields[1..24]:unique_names<"
        "Field;entity_ref=emitted_entity_name_in_this_object_when_present>" in shape
    )
    assert "tools[1..8]{name:stripped_text[1..64]:unique_in_tools," in shape
    assert "purpose:stripped_text[1..300],actor_names[1..frozen_actor_count]:" in shape
    assert (
        "argument_fields[0..24]:unique_names<"
        "Field;entity_ref=optional_actual_relation_snake_name;external_relation_label_allowed>"
        in shape
    )
    assert (
        "result_fields[1..24]:unique_names<"
        "Field;entity_ref=optional_actual_relation_snake_name;external_relation_label_allowed>"
        in shape
    )
    assert "actor_names[1..frozen_actor_count]:unique_exact_declared_names" in shape
    assert "actor_indexes" not in shape
    assert "[]" not in shape and "null" not in shape
    assert "known_divergences[0..16]{statement:stripped_text[1..500]," in shape
    assert "kind:observed|bounded_inference,citation_indexes:frozen_one_based[1..6]" in shape
    graph = design_graph()
    node = graph.node("world_architecture")
    assert (
        node.id,
        node.input_ports,
        node.output_ports,
        node.execution_kind,
        node.route,
        node.local_corrections,
    ) == (
        "world_architecture",
        ("request", "evidence", "coverage"),
        ("architecture",),
        "direct_llm",
        "direct",
        1,
    )
    semantic_material = {
        "effective_projection": json.loads(direct.calls[0]["user"])["input"],
        "output_shape": shape,
        "prompt_identity": graph.node("world_architecture").prompt_id,
    }
    assert store.read_json(work)["semantic_revision_digest"] == graph.semantic_revision(
        graph.node("world_architecture"), semantic_material
    )
    legacy_material = {
        **semantic_material,
        "output_shape": shape.replace(
            "before returning and after any correction",
            "before returning",
        ),
    }
    assert graph.semantic_revision(graph.node("world_architecture"), semantic_material) != (
        graph.semantic_revision(graph.node("world_architecture"), legacy_material)
    )


def test_world_architecture_compiles_sparse_fields_and_actor_names(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    proposal = _architecture()
    proposal["boundary"]["actors"] = ["operator", "reviewer"]
    proposal["entities"][0]["fields"] = [
        {"name": "required_id", "category": "identifier", "required": True},
        {"name": "optional_flag", "category": "boolean", "required": False},
        {"name": "state", "category": "enum", "required": True, "values": ["open", "closed"]},
        {"name": "labels", "category": "list", "required": False, "values": ["a", "b"]},
        {
            "name": "related_handoff",
            "category": "identifier",
            "required": False,
            "entity_ref": "handoff",
        },
    ]
    proposal["tools"][0]["actor_names"] = ["reviewer", "operator"]
    proposal["tools"][0]["argument_fields"][0]["entity_ref"] = "external_relation"
    proposal["tools"][0]["result_fields"][0]["entity_ref"] = "external_result_relation"
    direct.proposals = iter((proposal,))

    architecture, _, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "architecture-contract", request_ref, evidence_ref
    )

    fields = architecture.entities[0].fields
    assert [(field.name, field.required) for field in fields[:2]] == [
        ("required_id", True),
        ("optional_flag", False),
    ]
    assert fields[0].values == fields[1].values == ()
    assert fields[0].entity_ref is fields[1].entity_ref is None
    assert fields[2].values == ("open", "closed")
    assert fields[3].values == ("a", "b")
    assert fields[4].entity_ref == "handoff"
    assert architecture.tools[0].argument_fields[0].entity_ref == "external_relation"
    assert architecture.tools[0].result_fields[0].entity_ref == "external_result_relation"
    assert architecture.tools[0].actor_indexes == (2, 1)
    compiled = json_value(architecture)
    assert compiled["tools"][0]["actor_indexes"] == [2, 1]
    assert "actor_names" not in json.dumps(compiled)

    invalid = _architecture()
    invalid["entities"][0]["fields"][0]["entity_ref"] = "external_relation"
    error, invalid_direct, _ = _architecture_error(
        tmp_path / "external-entity", monkeypatch, invalid
    )
    assert error.correction is not None and error.correction.path == "$.entities"
    assert len(invalid_direct.calls) == 2


def test_world_architecture_stops_after_correcting_entity_reference_then_invalid_tools(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    invalid_entity = _architecture()
    invalid_entity["entities"][0]["fields"][0]["entity_ref"] = "external_relation"
    direct.proposals = iter((invalid_entity, _architecture(9)))

    with pytest.raises(DesignError) as raised:
        executor._direct_architecture(
            request,
            evidence,
            store,
            design_graph(),
            "architecture-whole-object",
            request_ref,
            evidence_ref,
        )

    calls = [json.loads(call["user"]) for call in direct.calls]
    assert raised.value.code == "world_architecture_invalid"
    assert len(calls) == 2
    assert [call["correction"] for call in calls] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "world_architecture_invalid",
        "path": "$.entities",
        "violated_condition": "entity names and references must be closed",
        "expected_category": "array",
    }
    assert len(_architecture(9)["tools"]) == 9


def test_world_architecture_preserves_eight_tool_acceptance_and_nine_tool_rejection(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    direct.proposals = iter((_architecture(8),))

    architecture, _, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "architecture-eight", request_ref, evidence_ref
    )

    assert len(architecture.tools) == 8
    error, rejected_direct, _ = _architecture_error(
        tmp_path / "nine-tools", monkeypatch, _architecture(9)
    )
    assert error.correction is not None and error.correction.path == "$.tools"
    assert len(rejected_direct.calls) == 2


@pytest.mark.parametrize(
    ("mutate", "path", "expected_category"),
    (
        (
            lambda proposal: proposal["entities"][0]["fields"].append(
                dict(proposal["entities"][0]["fields"][0])
            ),
            "$.entities[0].fields",
            "array",
        ),
        (
            lambda proposal: proposal["tools"][0]["argument_fields"].append(
                dict(proposal["tools"][0]["argument_fields"][0])
            ),
            "$.tools[0].argument_fields",
            "array",
        ),
        (
            lambda proposal: proposal["tools"][0]["result_fields"].append(
                dict(proposal["tools"][0]["result_fields"][0])
            ),
            "$.tools[0].result_fields",
            "array",
        ),
        (
            lambda proposal: proposal["tools"][0].update({"actor_names": ["operator", "operator"]}),
            "$.tools[0].actor_names",
            "array",
        ),
        (
            lambda proposal: proposal["entities"][0]["fields"][0].update({"category": "enum"}),
            "$.entities[0].fields[0].values",
            "array",
        ),
        (
            lambda proposal: proposal["entities"][0]["fields"][0].update({"category": "list"}),
            "$.entities[0].fields[0].values",
            "array",
        ),
        (
            lambda proposal: proposal["entities"][0]["fields"][0].update({"values": []}),
            "$.entities[0].fields[0].values",
            "array",
        ),
        (
            lambda proposal: proposal["entities"][0]["fields"][0].update({"entity_ref": None}),
            "$.entities[0].fields[0].entity_ref",
            "string",
        ),
        (
            lambda proposal: proposal["entities"][0]["fields"][0].update({"entity_ref": "unknown"}),
            "$.entities",
            "array",
        ),
        (
            lambda proposal: proposal["tools"][0].update({"actor_indexes": [1]}),
            "$.tools[0]",
            "object",
        ),
        (
            lambda proposal: proposal["tools"][0].update({"actor_names": ["unknown"]}),
            "$.tools[0].actor_names",
            "array",
        ),
    ),
)
def test_world_architecture_invalid_source_is_typed_and_persisted(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mutate, path: str, expected_category: str
) -> None:
    proposal = _architecture()
    if path == "$.tools[0].actor_names":
        proposal["boundary"]["actors"].append("reviewer")
    mutate(proposal)

    error, direct, store = _architecture_error(tmp_path, monkeypatch, proposal)

    assert error.code == "world_architecture_invalid"
    assert error.correction is not None and error.correction.path == path
    assert [json.loads(call["user"])["correction"] for call in direct.calls] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "world_architecture_invalid",
        "path": path,
        "violated_condition": error.correction.violated_condition,
        "expected_category": expected_category,
    }
    work = store.read_json(error.artifact_refs[-1])
    assert work["status"] == "failed"
    assert work["safe_code"] == "world_architecture_invalid"


def test_world_architecture_empty_finite_domain_gets_one_actionable_correction(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    invalid = _architecture()
    invalid["entities"][0]["fields"][0].update({"category": "enum", "values": []})
    direct.proposals = iter((invalid, _architecture()))

    architecture, _, _ = executor._direct_architecture(
        request,
        evidence,
        store,
        design_graph(),
        "architecture-correction",
        request_ref,
        evidence_ref,
    )

    assert architecture.entities[0].fields[0].category == "identifier"
    assert [json.loads(call["user"])["correction"] for call in direct.calls] == [None, None]
    feedback = _feedback_packet(direct.calls[1])
    assert feedback["code"] == "world_architecture_invalid"
    assert feedback["path"] == "$.entities[0].fields[0].values"


@pytest.mark.parametrize(
    ("purpose", "condition"),
    (
        (None, "value must be text with nonempty content after stripping"),
        (" \t\n ", "value must be text with nonempty content after stripping"),
    ),
)
def test_world_architecture_purpose_requires_nonempty_text_after_stripping(
    tmp_path, monkeypatch: pytest.MonkeyPatch, purpose: object, condition: str
) -> None:
    proposal = _architecture()
    proposal["boundary"]["purpose"] = purpose

    error, direct, store = _architecture_error(tmp_path, monkeypatch, proposal)

    correction = {
        "code": "world_architecture_invalid",
        "path": "$.boundary.purpose",
        "violated_condition": condition,
        "expected_category": "string",
    }
    assert json_value(error.correction) == correction
    assert [json.loads(call["user"])["correction"] for call in direct.calls] == [None, None]
    assert _feedback_packet(direct.calls[1]) == correction
    work = store.read_json(error.artifact_refs[-1])
    assert work["status"] == "failed"
    assert work["safe_code"] == "world_architecture_invalid"


def test_world_architecture_purpose_retains_full_ascii_value_for_consumers(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    purpose = "x" * 161
    proposal = _architecture()
    proposal["boundary"]["purpose"] = f" {purpose} "
    next(direct.proposals)
    direct.proposals = chain((proposal,), direct.proposals)
    store = ArtifactStore(tmp_path)
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        design_graph(),
        "architecture-purpose",
    )

    architecture = result.design.architecture
    assert architecture.boundary.purpose == purpose
    assert store.read_envelope(architecture.artifact)["payload"]["boundary"]["purpose"] == purpose
    direct_inputs = {
        payload["node"]: payload["input"]
        for call in direct.calls
        if (payload := json.loads(call["user"]))["node"] in {"world_rules", "curriculum_plan"}
    }
    assert direct_inputs["world_rules"]["architecture"]["boundary"]["purpose"] == purpose
    assert direct_inputs["curriculum_plan"]["architecture"]["boundary"]["purpose"] == purpose
    builder_projection = CandidateExecutor._projection(result.design)
    assert builder_projection["architecture"]["boundary"]["purpose"] == purpose
    placeholder_ref = result.design.artifact
    manifest = CandidateManifest("runtime.py", _digest(), (), placeholder_ref)
    report = JudgeReport(
        _digest(),
        (GateResult("task_materialization", "passed", None, placeholder_ref),),
        placeholder_ref,
    )
    package_metadata = candidate_module._package_metadata(
        result.design,
        manifest,
        placeholder_ref,
        placeholder_ref,
        report,
        placeholder_ref,
        placeholder_ref,
        placeholder_ref,
        placeholder_ref,
        {},
        {},
        _digest(),
        {"baseline_coverage": []},
        {"commitments": []},
    )
    package_world = json.loads(package_metadata["world/world_spec.json"])
    assert package_world["architecture"]["boundary"]["purpose"] == purpose
    assert all(json.loads(call["user"])["correction"] is None for call in direct.calls)


def test_world_architecture_purpose_counts_python_code_points_without_slicing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purpose = "é" + "e\u0301" + "x" * 4093
    assert len(purpose) == 4096
    assert len(purpose.encode()) > 4096
    executor, direct, store, request, evidence, request_ref, evidence_ref = _architecture_context(
        tmp_path, monkeypatch
    )
    proposal = _architecture()
    proposal["boundary"]["purpose"] = f" \t{purpose}\n"
    direct.proposals = iter((proposal,))

    architecture, artifact, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "architecture-unicode", request_ref, evidence_ref
    )

    assert architecture.boundary.purpose == purpose
    assert store.read_envelope(artifact)["payload"]["boundary"]["purpose"] == purpose
    assert json.loads(direct.calls[0]["user"])["correction"] is None

    over_limit = _architecture()
    over_limit["boundary"]["purpose"] = purpose + "x"
    error, direct, store = _architecture_error(tmp_path / "over-limit", monkeypatch, over_limit)
    correction = {
        "code": "world_architecture_invalid",
        "path": "$.boundary.purpose",
        "violated_condition": "stripped value must contain at most 4096 Unicode code points",
        "expected_category": "string",
    }
    assert len(over_limit["boundary"]["purpose"].strip()) == 4097
    assert json_value(error.correction) == correction
    assert [json.loads(call["user"])["correction"] for call in direct.calls] == [None, None]
    assert _feedback_packet(direct.calls[1]) == correction
    assert store.read_json(error.artifact_refs[-1])["output_refs"] == []


def test_world_architecture_nonfinite_domain_values_are_typed_and_persisted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = _architecture()
    invalid["entities"][0]["fields"][0]["values"] = ["unexpected"]

    error, direct, store = _architecture_error(tmp_path, monkeypatch, invalid)

    assert error.code == "world_architecture_invalid"
    assert error.correction is not None
    assert error.correction.path == "$.entities[0].fields[0].values"
    assert [json.loads(call["user"])["correction"] for call in direct.calls] == [None, None]
    assert _feedback_packet(direct.calls[1]) == {
        "code": "world_architecture_invalid",
        "path": "$.entities[0].fields[0].values",
        "violated_condition": "enum/list fields require nonempty values; scalars must omit them",
        "expected_category": "array",
    }
    work = store.read_json(error.artifact_refs[-1])
    assert work["status"] == "failed"
    assert work["safe_code"] == "world_architecture_invalid"


def test_single_tool_skips_shared_call_and_unknown_output_is_corrected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch, tool_count=1)
    store = ArtifactStore(tmp_path)
    result = executor.run(
        EnvironmentRequest.create("Build a single-tool handoff environment."),
        store,
        design_graph(),
        "single-tool",
    )
    assert not result.design.shared_tool_contracts
    assert [json.loads(call["user"])["node"] for call in direct.calls].count(
        "shared_tool_semantics"
    ) == 0
    gate = store.read_json(result.work_refs[-1])
    assert not any(
        store.read_envelope(ArtifactRef(**ref))["producer"]["node_id"] == "shared_tool_semantics"
        for ref in gate["dependency_refs"]
    )

    executor, _, direct = _executor(monkeypatch)
    direct.proposals = iter(({**_architecture(), "unknown": True}, _architecture()))
    store = ArtifactStore(tmp_path / "correction")
    request = EnvironmentRequest.create("Build a support handoff environment.")
    request_ref = store.put_json("control.design_request", {"need_digest": request.need_digest})
    evidence_ref = store.put_envelope(
        ArtifactEnvelope(
            "design.evidence_graph",
            1,
            WorkCoordinate("correction", "design", "research_synthesis", None, 1),
            _digest(),
            (),
            ("evidence", "coverage"),
            {"safe": True},
        )
    )
    evidence = result.design.evidence
    architecture, _, _ = executor._direct_architecture(
        request, evidence, store, design_graph(), "correction", request_ref, evidence_ref
    )
    assert architecture.boundary.name == "support"
    assert [json.loads(call["user"])["correction"] for call in direct.calls] == [None, None]
    feedback = _feedback_packet(direct.calls[1])
    assert feedback["code"] == "world_architecture_invalid"
    assert feedback["path"] == "$"


def test_world_rule_predicate_right_accepts_closed_union_and_rejects_invalid_values(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, _ = _executor(monkeypatch)
    bindings = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        ArtifactStore(tmp_path),
        design_graph(),
        "predicate-right",
    ).design.architecture.catalog.bindings
    rules = []
    for right in (
        {"kind": "literal", "value": "open"},
        {"kind": "semantic_ref", "semantic_index": 1},
    ):
        rule = _rule(1, citation=False)
        rule["when"] = [{"left_semantic_index": 1, "operator": "eq", "right": right}]
        rules.append(rule)

    compiled = _compile_rules(
        rules,
        bindings,
        set(),
        "world_rules_invalid",
        path="$.initial_rules",
        minimum=0,
        maximum=8,
    )
    assert [rule.when[0].right for rule in compiled] == [
        {"kind": "literal", "value": "open"},
        {"kind": "semantic_ref", "semantic_index": 1},
    ]

    invalid_rights: tuple[Any, ...] = ({}, {"kind": "unknown"}, None, ["kind", "value"])
    for right in invalid_rights:
        rule = _rule(1, citation=False)
        rule["when"] = [{"left_semantic_index": 1, "operator": "eq", "right": right}]
        with pytest.raises(DesignError) as error:
            _compile_rules(
                [rule],
                bindings,
                set(),
                "world_rules_invalid",
                path="$.initial_rules",
                minimum=0,
                maximum=8,
            )
        assert str(error.value) == "world_rules_invalid"


def test_effect_value_acceptance_and_precise_rejection_conditions(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, _ = _executor(monkeypatch)
    bindings = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        ArtifactStore(tmp_path),
        design_graph(),
        "effect-value-contract",
    ).design.architecture.catalog.bindings

    def compile_effect(value: Any, operation: str = "set") -> tuple[Any, ...]:
        rule = _rule(1, citation=False)
        rule["effects"] = [{"target_semantic_index": 1, "operation": operation, "value": value}]
        return _compile_rules(
            [rule],
            bindings,
            set(),
            "tool_semantics_invalid",
            path="$.rules",
            minimum=1,
            maximum=1,
        )

    accepted_values: tuple[Any, ...] = (
        None,
        True,
        7,
        1.5,
        "direct literal",
        list(range(32)),
        {"kind": "semantic_ref", "semantic_index": 1},
    )
    for value in accepted_values:
        assert compile_effect(value)[0].effects[0].value == value

    generic_condition = (
        "effect value must be a direct JSON scalar "
        "(null, boolean, integer, finite float, or string) "
        'or a scalar-list of at most 32 such scalars, not a {kind:"literal",value:...} '
        "wrapper; or exactly "
        '{kind:"semantic_ref",semantic_index:<frozen one-based index>} object'
    )
    with pytest.raises(DesignError) as literal_wrapper:
        compile_effect({"kind": "literal", "value": "direct literal"})
    assert literal_wrapper.value.correction is not None
    assert literal_wrapper.value.correction.violated_condition == generic_condition
    assert literal_wrapper.value.correction.expected_category == "semantic_draft"

    with pytest.raises(DesignError) as over_bound:
        compile_effect(list(range(33)))
    assert over_bound.value.correction is not None
    assert over_bound.value.correction.violated_condition == generic_condition

    with pytest.raises(DesignError) as invalid_reference:
        compile_effect({"kind": "semantic_ref", "semantic_index": len(bindings) + 1})
    assert invalid_reference.value.correction is not None
    assert invalid_reference.value.correction.violated_condition == (
        "semantic effect reference must be frozen"
    )
    assert invalid_reference.value.correction.expected_category == "object"

    for operation in ("preserve", "reject"):
        with pytest.raises(DesignError) as nonnull_special_operation:
            compile_effect("not null", operation)
        assert nonnull_special_operation.value.correction is not None
        assert nonnull_special_operation.value.correction.violated_condition == (
            "preserve and reject require null values"
        )
        assert nonnull_special_operation.value.correction.expected_category == "semantic_draft"


def test_world_rules_two_invalid_proposals_persist_failure_without_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, direct = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "predicate-right-base",
    )
    outputs: dict[str, list[ArtifactRef]] = {}
    for work_ref in result.work_refs:
        work = store.read_json(work_ref)
        outputs.setdefault(work["coordinate"]["node_id"], []).extend(
            ArtifactRef(**ref) for ref in work["output_refs"]
        )
    invalid_rule = _rule(1, citation=False)
    invalid_rule["when"] = [{"left_semantic_index": 1, "operator": "eq", "right": None}]
    direct.proposals = iter(({"initial_rules": [invalid_rule], "invariants": []},) * 2)

    with pytest.raises(DesignError):
        executor._direct_rules(
            result.design.architecture,
            result.design.tools,
            store,
            graph,
            "predicate-right-failure",
            outputs["world_architecture"][0],
            tuple(outputs["tool_semantics"]),
        )

    work = next(
        json.loads(path.read_text())["payload"]
        for path in (tmp_path / "artifacts").glob("*.json")
        if (record := json.loads(path.read_text())).get("kind") == "control.work_record"
        and record["payload"].get("coordinate", {}).get("run_id") == "predicate-right-failure"
    )
    validation = store.read_json(ArtifactRef(**work["validation_ref"]))
    finding = store.read_json(ArtifactRef(**work["finding_refs"][0]))
    assert [json.loads(call["user"])["correction"] for call in direct.calls[-2:]] == [
        None,
        None,
    ]
    assert _feedback_packet(direct.calls[-1]) == {
        "code": "world_rules_invalid",
        "expected_category": "object",
        "path": "$.initial_rules[0].when[0].right",
        "violated_condition": "right side must be a finite literal or frozen binding reference",
    }
    assert work["status"] == "failed"
    assert work["safe_code"] == "world_rules_invalid"
    assert work["output_refs"] == []
    assert validation["code"] == finding["code"] == "world_rules_invalid"
    assert "route" not in finding


def test_modeling_gate_shared_artifacts_bind_dependencies_and_semantic_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, _ = _executor(monkeypatch)
    store, graph = ArtifactStore(tmp_path), design_graph()
    result = executor.run(
        EnvironmentRequest.create("Build a support handoff environment."),
        store,
        graph,
        "shared-bind",
    )
    refs = tuple(
        ArtifactRef(**ref) for ref in store.read_json(result.work_refs[-1])["dependency_refs"]
    )

    def produced(node_id: str) -> tuple[ArtifactRef, ...]:
        return tuple(
            ref for ref in refs if store.read_envelope(ref)["producer"]["node_id"] == node_id
        )

    evidence_ref, architecture_ref = (
        produced("research_synthesis")[:1],
        produced("world_architecture")[:1],
    )
    shared_refs, tool_refs = produced("shared_tool_semantics"), produced("tool_semantics")
    curriculum_ref, rules_ref, task_refs = (
        produced("curriculum_plan")[:1],
        produced("world_rules")[:1],
        produced("task_requirement"),
    )
    changed_shared = store.put_envelope(
        ArtifactEnvelope(
            "test.shared_tools",
            1,
            WorkCoordinate("shared-bind", "design", "shared_tool_semantics", "changed", 2),
            _digest(),
            (),
            ("shared_tools",),
            {"changed": True},
        )
    )
    changed_evidence = store.put_envelope(
        ArtifactEnvelope(
            "test.evidence",
            1,
            WorkCoordinate("shared-bind", "design", "research_synthesis", None, 2),
            _digest(),
            (),
            ("evidence", "coverage"),
            {"changed": True},
        )
    )
    changed_tool = store.put_envelope(
        ArtifactEnvelope(
            "test.tool",
            1,
            WorkCoordinate("shared-bind", "design", "tool_semantics", "changed", 2),
            _digest(),
            (),
            ("tool_semantics",),
            {"changed": True},
        )
    )

    def gate(
        run_id: str,
        refs: tuple[ArtifactRef, ...],
        *,
        evidence: ArtifactRef = evidence_ref[0],
        tools: tuple[ArtifactRef, ...] = tool_refs,
    ):
        return executor._modeling_gate(
            result.design.evidence,
            result.design.architecture,
            result.design.shared_tool_contracts,
            result.design.tools,
            result.design.world_rules,
            result.design.curriculum,
            result.design.task_requirements,
            store,
            graph,
            run_id,
            evidence,
            architecture_ref[0],
            refs,
            tools,
            rules_ref[0],
            curriculum_ref[0],
            task_refs,
        )

    first = gate("shared-bind-one", shared_refs)
    second = gate("shared-bind-two", (changed_shared,))
    evidence_changed = gate("evidence-bind", shared_refs, evidence=changed_evidence)
    tools_changed = gate("tools-bind", shared_refs, tools=(changed_tool, tool_refs[1]))
    first_work, second_work = store.read_json(first[2]), store.read_json(second[2])
    assert first_work["dependency_refs"] != second_work["dependency_refs"]
    assert first_work["semantic_revision_digest"] != second_work["semantic_revision_digest"]
    assert changed_shared.artifact_id in {
        ref["artifact_id"] for ref in second_work["dependency_refs"]
    }
    evidence_work = store.read_json(evidence_changed[2])
    assert evidence_work["semantic_revision_digest"] != first_work["semantic_revision_digest"]
    assert changed_evidence.artifact_id in {
        ref["artifact_id"] for ref in evidence_work["dependency_refs"]
    }
    tools_work = store.read_json(tools_changed[2])
    assert tools_work["semantic_revision_digest"] != first_work["semantic_revision_digest"]
    assert changed_tool.artifact_id in {ref["artifact_id"] for ref in tools_work["dependency_refs"]}


def test_recipe_digests_are_exact_and_no_first_only_task_or_tool_survives(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _, _ = _executor(monkeypatch)
    design = executor.run(
        EnvironmentRequest.create("Build support handoffs."),
        ArtifactStore(tmp_path),
        design_graph(),
        "recipes",
    ).design
    for contract in design.executable_tasks:
        expected = tuple(
            recipe.recipe_digest
            for recipe in design.assurance_recipes
            if recipe.task_family_index == contract.task_family_index
        )
        assert contract.verification_requirements.required_recipe_digests == expected
        assert contract.reward_digest == digest_value(contract.reward_spec)
        assert contract.termination_digest == digest_value(contract.termination_spec)
        assert contract.verification_digest == digest_value(contract.verification_requirements)
    assert len({contract.task_family_index for contract in design.executable_tasks}) == 2
    assert len({recipe.tool_index for recipe in design.assurance_recipes}) == 2
