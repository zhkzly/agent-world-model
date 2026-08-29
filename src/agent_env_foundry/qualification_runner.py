"""Host-owned physical Qualification orchestration for one frozen v2 Core."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.builder import ACTOR_FACTORY, BuilderConfig
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.preparation import (
    ActorProxy,
    PreparationSettings,
    _ChildTransport,
)
from agent_env_foundry.public_agent import run_public_episode
from agent_env_foundry.qualification_contracts import (
    NativeVerificationRequest,
    NativeVerificationResult,
    QualificationCore,
    QualificationReceipt,
    QualifiedCatalogManifest,
    QualifiedStartCasesManifest,
    RequirementCoverageEntry,
    RequirementCoverageManifest,
)
from agent_env_foundry.qualification_v2 import (
    FrozenCoreInputs,
    QualificationV2Error,
    derive_qualification_core,
    materialize_qualification_core,
    seal_qualification_evidence,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    EvaluationBinding,
    GoalEvaluationContext,
    StartCase,
    TraceEvent,
    atom_result_from_document,
    binding_from_document,
    capability_from_document,
    start_case_from_document,
    validate_catalog,
    validate_start_cases,
)
from agent_env_foundry.semantics_author import SEMANTICS_FACTORY
from agent_env_foundry.task_foundry import _answer_schema, _instruction, _wrong_answer
from agent_env_foundry.tree_manifest import tree_manifest
from agent_env_foundry.verifier_author import invoke_verifier_transition


@dataclass(frozen=True, slots=True)
class QualificationBudget:
    start_seed: int = 0
    start_limit: int = 4
    max_provider_turns: int = 12

    def __post_init__(self) -> None:
        if isinstance(self.start_seed, bool) or not isinstance(self.start_seed, int):
            raise ValueError("start_seed must be an integer")
        for name in (
            "start_limit",
            "max_provider_turns",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class QualificationReport:
    core: QualificationCore
    evidence_root: Path
    evidence_manifest: JSONObject
    qualified_catalog: QualifiedCatalogManifest
    qualified_start_cases: QualifiedStartCasesManifest
    requirement_coverage: RequirementCoverageManifest
    receipt: QualificationReceipt

    def __post_init__(self) -> None:
        self.receipt.validate_core(self.core)
        expected = {
            "qualified_catalog_digest": self.qualified_catalog.catalog_digest,
            "qualified_start_cases_digest": self.qualified_start_cases.start_cases_digest,
            "requirement_coverage_digest": self.requirement_coverage.coverage_digest,
            "evidence_manifest_digest": hashlib.sha256(
                canonical_bytes(self.evidence_manifest)
            ).hexdigest(),
        }
        if any(getattr(self.receipt, name) != value for name, value in expected.items()):
            raise QualificationV2Error(
                "qualification_report_receipt_mismatch",
                "Qualification report records do not match its strict receipt",
            )


@dataclass(frozen=True, slots=True)
class _EvaluatedCase:
    category: str
    capability: CapabilitySpec
    start: StartCase
    binding: BindingCandidate
    before: Path
    after: Path
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    semantics_result: AtomCheckResult
    verifier_result: NativeVerificationResult

    def to_record(self) -> dict[str, object]:
        agreement_fields = (
            "initially_satisfied",
            "satisfied",
            "required_effects_ok",
            "collateral_ok",
            "answer_ok",
            "process_ok",
            "report_values",
        )
        agreement = all(
            getattr(self.semantics_result, name) == getattr(self.verifier_result, name)
            for name in agreement_fields
        )
        return {
            "category": self.category,
            "capability_id": self.capability.capability_id,
            "start_case_id": self.start.case_id,
            "semantic_key": self.binding.semantic_key,
            "public_descriptor": self.binding.public_descriptor,
            "before_instance_directory": str(self.before),
            "after_instance_directory": str(self.after),
            "axis_agreement": agreement,
            "readers_unchanged": True,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": self.final_answer,
            "semantics_result": self.semantics_result.to_document(),
            "verifier_result": self.verifier_result.to_document(),
        }


class _QualificationHarness:
    def __init__(
        self,
        inputs: FrozenCoreInputs,
        core: QualificationCore,
        cache_root: Path,
        settings: PreparationSettings,
    ) -> None:
        self.inputs = inputs
        self.settings = settings
        self.runtimes = materialize_qualification_core(
            inputs,
            core,
            cache_root,
            settings=settings,
        )
        self._semantics = _ChildTransport(
            self.runtimes.semantics.python,
            Path(__file__).resolve().parent / "_semantics_runner.py",
            (SEMANTICS_FACTORY,),
            cwd=self.runtimes.semantics.project_root,
            timeout=settings.command_timeout_seconds,
            role="semantics",
        )

    def close(self) -> None:
        self._semantics.close(operation="close")

    def actor(self, instance: Path) -> ActorProxy:
        transport = _ChildTransport(
            self.runtimes.actor.python,
            Path(__file__).resolve().parent / "_actor_runner.py",
            (ACTOR_FACTORY, str(instance)),
            cwd=self.runtimes.actor.project_root,
            timeout=self.settings.command_timeout_seconds,
            role="actor",
        )
        return ActorProxy(
            transport,
            start_schema=self.inputs.public_surface.start_schema,
            reset_observation_schema=self.inputs.public_surface.reset_observation_schema,
        )

    def _call(
        self,
        operation: str,
        arguments: JSONObject,
        *instances: Path,
    ) -> JSONValue:
        project_before = tree_manifest(self.runtimes.semantics.project_root).digest
        instance_before = tuple(tree_manifest(path).digest for path in instances)
        value = self._semantics.call(operation, arguments)
        if project_before != tree_manifest(self.runtimes.semantics.project_root).digest or (
            instance_before != tuple(tree_manifest(path).digest for path in instances)
        ):
            raise QualificationV2Error(
                "qualification_semantics_mutation",
                "TaskSemantics changed a project or native instance during Qualification",
                operation=operation,
            )
        return value

    def capabilities(self) -> tuple[CapabilitySpec, ...]:
        raw = self._call("capabilities", {})
        if not isinstance(raw, list):
            raise QualificationV2Error(
                "qualification_capabilities_invalid",
                "TaskSemantics capabilities response is not an array",
            )
        values = tuple(capability_from_document(item) for item in raw)
        validate_catalog(values)
        return values

    def start_cases(self, seed: int, limit: int) -> tuple[StartCase, ...]:
        raw = self._call("start_cases", {"seed": seed, "limit": limit})
        if not isinstance(raw, list):
            raise QualificationV2Error(
                "qualification_start_cases_invalid",
                "TaskSemantics StartCases response is not an array",
            )
        values = tuple(start_case_from_document(item) for item in raw)
        validate_start_cases(
            values,
            start_schema=self.inputs.public_surface.start_schema,
            limit=limit,
        )
        return values

    def inspect(self, instance: Path) -> JSONValue:
        return self._call(
            "inspect",
            {"instance_directory": str(instance)},
            instance,
        )

    def bindings(
        self,
        capability: CapabilitySpec,
        facts: JSONValue,
        instance: Path,
    ) -> tuple[BindingCandidate, ...]:
        raw = self._call(
            "enumerate_bindings",
            {"capability_id": capability.capability_id, "facts": facts},
            instance,
        )
        if not isinstance(raw, list):
            raise QualificationV2Error(
                "qualification_bindings_invalid",
                "TaskSemantics bindings response is not an array",
            )
        return tuple(binding_from_document(item) for item in raw)

    def evaluate(
        self,
        capability: CapabilitySpec,
        binding: BindingCandidate,
        before_facts: JSONValue,
        after_facts: JSONValue,
        before: Path,
        after: Path,
        trace: tuple[TraceEvent, ...],
        final_answer: JSONObject,
    ) -> AtomCheckResult:
        context = GoalEvaluationContext(
            "target",
            (
                EvaluationBinding(
                    "target",
                    capability.capability_id,
                    binding.semantic_key,
                    binding.protected_binding,
                ),
            ),
            None,
            None,
            (),
        )
        request = AtomCheckRequest(
            capability.capability_id,
            before_facts,
            after_facts,
            binding.protected_binding,
            trace,
            final_answer,
            context,
        )
        return atom_result_from_document(
            self._call(
                "evaluate_atom",
                {"request": request.to_document()},
                before,
                after,
            )
        )

    def verify(
        self,
        capability: CapabilitySpec,
        start: StartCase,
        binding: BindingCandidate,
        before: Path,
        after: Path,
        trace: tuple[TraceEvent, ...],
        final_answer: JSONObject,
    ) -> NativeVerificationResult:
        return invoke_verifier_transition(
            self.runtimes.verifier.project_root,
            NativeVerificationRequest(
                capability.capability_id,
                start.case_id,
                binding.public_descriptor,
                trace,
                final_answer,
                before,
                after,
            ),
            expected_verifier_project_digest=self.runtimes.verifier.project_digest,
            expected_report_field_ids=tuple(item.field_id for item in capability.answer_fields),
            config=BuilderConfig(
                uv_cache_dir=self.settings.uv_cache_dir,
                command_timeout_seconds=self.settings.command_timeout_seconds,
            ),
        )


def _case_root(
    root: Path,
    category: str,
    capability: CapabilitySpec,
    start: StartCase,
    semantic_key: str,
    ordinal: int,
) -> Path:
    preimage = {
        "category": category,
        "capability_id": capability.capability_id,
        "start_case_id": start.case_id,
        "semantic_key": semantic_key,
        "ordinal": ordinal,
    }
    return root / hashlib.sha256(canonical_bytes(preimage)).hexdigest()


def _resolve_binding(
    harness: _QualificationHarness,
    capability: CapabilitySpec,
    facts: JSONValue,
    instance: Path,
    semantic_key: str,
) -> BindingCandidate:
    matches = [
        item
        for item in harness.bindings(capability, facts, instance)
        if item.semantic_key == semantic_key
    ]
    if len(matches) != 1:
        raise QualificationV2Error(
            "qualification_binding_unresolved",
            "Qualification cannot resolve one semantic key exactly once",
            capability_id=capability.capability_id,
            semantic_key=semantic_key,
            match_count=len(matches),
        )
    return matches[0]


def _reset_pair(
    harness: _QualificationHarness,
    case_root: Path,
    start: StartCase,
) -> tuple[Path, Path, ActorProxy, JSONValue, JSONValue]:
    before = case_root / "before"
    after = case_root / "after"
    before_actor = harness.actor(before)
    try:
        before_actor.reset(start.reset_input)
    finally:
        before_actor.close()
    after_actor = harness.actor(after)
    try:
        after_reset = after_actor.reset(start.reset_input)
        before_facts = harness.inspect(before)
    except Exception:
        after_actor.close()
        raise
    return before, after, after_actor, after_reset, before_facts


def _evaluate(
    harness: _QualificationHarness,
    category: str,
    capability: CapabilitySpec,
    start: StartCase,
    binding: BindingCandidate,
    before: Path,
    after: Path,
    trace: tuple[TraceEvent, ...],
    final_answer: JSONObject,
) -> _EvaluatedCase:
    before_facts = harness.inspect(before)
    after_facts = harness.inspect(after)
    live_binding = _resolve_binding(
        harness,
        capability,
        before_facts,
        before,
        binding.semantic_key,
    )
    semantics_result = harness.evaluate(
        capability,
        live_binding,
        before_facts,
        after_facts,
        before,
        after,
        trace,
        final_answer,
    )
    verifier_result = harness.verify(
        capability,
        start,
        live_binding,
        before,
        after,
        trace,
        final_answer,
    )
    agreement_fields = (
        "initially_satisfied",
        "satisfied",
        "required_effects_ok",
        "collateral_ok",
        "answer_ok",
        "process_ok",
        "report_values",
    )
    disagreements = {
        name: {
            "semantics": getattr(semantics_result, name),
            "verifier": getattr(verifier_result, name),
        }
        for name in agreement_fields
        if getattr(semantics_result, name) != getattr(verifier_result, name)
    }
    if disagreements:
        raise QualificationV2Error(
            "qualification_reader_disagreement",
            "TaskSemantics and Verifier disagree on physical result axes",
            category=category,
            capability_id=capability.capability_id,
            semantic_key=live_binding.semantic_key,
            disagreements=disagreements,
            semantics_result=semantics_result.to_document(),
            verifier_result=verifier_result.to_document(),
        )
    return _EvaluatedCase(
        category,
        capability,
        start,
        live_binding,
        before,
        after,
        trace,
        final_answer,
        semantics_result,
        verifier_result,
    )


def _discover_bindings(
    harness: _QualificationHarness,
    root: Path,
    capability: CapabilitySpec,
    start: StartCase,
) -> tuple[BindingCandidate, ...]:
    instance = (
        root
        / hashlib.sha256(
            canonical_bytes(
                {
                    "capability_id": capability.capability_id,
                    "start_case_id": start.case_id,
                }
            )
        ).hexdigest()
    )
    actor = harness.actor(instance)
    try:
        actor.reset(start.reset_input)
        facts = harness.inspect(instance)
        return harness.bindings(capability, facts, instance)
    finally:
        actor.close()


def _run_episode_case(
    harness: _QualificationHarness,
    root: Path,
    category: str,
    capability: CapabilitySpec,
    start: StartCase,
    binding: BindingCandidate,
    goal: str,
    route: AgentRoute,
    budget: QualificationBudget,
    ordinal: int,
) -> _EvaluatedCase:
    case = _case_root(root, category, capability, start, binding.semantic_key, ordinal)
    before, after, actor, reset, before_facts = _reset_pair(harness, case, start)
    try:
        live_binding = _resolve_binding(
            harness,
            capability,
            before_facts,
            before,
            binding.semantic_key,
        )
        instruction = _instruction(
            goal,
            live_binding.public_descriptor,
            capability.answer_fields,
        )
        episode = run_public_episode(
            actor=actor,
            instruction=instruction,
            reset_observation=reset,
            tool_specs=actor.tools(),
            answer_schema=_answer_schema(capability.answer_fields),
            route=route,
            max_provider_turns=budget.max_provider_turns,
        )
    finally:
        actor.close()
    return _evaluate(
        harness,
        category,
        capability,
        start,
        binding,
        before,
        after,
        episode.trace,
        episode.final_answer,
    )


def _run_noop_case(
    harness: _QualificationHarness,
    root: Path,
    capability: CapabilitySpec,
    start: StartCase,
    binding: BindingCandidate,
    ordinal: int,
) -> _EvaluatedCase:
    case = _case_root(root, "no_op", capability, start, binding.semantic_key, ordinal)
    before, after, actor, _, _ = _reset_pair(harness, case, start)
    actor.close()
    return _evaluate(
        harness,
        "no_op",
        capability,
        start,
        binding,
        before,
        after,
        (),
        {},
    )


def _variant_case(
    harness: _QualificationHarness,
    source: _EvaluatedCase,
    category: str,
    *,
    trace: tuple[TraceEvent, ...] | None = None,
    final_answer: JSONObject | None = None,
) -> _EvaluatedCase:
    return _evaluate(
        harness,
        category,
        source.capability,
        source.start,
        source.binding,
        source.before,
        source.after,
        source.trace if trace is None else trace,
        source.final_answer if final_answer is None else final_answer,
    )


def _run_wrong_target_case(
    harness: _QualificationHarness,
    root: Path,
    capability: CapabilitySpec,
    start: StartCase,
    target: BindingCandidate,
    control: BindingCandidate,
    goal: str,
    route: AgentRoute,
    budget: QualificationBudget,
    ordinal: int,
) -> _EvaluatedCase:
    case = _case_root(root, "wrong_target", capability, start, target.semantic_key, ordinal)
    before, after, actor, reset, before_facts = _reset_pair(harness, case, start)
    try:
        live_control = _resolve_binding(
            harness,
            capability,
            before_facts,
            before,
            control.semantic_key,
        )
        episode = run_public_episode(
            actor=actor,
            instruction=_instruction(
                goal,
                live_control.public_descriptor,
                capability.answer_fields,
            ),
            reset_observation=reset,
            tool_specs=actor.tools(),
            answer_schema=_answer_schema(capability.answer_fields),
            route=route,
            max_provider_turns=budget.max_provider_turns,
        )
    finally:
        actor.close()
    control_result = _evaluate(
        harness,
        "positive",
        capability,
        start,
        live_control,
        before,
        after,
        episode.trace,
        episode.final_answer,
    )
    if not control_result.semantics_result.satisfied:
        raise QualificationV2Error(
            "qualification_wrong_target_control_failed",
            "Wrong-target control binding did not satisfy its own semantics",
            capability_id=capability.capability_id,
            semantic_key=live_control.semantic_key,
        )
    return _evaluate(
        harness,
        "wrong_target",
        capability,
        start,
        target,
        before,
        after,
        episode.trace,
        episode.final_answer,
    )


def _run_collateral_case(
    harness: _QualificationHarness,
    root: Path,
    primary: tuple[CapabilitySpec, StartCase, BindingCandidate, str],
    control: tuple[CapabilitySpec, BindingCandidate, str],
    route: AgentRoute,
    budget: QualificationBudget,
) -> _EvaluatedCase:
    capability, start, binding, goal = primary
    control_capability, control_binding, control_goal = control
    case = _case_root(root, "collateral", capability, start, binding.semantic_key, 0)
    before, after, actor, reset, before_facts = _reset_pair(harness, case, start)
    try:
        live_primary = _resolve_binding(
            harness,
            capability,
            before_facts,
            before,
            binding.semantic_key,
        )
        primary_episode = run_public_episode(
            actor=actor,
            instruction=_instruction(
                goal,
                live_primary.public_descriptor,
                capability.answer_fields,
            ),
            reset_observation=reset,
            tool_specs=actor.tools(),
            answer_schema=_answer_schema(capability.answer_fields),
            route=route,
            max_provider_turns=budget.max_provider_turns,
        )
        middle = case / "middle"
        shutil.copytree(after, middle)
        middle_facts = harness.inspect(middle)
        live_control = _resolve_binding(
            harness,
            control_capability,
            middle_facts,
            middle,
            control_binding.semantic_key,
        )
        control_episode = run_public_episode(
            actor=actor,
            instruction=_instruction(
                control_goal,
                live_control.public_descriptor,
                control_capability.answer_fields,
            ),
            reset_observation=reset,
            tool_specs=actor.tools(),
            answer_schema=_answer_schema(control_capability.answer_fields),
            route=route,
            max_provider_turns=budget.max_provider_turns,
        )
    finally:
        actor.close()
    middle_facts = harness.inspect(middle)
    after_facts = harness.inspect(after)
    control_result = harness.evaluate(
        control_capability,
        live_control,
        middle_facts,
        after_facts,
        middle,
        after,
        control_episode.trace,
        control_episode.final_answer,
    )
    if not control_result.satisfied:
        raise QualificationV2Error(
            "qualification_collateral_control_failed",
            "Collateral control capability did not satisfy its own semantics",
            capability_id=control_capability.capability_id,
            result=control_result.to_document(),
        )
    offset = max((item.seq for item in primary_episode.trace), default=0)
    combined = primary_episode.trace + tuple(
        TraceEvent(
            offset + item.seq,
            item.tool_name,
            item.arguments,
            item.observation,
        )
        for item in control_episode.trace
    )
    return _evaluate(
        harness,
        "collateral",
        capability,
        start,
        live_primary,
        before,
        after,
        combined,
        primary_episode.final_answer,
    )


def _mutation_records(cases: tuple[_EvaluatedCase, ...]) -> tuple[dict[str, object], ...]:
    agreement_fields = (
        "initially_satisfied",
        "satisfied",
        "required_effects_ok",
        "collateral_ok",
        "answer_ok",
        "process_ok",
        "report_values",
    )
    mutable_axes = ("required_effects_ok", "collateral_ok", "answer_ok", "process_ok")
    records: list[dict[str, object]] = []
    for role in ("semantics", "verifier"):
        selected: tuple[_EvaluatedCase, str, JSONObject, JSONObject] | None = None
        for item in cases:
            own = (
                item.semantics_result.to_document()
                if role == "semantics"
                else item.verifier_result.to_document()
            )
            independent = (
                item.verifier_result.to_document()
                if role == "semantics"
                else item.semantics_result.to_document()
            )
            axis = next(
                (
                    name
                    for name in mutable_axes
                    if own[name] is False and independent[name] is False
                ),
                None,
            )
            if axis is not None:
                selected = (item, axis, own, independent)
                break
        if selected is None:
            raise QualificationV2Error(
                "qualification_mutation_killer_missing",
                "Qualification lacks an independently false result axis for a reader mutant",
                role=role,
            )
        item, axis, original, independent = selected
        mutant = {**original, axis: True}
        killed = any(mutant[name] != independent[name] for name in agreement_fields)
        if not killed:
            raise QualificationV2Error(
                "qualification_mutant_survived",
                "Executable result-axis mutant survived physical cross-reader comparison",
                role=role,
                axis=axis,
            )
        records.append(
            {
                "mutant_id": f"{role}-{axis}-always-true",
                "target_role": role,
                "killed": True,
                "killed_by": "physical_axis_comparison",
                "evidence": {
                    "category": item.category,
                    "capability_id": item.capability.capability_id,
                    "original": original,
                    "mutant": mutant,
                    "independent": independent,
                },
            }
        )
    return tuple(records)


def _requirement_coverage(
    inputs: FrozenCoreInputs,
    manifest: JSONObject,
    starts: QualifiedStartCasesManifest,
) -> RequirementCoverageManifest:
    try:
        expected = json.loads(inputs.expected_semantics_payload)
        requirements = expected["requirements"]
        capabilities = expected["capabilities"]
        entries = cast(list[JSONObject], manifest["cases"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise QualificationV2Error(
            "qualification_coverage_inputs_invalid",
            "Qualification coverage inputs are invalid",
        ) from exc
    positive_digests: dict[str, list[str]] = {}
    for item in entries:
        if item["category"] == "positive":
            positive_digests.setdefault(cast(str, item["capability_id"]), []).append(
                cast(str, item["digest"])
            )
    capability_map: dict[str, list[str]] = {}
    for capability in capabilities:
        for requirement_id in capability["requirement_ids"]:
            capability_map.setdefault(requirement_id, []).append(capability["capability_id"])
    result: list[RequirementCoverageEntry] = []
    for item in requirements:
        requirement_id = cast(str, item["requirement_id"])
        disposition = cast(str, item["disposition"])
        capability_ids = tuple(sorted(capability_map.get(requirement_id, ())))
        evidence_ids = tuple(
            digest
            for capability_id in capability_ids
            for digest in positive_digests.get(capability_id, ())
        )
        if disposition != "Taskable":
            capability_ids = ()
            evidence_ids = (starts.start_cases_digest,)
        result.append(
            RequirementCoverageEntry(
                requirement_id,
                cast(Any, disposition),
                capability_ids,
                evidence_ids,
            )
        )
    return RequirementCoverageManifest(tuple(result))


def _goals(inputs: FrozenCoreInputs) -> dict[str, str]:
    try:
        document = json.loads(inputs.expected_semantics_payload)
        values = {
            item["capability_id"]: item["qualification_goal"] for item in document["capabilities"]
        }
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise QualificationV2Error(
            "qualification_goals_invalid",
            "Expected Semantics qualification goals are invalid",
        ) from exc
    if any(
        not isinstance(key, str) or not isinstance(value, str) or not value
        for key, value in values.items()
    ):
        raise QualificationV2Error(
            "qualification_goals_invalid",
            "Expected Semantics qualification goals must be non-empty strings",
        )
    return values


def run_v2_qualification(
    inputs: FrozenCoreInputs,
    core: QualificationCore,
    destination: Path,
    cache_root: Path,
    *,
    route: AgentRoute,
    budget: QualificationBudget,
    settings: PreparationSettings | None = None,
) -> QualificationReport:
    """Execute and seal the complete Host-owned physical Qualification matrix."""

    if derive_qualification_core(inputs) != core:
        raise QualificationV2Error(
            "qualification_core_mismatch",
            "Qualification inputs differ from the supplied frozen Core",
        )
    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise QualificationV2Error(
            "qualification_destination_exists",
            "Qualification destination must be new",
        )
    selected_settings = settings or PreparationSettings(
        Path("/tmp/agent-env-foundry-v2-qualification-uv-cache")
    )
    work = root / "work"
    evidence_root = root / "evidence"
    harness: _QualificationHarness | None = None
    try:
        work.mkdir(parents=True)
        harness = _QualificationHarness(inputs, core, Path(cache_root), selected_settings)
        capabilities = harness.capabilities()
        starts = harness.start_cases(budget.start_seed, budget.start_limit)
        goals = _goals(inputs)
        if set(goals) != {item.capability_id for item in capabilities}:
            raise QualificationV2Error(
                "qualification_goal_coverage_mismatch",
                "Qualification goals and live capability catalog differ",
            )
        catalog = QualifiedCatalogManifest(capabilities)
        start_manifest = QualifiedStartCasesManifest(
            budget.start_seed,
            budget.start_limit,
            starts,
        )
        cases: list[_EvaluatedCase] = []
        positives: list[_EvaluatedCase] = []
        ineligible: list[tuple[CapabilitySpec, StartCase, BindingCandidate]] = []
        ordinal = 0
        for start in starts:
            for capability in capabilities:
                discovered = _discover_bindings(
                    harness,
                    work / "discovery",
                    capability,
                    start,
                )
                eligible = [item for item in discovered if item.eligible]
                ineligible.extend(
                    (capability, start, item) for item in discovered if not item.eligible
                )
                if not eligible:
                    continue
                binding = eligible[0]
                positive = _run_episode_case(
                    harness,
                    work / "cases",
                    "positive",
                    capability,
                    start,
                    binding,
                    goals[capability.capability_id],
                    route,
                    budget,
                    ordinal,
                )
                ordinal += 1
                if not positive.semantics_result.satisfied:
                    raise QualificationV2Error(
                        "qualification_positive_failed",
                        "Public Qualification episode did not satisfy TaskSemantics",
                        capability_id=capability.capability_id,
                        result=positive.semantics_result.to_document(),
                    )
                positives.append(positive)
                cases.append(positive)
                replay = _run_episode_case(
                    harness,
                    work / "cases",
                    "fresh_replay",
                    capability,
                    start,
                    binding,
                    goals[capability.capability_id],
                    route,
                    budget,
                    ordinal,
                )
                ordinal += 1
                cases.append(replay)

        represented = {item.capability.capability_id for item in positives}
        missing = {item.capability_id for item in capabilities} - represented
        if missing:
            raise QualificationV2Error(
                "qualification_positive_coverage_missing",
                "No eligible public Qualification case represents a capability",
                missing=sorted(missing),
            )

        stateful_positives = [
            item
            for item in positives
            if item.capability.task_kind != "query"
            and canonical_bytes(harness.inspect(item.before))
            != canonical_bytes(harness.inspect(item.after))
        ]
        if not stateful_positives:
            raise QualificationV2Error(
                "qualification_state_change_case_missing",
                "Qualification requires one positive case with a real native state change",
            )
        no_op_source = stateful_positives[0]
        cases.append(
            _run_noop_case(
                harness,
                work / "cases",
                no_op_source.capability,
                no_op_source.start,
                no_op_source.binding,
                ordinal,
            )
        )
        ordinal += 1
        cases.append(_variant_case(harness, no_op_source, "missing_process", trace=()))

        query_source = next(
            (item for item in positives if item.capability.task_kind == "query"),
            None,
        )
        if query_source is None:
            raise QualificationV2Error(
                "qualification_query_case_missing",
                "Qualification requires one query capability for answer challenges",
            )
        wrong = _wrong_answer(
            _answer_schema(query_source.capability.answer_fields),
            query_source.semantics_result.report_values,
        )
        if wrong is None:
            raise QualificationV2Error(
                "qualification_wrong_answer_unavailable",
                "Query answer schema has no deterministic wrong alternative",
            )
        cases.append(_variant_case(harness, query_source, "wrong_answer", final_answer=wrong))
        cases.append(_variant_case(harness, query_source, "missing_process", trace=()))

        query_bindings = [
            item
            for item in _discover_bindings(
                harness,
                work / "wrong-target-discovery",
                query_source.capability,
                query_source.start,
            )
            if item.eligible
        ]
        wrong_control = next(
            (
                item
                for item in query_bindings
                if item.semantic_key != query_source.binding.semantic_key
            ),
            None,
        )
        if wrong_control is None:
            raise QualificationV2Error(
                "qualification_wrong_target_binding_missing",
                "Qualification requires two eligible bindings for a wrong-target challenge",
            )
        cases.append(
            _run_wrong_target_case(
                harness,
                work / "cases",
                query_source.capability,
                query_source.start,
                query_source.binding,
                wrong_control,
                goals[query_source.capability.capability_id],
                route,
                budget,
                ordinal,
            )
        )
        ordinal += 1

        state_ineligible = [item for item in ineligible if item[0].task_kind != "query"]
        if state_ineligible:
            capability, start, binding = state_ineligible[0]
            cases.append(
                _run_episode_case(
                    harness,
                    work / "cases",
                    "near_miss",
                    capability,
                    start,
                    binding,
                    goals[capability.capability_id],
                    route,
                    budget,
                    ordinal,
                )
            )
            ordinal += 1

        primary = (
            query_source.capability,
            query_source.start,
            query_source.binding,
            goals[query_source.capability.capability_id],
        )
        control_source = next(
            item
            for item in stateful_positives
            if set(item.capability.workflow_ids).isdisjoint(query_source.capability.workflow_ids)
            and item.start == query_source.start
        )
        control = (
            control_source.capability,
            control_source.binding,
            goals[control_source.capability.capability_id],
        )
        cases.append(
            _run_collateral_case(
                harness,
                work / "cases",
                primary,
                control,
                route,
                budget,
            )
        )

        reference_route = tuple(item.tool_name for item in query_source.trace)
        existing_alternative = next(
            (
                item
                for item in cases
                if item.category == "fresh_replay"
                and item.capability.capability_id == query_source.capability.capability_id
                and item.start == query_source.start
                and item.binding.semantic_key == query_source.binding.semantic_key
                and tuple(event.tool_name for event in item.trace) != reference_route
            ),
            None,
        )
        if existing_alternative is not None:
            cases.append(
                _evaluate(
                    harness,
                    "alternative_route",
                    existing_alternative.capability,
                    existing_alternative.start,
                    existing_alternative.binding,
                    existing_alternative.before,
                    existing_alternative.after,
                    existing_alternative.trace,
                    existing_alternative.final_answer,
                )
            )

        mutations = _mutation_records(tuple(cases))
        manifest = seal_qualification_evidence(
            core,
            evidence_root,
            case_records=tuple(item.to_record() for item in cases),
            mutation_records=mutations,
            required_capability_ids=tuple(item.capability_id for item in capabilities),
        )
        coverage = _requirement_coverage(inputs, manifest, start_manifest)
        receipt = QualificationReceipt(
            core.core_id,
            core.expected_semantics_digest,
            core.actor_project_digest,
            core.semantics_project_digest,
            core.verifier_project_digest,
            core.public_surface_manifest_digest,
            catalog.catalog_digest,
            coverage.coverage_digest,
            start_manifest.start_cases_digest,
            hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
        )
        report = QualificationReport(
            core,
            evidence_root,
            manifest,
            catalog,
            start_manifest,
            coverage,
            receipt,
        )
        shutil.rmtree(work)
        return report
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    finally:
        if harness is not None:
            harness.close()


__all__ = ["QualificationBudget", "QualificationReport", "run_v2_qualification"]
