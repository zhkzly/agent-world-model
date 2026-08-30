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
from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec
from agent_env_foundry.preparation import (
    ActorProxy,
    PreparationSettings,
    _ChildTransport,
)
from agent_env_foundry.public_agent import run_public_episode
from agent_env_foundry.qualification_contracts import (
    NativeVerificationRequest,
    NativeVerificationResult,
    PublicSurfaceManifest,
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
from agent_env_foundry.schema import SchemaError, validate_instance
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
from agent_env_foundry.task_foundry import _answer_schema, _instruction
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
    reset_observation: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    semantics_result: AtomCheckResult
    verifier_result: NativeVerificationResult
    answer_source_evidence: tuple[JSONObject, ...]

    def to_record(self) -> dict[str, object]:
        agreement_fields = (
            "required_effects_ok",
            "collateral_ok",
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
            "reset_observation": self.reset_observation,
            "axis_agreement": agreement,
            "readers_unchanged": True,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": self.final_answer,
            "semantics_result": self.semantics_result.to_document(),
            "verifier_result": self.verifier_result.to_document(),
            "answer_source_evidence": list(self.answer_source_evidence),
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
    ) -> NativeVerificationResult:
        return invoke_verifier_transition(
            self.runtimes.verifier.project_root,
            NativeVerificationRequest(
                capability.capability_id,
                start.case_id,
                binding.public_descriptor,
                trace,
                before,
                after,
            ),
            expected_verifier_project_digest=self.runtimes.verifier.project_digest,
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


def _validate_task_kind_transition(
    capability: CapabilitySpec,
    before_facts: JSONValue,
    after_facts: JSONValue,
) -> None:
    changed = canonical_bytes(before_facts) != canonical_bytes(after_facts)
    expected_change = capability.task_kind == "state_change"
    if changed != expected_change:
        raise QualificationV2Error(
            "qualification_task_kind_mismatch",
            "Capability task_kind disagrees with its physical semantic state transition",
            capability_id=capability.capability_id,
            task_kind=capability.task_kind,
            semantic_state_changed=changed,
        )


_TOOL_ERROR_SCHEMA: JSONObject = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {},
    },
    "required": ["code", "message"],
    "additionalProperties": False,
}


def _validate_answer_field_source_contract(
    capabilities: tuple[CapabilitySpec, ...],
    surface: PublicSurfaceManifest,
) -> None:
    """Bind every AnswerField declaration to one real public schema source."""

    tools = {item["name"]: item for item in surface.tool_specs}
    for capability in capabilities:
        for field in capability.answer_fields:
            source = field.public_source
            try:
                _answer_source_schema(capability, source, surface, tools)
                if source.kind in {"task_literal", "tool_schema_constant"}:
                    validate_instance(
                        source.value,
                        field.schema,
                        role=(
                            f"capability {capability.capability_id!r} answer field "
                            f"{field.field_id!r} source value"
                        ),
                    )
            except (KeyError, SchemaError, TypeError, ValueError) as exc:
                raise QualificationV2Error(
                    "qualification_answer_source_pointer_invalid",
                    "AnswerField public source does not resolve through the sealed public schemas",
                    capability_id=capability.capability_id,
                    field_id=field.field_id,
                    source=source.to_document(),
                    original_code=type(exc).__name__,
                    original_message=str(exc),
                ) from exc


def _answer_source_schema(
    capability: CapabilitySpec,
    source: Any,
    surface: PublicSurfaceManifest,
    tools: dict[str, ToolSpec],
) -> dict[str, Any]:
    if source.kind == "task_literal":
        return {}
    pointer = cast(str, source.json_pointer)
    if source.kind == "task_descriptor":
        return _schema_at_public_pointer(capability.public_descriptor_schema, pointer)
    if source.kind == "reset":
        return _schema_at_public_pointer(surface.reset_observation_schema, pointer)
    tool = tools[cast(str, source.tool_name)]
    if source.kind == "tool_schema_constant":
        schema = _schema_at_public_pointer(tool["input_schema"], pointer)
        constant = schema.get("const")
        enum = schema.get("enum")
        is_constant = ("const" in schema and _same_json(constant, source.value)) or (
            isinstance(enum, list) and len(enum) == 1 and _same_json(enum[0], source.value)
        )
        if not is_constant:
            raise ValueError("tool_schema_constant pointer is not an exact const or singleton enum")
        return schema
    if source.kind != "tool_observation":
        raise ValueError(f"unsupported AnswerField source kind {source.kind!r}")
    tokens = _pointer_tokens(pointer)
    if not tokens:
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "data": {"anyOf": [tool["output_schema"], {"type": "null"}]},
                "error": {"anyOf": [_TOOL_ERROR_SCHEMA, {"type": "null"}]},
            },
            "required": ["ok", "data", "error"],
            "additionalProperties": False,
        }
    head, *tail = tokens
    relative = "" if not tail else "/" + "/".join(_escape_pointer_token(item) for item in tail)
    if head == "ok":
        if tail:
            raise ValueError("tool observation ok is scalar")
        return {"type": "boolean"}
    if head == "data":
        return _schema_at_public_pointer(tool["output_schema"], relative)
    if head == "error":
        return _schema_at_public_pointer(_TOOL_ERROR_SCHEMA, relative)
    raise ValueError("tool observation pointer must start at /ok, /data, or /error")


def _schema_at_public_pointer(schema: JSONObject, pointer: str) -> dict[str, Any]:
    current: Any = schema
    root: Any = schema
    seen_refs: set[str] = set()
    for token in _pointer_tokens(pointer):
        current = _dereference_local_schema(current, root, seen_refs)
        if not isinstance(current, dict):
            raise TypeError("schema pointer traverses a non-object schema")
        properties = current.get("properties")
        if isinstance(properties, dict) and token in properties:
            current = properties[token]
            continue
        items = current.get("items")
        if isinstance(items, dict) and token.isdigit():
            current = items
            continue
        raise KeyError(token)
    current = _dereference_local_schema(current, root, seen_refs)
    if not isinstance(current, dict):
        raise TypeError("schema pointer does not resolve to a schema object")
    return cast(dict[str, Any], current)


def _dereference_local_schema(current: Any, root: Any, seen: set[str]) -> Any:
    while isinstance(current, dict) and isinstance(current.get("$ref"), str):
        reference = cast(str, current["$ref"])
        if not reference.startswith("#") or reference in seen:
            raise ValueError("schema source contains an invalid or cyclic local reference")
        seen.add(reference)
        current = _json_pointer_value(root, reference.removeprefix("#"))
    return current


def _answer_field_evidence(
    capability: CapabilitySpec,
    binding: Any,
    reset_observation: JSONValue,
    trace: tuple[TraceEvent, ...],
    report_values: JSONObject,
) -> tuple[JSONObject, ...]:
    expected_ids = {field.field_id for field in capability.answer_fields}
    if set(report_values) != expected_ids:
        raise QualificationV2Error(
            "qualification_answer_report_fields_mismatch",
            "Reader report_values differ from the qualified AnswerField IDs",
            capability_id=capability.capability_id,
            expected=sorted(expected_ids),
            actual=sorted(report_values),
        )
    records: list[JSONObject] = []
    for field in capability.answer_fields:
        report_value = report_values[field.field_id]
        try:
            validate_instance(
                report_value,
                field.schema,
                role=(f"capability {capability.capability_id!r} report field {field.field_id!r}"),
            )
        except SchemaError as exc:
            raise QualificationV2Error(
                "qualification_answer_report_schema_mismatch",
                "Reader report value violates its frozen AnswerField schema",
                capability_id=capability.capability_id,
                field_id=field.field_id,
                report_value=report_value,
                original_message=str(exc),
            ) from exc
        occurrences = _source_occurrences(
            field.public_source,
            binding.public_descriptor,
            reset_observation,
            trace,
        )
        matching = [
            occurrence
            for occurrence in occurrences
            if _same_json(occurrence["value"], report_value)
        ]
        if occurrences and not matching:
            raise QualificationV2Error(
                "qualification_answer_source_value_mismatch",
                "Reader report value differs from every real public source occurrence",
                capability_id=capability.capability_id,
                field_id=field.field_id,
                report_value=report_value,
                source=field.public_source.to_document(),
                observed_values=[item["value"] for item in occurrences],
            )
        if not occurrences and report_value is not None:
            raise QualificationV2Error(
                "qualification_answer_source_value_mismatch",
                "Reader emitted a non-null report value without a real public source occurrence",
                capability_id=capability.capability_id,
                field_id=field.field_id,
                report_value=report_value,
                source=field.public_source.to_document(),
            )
        records.append(
            {
                "field_id": field.field_id,
                "source": field.public_source.to_document(),
                "report_value": report_value,
                "occurrences": cast(JSONValue, matching),
            }
        )
    return tuple(records)


def _source_occurrences(
    source: Any,
    public_descriptor: JSONObject,
    reset_observation: JSONValue,
    trace: tuple[TraceEvent, ...],
) -> list[JSONObject]:
    pointer = source.json_pointer
    if source.kind == "task_literal":
        return [_source_occurrence(source.kind, None, None, source.value)]
    if source.kind == "task_descriptor":
        return [
            _source_occurrence(
                source.kind,
                None,
                pointer,
                _json_pointer_value(public_descriptor, cast(str, pointer)),
            )
        ]
    if source.kind == "reset":
        return [
            _source_occurrence(
                source.kind,
                None,
                pointer,
                _json_pointer_value(reset_observation, cast(str, pointer)),
            )
        ]
    if source.kind == "tool_schema_constant":
        return [_source_occurrence(source.kind, None, pointer, source.value)]
    occurrences: list[JSONObject] = []
    for event in trace:
        if event.tool_name != source.tool_name:
            continue
        try:
            value = _json_pointer_value(event.observation, cast(str, pointer))
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        occurrences.append(_source_occurrence(source.kind, event.seq, pointer, value))
    return occurrences


def _source_occurrence(
    kind: str,
    trace_event_seq: int | None,
    pointer: str | None,
    value: JSONValue,
) -> JSONObject:
    return {
        "kind": kind,
        "trace_event_seq": trace_event_seq,
        "json_pointer": pointer,
        "value": value,
    }


def _json_pointer_value(value: Any, pointer: str) -> JSONValue:
    current = value
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise TypeError("JSON pointer traverses a scalar")
    return cast(JSONValue, current)


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("not an RFC 6901 pointer")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _same_json(left: Any, right: Any) -> bool:
    try:
        return canonical_bytes(left) == canonical_bytes(right)
    except (TypeError, ValueError):
        return False


def _evaluate(
    harness: _QualificationHarness,
    category: str,
    capability: CapabilitySpec,
    start: StartCase,
    binding: BindingCandidate,
    before: Path,
    after: Path,
    reset_observation: JSONValue,
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
    )
    agreement_fields = (
        "required_effects_ok",
        "collateral_ok",
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
    answer_source_evidence = _answer_field_evidence(
        capability,
        live_binding,
        reset_observation,
        trace,
        semantics_result.report_values,
    )
    return _EvaluatedCase(
        category,
        capability,
        start,
        live_binding,
        before,
        after,
        reset_observation,
        trace,
        final_answer,
        semantics_result,
        verifier_result,
        answer_source_evidence,
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
        reset,
        episode.trace,
        episode.final_answer,
    )


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
        _validate_answer_field_source_contract(capabilities, inputs.public_surface)
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
        ordinal = 0
        for capability in capabilities:
            positive: _EvaluatedCase | None = None
            for start in starts:
                discovered = _discover_bindings(
                    harness,
                    work / "discovery",
                    capability,
                    start,
                )
                eligible = [item for item in discovered if item.eligible]
                if not eligible:
                    continue
                positive = _run_episode_case(
                    harness,
                    work / "cases",
                    "positive",
                    capability,
                    start,
                    eligible[0],
                    goals[capability.capability_id],
                    route,
                    budget,
                    ordinal,
                )
                ordinal += 1
                break
            if positive is None:
                raise QualificationV2Error(
                    "qualification_positive_coverage_missing",
                    "No eligible public Qualification case represents a capability",
                    capability_id=capability.capability_id,
                )
            if not positive.semantics_result.satisfied or not positive.verifier_result.satisfied:
                raise QualificationV2Error(
                    "qualification_positive_failed",
                    "Public capability execution or native audit did not pass",
                    capability_id=capability.capability_id,
                    semantics_result=positive.semantics_result.to_document(),
                    verifier_result=positive.verifier_result.to_document(),
                )
            _validate_task_kind_transition(
                capability,
                harness.inspect(positive.before),
                harness.inspect(positive.after),
            )
            cases.append(positive)

        manifest = seal_qualification_evidence(
            core,
            evidence_root,
            case_records=tuple(item.to_record() for item in cases),
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
