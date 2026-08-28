"""Host-owned public episodes and physical TaskSemantics Qualification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from agent_env_foundry._qualification_runner import _tree_manifest
from agent_env_foundry.agents import (
    AgentRoute,
    ClientFactory,
    _default_client_factory,
    _ProviderTurnBudget,
    _run_tool_json_loop,
)
from agent_env_foundry.builder import compute_candidate_digest
from agent_env_foundry.environment import Environment, JSONObject, JSONValue, ToolSpec
from agent_env_foundry.native_oracle import (
    NativeAtomEvidence,
    NativeOracleFailure,
    NativeOracleSession,
)
from agent_env_foundry.preparation import ActorProxy, _ChildTransport
from agent_env_foundry.qualification import (
    PUBLIC_SURFACE_NAME,
    QualificationConfig,
    QualificationResult,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.research import ResearchFailure
from agent_env_foundry.schema import SchemaError, validate_instance
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    StartCase,
    TraceEvent,
    atom_result_from_document,
    binding_from_document,
    capability_from_document,
    start_case_from_document,
    validate_binding,
    validate_catalog,
    validate_start_cases,
)
from agent_env_foundry.semantics_author import SemanticsBuild, compute_semantics_project_digest


class SemanticQualificationFailure(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = {"phase": "semantic_qualification", **details}


@dataclass(frozen=True, slots=True)
class PublicCapabilityEpisode:
    capability_id: str
    trace: tuple[TraceEvent, ...]
    final_answer: JSONValue | None
    model_id: str

    def to_document(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "trace": [event.to_document() for event in self.trace],
            "final_answer": self.final_answer,
            "model_id": self.model_id,
        }


def run_public_capability_episode(
    *,
    actor: Environment,
    capability: CapabilitySpec,
    binding: BindingCandidate,
    reset_observation: JSONValue,
    reset_schema: dict[str, Any],
    public_documents: dict[str, str],
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    max_provider_turns: int = 5,
) -> PublicCapabilityEpisode:
    """Let a public policy demonstrate one frozen capability through real actor tools."""
    selected_route = route or AgentRoute()
    budget = _ProviderTurnBudget(min(selected_route.max_provider_turns, max_provider_turns))
    trace: list[TraceEvent] = []
    tool_specs = actor.tools()
    tools = [_actor_function_tool(spec) for spec in tool_specs]
    dispatch: dict[str, Any] = {}

    def make_dispatch(tool_name: str) -> Any:
        def invoke_tool(**arguments: Any) -> dict[str, Any]:
            observation = actor.invoke(tool_name, cast(JSONObject, arguments))
            trace.append(
                TraceEvent(
                    len(trace) + 1,
                    tool_name,
                    cast(JSONObject, arguments),
                    cast(JSONObject, observation),
                )
            )
            return dict(observation)

        return invoke_tool

    for spec in tool_specs:
        tool_name = spec["name"]
        dispatch[tool_name] = make_dispatch(tool_name)
    answer_schema = _episode_answer_schema(capability)
    public_input = {
        "capability": {
            "capability_id": capability.capability_id,
            "actor_role": capability.actor_role,
            "task_kind": capability.task_kind,
            "intent_label": capability.intent_label,
            "rendering": capability.rendering.to_document(),
            "answer_fields": [field.to_document() for field in capability.answer_fields],
        },
        "target": _agent_visible_target(
            capability,
            binding,
            reset_observation,
            reset_schema,
        ),
        "reset_observation": reset_observation,
        "public_documents": public_documents,
    }
    try:
        document = _run_tool_json_loop(
            route=selected_route,
            client_factory=client_factory or _default_client_factory,
            instructions=(
                "Demonstrate the requested public capability by calling the supplied actor "
                "tools. Use only the reset observation, public target, tool schemas and tool "
                "observations and public documents. Do not invent protected identifiers, "
                "native state, verifier facts or a pass/fail verdict. For a query, use public "
                "reads and do not make a successful state-changing call. Return the required "
                "structured answer only after the public evidence is sufficient."
            ),
            input_text=json.dumps(public_input, ensure_ascii=False, sort_keys=True),
            schema_name="public_capability_episode",
            schema=answer_schema,
            tools=tools,
            dispatch=dispatch,
            provider_budget=budget,
            output_code="public_episode_output_invalid",
            strict_output=False,
        )
    except ResearchFailure as exc:
        raise SemanticQualificationFailure(
            "public_episode_failed",
            "Public capability episode did not complete",
            original_phase=exc.phase,
            original_code=exc.code,
            original_message=str(exc),
            original_details=exc.details,
            action_trace=[item.to_document() for item in trace],
        ) from exc
    if not trace:
        raise SemanticQualificationFailure(
            "public_episode_no_action",
            "Public capability episode returned without invoking an actor tool",
            capability_id=capability.capability_id,
        )
    answer = document["answer"]
    return PublicCapabilityEpisode(
        capability.capability_id,
        tuple(trace),
        cast(JSONValue | None, answer),
        selected_route.model,
    )


def _agent_visible_target(
    spec: CapabilitySpec,
    binding: BindingCandidate,
    reset_observation: JSONValue,
    reset_schema: dict[str, Any],
) -> JSONObject:
    _validate_pre_episode_binding_visibility(spec, binding, reset_observation, reset_schema)
    facet_specs = {facet.name: facet for facet in spec.facets}
    return cast(
        JSONObject,
        json.loads(
            json.dumps(
                {
                    "public_descriptor": binding.public_descriptor,
                    "facets": {
                        name: value
                        for name, value in binding.facets.items()
                        if facet_specs[name].visibility in {"task_literal", "reset"}
                    },
                }
            )
        ),
    )


def _episode_answer_schema(capability: CapabilitySpec) -> dict[str, Any]:
    if capability.answer_fields:
        answer: dict[str, Any] = {
            "type": "object",
            "properties": {field.field_id: field.schema for field in capability.answer_fields},
            "required": [field.field_id for field in capability.answer_fields],
            "additionalProperties": False,
        }
    else:
        answer = {"type": "null"}
    return {
        "type": "object",
        "properties": {"answer": answer},
        "required": ["answer"],
        "additionalProperties": False,
    }


def _actor_function_tool(spec: ToolSpec) -> dict[str, Any]:
    parameters = cast(dict[str, Any], json.loads(json.dumps(spec["input_schema"])))
    parameters.setdefault("properties", {})
    return {
        "type": "function",
        "name": spec["name"],
        "description": spec["description"],
        "parameters": parameters,
        # Generated ToolSpecs are complete Draft 2020-12 schemas, not necessarily
        # the smaller strict-function subset. ActorProxy validates the original
        # schema before dispatch, so provider strictness is not semantic authority.
        "strict": False,
    }


@dataclass(frozen=True, slots=True)
class ConcreteCapabilityScenario:
    capability_id: str
    selected_semantic_key: str
    role: str
    before_instance: str
    after_instance: str
    start_case: StartCase
    setup_trace: tuple[TraceEvent, ...]
    action_trace: tuple[TraceEvent, ...]
    final_answer: JSONValue | None
    action_instance_before_digest: str
    action_instance_after_digest: str

    def to_document(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "selected_semantic_key": self.selected_semantic_key,
            "role": self.role,
            "before_instance": self.before_instance,
            "after_instance": self.after_instance,
            "start_case": self.start_case.to_document(),
            "setup_trace": [event.to_document() for event in self.setup_trace],
            "action_trace": [event.to_document() for event in self.action_trace],
            "final_answer": self.final_answer,
            "action_instance_before_digest": self.action_instance_before_digest,
            "action_instance_after_digest": self.action_instance_after_digest,
        }


@dataclass(frozen=True, slots=True)
class SemanticCapabilityEvidence:
    capability_id: str
    semantic_key: str
    action_result: AtomCheckResult
    no_op_result: AtomCheckResult
    wrong_target_checked: bool
    wrong_target_not_applicable_reason: str | None
    wrong_answer_checked: bool
    process_challenge_checked: bool
    fresh_replay_passed: bool = False
    physical_wrong_target_checked: bool = False

    def to_document(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "semantic_key": self.semantic_key,
            "action_result": self.action_result.to_document(),
            "no_op_result": self.no_op_result.to_document(),
            "wrong_target_checked": self.wrong_target_checked,
            "wrong_target_not_applicable_reason": self.wrong_target_not_applicable_reason,
            "wrong_answer_checked": self.wrong_answer_checked,
            "process_challenge_checked": self.process_challenge_checked,
            "fresh_replay_passed": self.fresh_replay_passed,
            "physical_wrong_target_checked": self.physical_wrong_target_checked,
        }


@dataclass(frozen=True, slots=True)
class SemanticQualificationReport:
    semantics_digest: str
    public_episode_digest: str
    native_evidence_digest: str
    evidence_digest: str
    capabilities: tuple[SemanticCapabilityEvidence, ...]


@dataclass(frozen=True, slots=True)
class _CapabilityMaterialization:
    capability_id: str
    start_case: StartCase
    before_instance: Path
    after_instance: Path
    before_reset_observation: JSONValue
    after_reset_observation: JSONValue
    selected_binding: BindingCandidate
    episode: PublicCapabilityEpisode
    before_facts_digest: str


def qualify_semantic_capabilities(
    semantics: SemanticsBuild,
    qualification: QualificationResult,
    candidate_root: Path,
    *,
    config: QualificationConfig,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    runtime_root: Path | None = None,
) -> SemanticQualificationReport:
    """Materialize public episodes, then let Framework qualify every semantic atom."""
    source = qualification.semantics_author_inputs
    if source is None or qualification.workspace_root is None:
        raise SemanticQualificationFailure(
            "semantic_qualification_input_missing",
            "Actor Qualification omitted semantics inputs or its admitted workspace",
        )
    source.verify_inputs()
    candidate = Path(candidate_root).resolve()
    public = _read_object(source.root / PUBLIC_SURFACE_NAME)
    if public.get("candidate_digest") != compute_candidate_digest(candidate):
        raise SemanticQualificationFailure(
            "semantic_candidate_mismatch",
            "Semantic Qualification binds different Candidate bytes",
        )
    _validate_public_surface_schema_evidence(public)
    runtime = (
        Path(runtime_root)
        if runtime_root is not None
        else source.root.parent / "semantic-qualification-runtime"
    )
    if runtime.is_symlink() or (runtime.exists() and any(runtime.iterdir())):
        raise SemanticQualificationFailure(
            "semantic_runtime_not_fresh",
            "Semantic Qualification runtime must be fresh and empty",
        )
    runtime.mkdir()
    if (
        qualification.expected_task_semantics_digest is None
        or qualification.probe_bundle_digest is None
    ):
        raise SemanticQualificationFailure(
            "native_oracle_identity_missing",
            "Actor Qualification omitted native-oracle or ExpectedTaskSemantics identity",
        )
    oracle = NativeOracleSession(
        probe_path=qualification.workspace_root / "native_probe.py",
        runtime_root=runtime / "native-oracle",
        candidate_digest=qualification.candidate_digest,
        expected_task_semantics_digest=qualification.expected_task_semantics_digest,
        semantics_digest=semantics.project_digest,
        oracle_bundle_digest=qualification.probe_bundle_digest,
        config=config,
    )
    transport = _ChildTransport(
        semantics.root / ".venv/bin/python",
        Path(__file__).parent / "_semantics_runner.py",
        (semantics.factory,),
        cwd=semantics.root,
        timeout=config.command_timeout_seconds,
        role="semantics",
    )
    evidence: list[SemanticCapabilityEvidence] = []
    episodes: list[PublicCapabilityEpisode] = []
    try:
        raw_catalog = transport.call("capabilities", {})
        if not isinstance(raw_catalog, list):
            raise SemanticQualificationFailure(
                "semantic_catalog_invalid",
                "Semantics capabilities must return an array",
            )
        catalog = validate_catalog(tuple(capability_from_document(item) for item in raw_catalog))
        start_limit = _semantic_start_limit(public)
        raw_cases = transport.call("start_cases", {"seed": 0, "limit": start_limit})
        if not isinstance(raw_cases, list) or not raw_cases:
            raise SemanticQualificationFailure(
                "semantic_start_cases_invalid",
                "Semantics start_cases must return a non-empty array",
            )
        cases = tuple(start_case_from_document(item) for item in raw_cases)
        validate_start_cases(
            cases,
            start_schema=cast(JSONObject, public["start_schema"]),
            limit=start_limit,
        )
        _preflight_native_oracle(
            transport,
            oracle,
            catalog,
            cases,
            candidate,
            public,
            runtime / "oracle-preflight",
            config,
        )
        for capability_id in sorted(catalog):
            capability_evidence, materialization = _materialize_capability_episode(
                transport,
                catalog,
                catalog[capability_id],
                cases,
                candidate,
                public,
                runtime / capability_id / "primary",
                config,
                role="primary",
                oracle=oracle,
                route=route,
                client_factory=client_factory,
            )
            replay_evidence, replay_materialization = _materialize_capability_episode(
                transport,
                catalog,
                catalog[capability_id],
                cases,
                candidate,
                public,
                runtime / capability_id / "fresh-replay",
                config,
                role="fresh-replay",
                oracle=oracle,
                required_start_case=materialization.start_case,
                required_semantic_key=materialization.selected_binding.semantic_key,
                route=route,
                client_factory=client_factory,
            )
            _require_fresh_replay(
                capability_id,
                capability_evidence.semantic_key,
                replay_evidence.semantic_key,
                materialization.before_facts_digest,
                replay_materialization.before_facts_digest,
            )
            physical_wrong_target_checked, wrong_target_materialization = (
                _materialize_physical_wrong_target(
                    transport,
                    catalog[capability_id],
                    materialization,
                    candidate,
                    public,
                    runtime / capability_id / "wrong-target",
                    config,
                    oracle=oracle,
                    route=route,
                    client_factory=client_factory,
                )
            )
            evidence.append(
                replace(
                    capability_evidence,
                    fresh_replay_passed=True,
                    physical_wrong_target_checked=physical_wrong_target_checked,
                )
            )
            episodes.append(materialization.episode)
            episodes.append(replay_materialization.episode)
            if wrong_target_materialization is not None:
                episodes.append(wrong_target_materialization.episode)
    finally:
        transport.close(operation="close")
    try:
        native_evidence_digest = oracle.evidence_digest
    except NativeOracleFailure as exc:
        raise SemanticQualificationFailure(exc.code, str(exc), **exc.details) from exc
    source.verify_inputs()
    if compute_candidate_digest(candidate) != public["candidate_digest"]:
        raise SemanticQualificationFailure(
            "semantic_candidate_changed",
            "Candidate bytes changed during Semantic Qualification",
        )
    if compute_semantics_project_digest(semantics.root) != semantics.project_digest:
        raise SemanticQualificationFailure(
            "semantic_project_changed",
            "TaskSemantics bytes changed during Semantic Qualification",
        )
    episode_payload = canonical_bytes([item.to_document() for item in episodes])
    evidence_payload = canonical_bytes(
        {
            "candidate_digest": public["candidate_digest"],
            "semantics_digest": semantics.project_digest,
            "public_episode_digest": hashlib.sha256(episode_payload).hexdigest(),
            "native_evidence_digest": native_evidence_digest,
            "capabilities": [item.to_document() for item in evidence],
        }
    )
    return SemanticQualificationReport(
        semantics.project_digest,
        hashlib.sha256(episode_payload).hexdigest(),
        native_evidence_digest,
        hashlib.sha256(evidence_payload).hexdigest(),
        tuple(evidence),
    )


def _require_fresh_replay(
    capability_id: str,
    primary_key: str,
    replay_key: str,
    primary_facts_digest: str,
    replay_facts_digest: str,
) -> None:
    if replay_key != primary_key:
        raise SemanticQualificationFailure(
            "semantic_fresh_replay_mismatch",
            "Fresh replay selected a different semantic referent",
            capability_id=capability_id,
            primary=primary_key,
            replay=replay_key,
        )
    if replay_facts_digest != primary_facts_digest:
        raise SemanticQualificationFailure(
            "semantic_fresh_replay_facts_mismatch",
            "Fresh replay reconstructed different protected business predicates",
            capability_id=capability_id,
            primary=primary_facts_digest,
            replay=replay_facts_digest,
        )


def _preflight_native_oracle(
    transport: _ChildTransport,
    oracle: NativeOracleSession,
    catalog: dict[str, CapabilitySpec],
    cases: tuple[StartCase, ...],
    candidate: Path,
    public: dict[str, Any],
    root: Path,
    config: QualificationConfig,
) -> None:
    reset_schema, _tool_specs = _visibility_inputs(public)
    for capability_id in sorted(catalog):
        capability = catalog[capability_id]
        for start_case in cases:
            instance = root / capability_id / start_case.case_id / "instance"
            actor = _open_candidate_actor(candidate, instance, public, config)
            try:
                reset_observation = actor.reset(start_case.reset_input)
            finally:
                actor.close()
            facts = _readonly_semantic_call(
                transport,
                "inspect",
                {"instance_directory": str(instance)},
                instance,
            )
            raw_bindings = _readonly_semantic_call(
                transport,
                "enumerate_bindings",
                {"capability_id": capability_id, "facts": facts},
                instance,
            )
            if not isinstance(raw_bindings, list):
                raise SemanticQualificationFailure(
                    "semantic_bindings_invalid",
                    "enumerate_bindings must return an array",
                )
            bindings = tuple(binding_from_document(item) for item in raw_bindings)
            _validate_binding_set(capability, bindings)
            for binding in bindings:
                _validate_pre_episode_binding_visibility(
                    capability,
                    binding,
                    reset_observation,
                    reset_schema,
                )
            selected = next((binding for binding in bindings if binding.eligible), None)
            if selected is None:
                continue
            digest = _tree_manifest(instance).digest
            scenario = ConcreteCapabilityScenario(
                capability_id,
                selected.semantic_key,
                "no-op",
                "instance",
                "instance",
                start_case,
                (),
                (),
                None,
                digest,
                digest,
            )
            result = _evaluate_reconciled(
                transport,
                oracle,
                capability,
                scenario,
                selected,
                facts,
                facts,
                instance,
                instance,
                role="no-op",
                action_trace=(),
                final_answer=None,
            )
            if result.satisfied:
                raise SemanticQualificationFailure(
                    "semantic_noop_accepted",
                    "Evaluator accepts a no-op before public capability episodes",
                    capability_id=capability_id,
                    semantic_key=selected.semantic_key,
                )
            return
    raise SemanticQualificationFailure(
        "native_oracle_preflight_unreachable",
        "No qualified StartCase exposes an eligible binding for native-oracle preflight",
    )


def _materialize_capability_episode(
    transport: _ChildTransport,
    catalog: dict[str, CapabilitySpec],
    capability: CapabilitySpec,
    cases: tuple[StartCase, ...],
    candidate: Path,
    public: dict[str, Any],
    root: Path,
    config: QualificationConfig,
    *,
    role: str,
    oracle: NativeOracleSession,
    required_start_case: StartCase | None = None,
    required_semantic_key: str | None = None,
    route: AgentRoute | None,
    client_factory: ClientFactory | None,
) -> tuple[SemanticCapabilityEvidence, _CapabilityMaterialization]:
    root.mkdir(parents=True)
    reset_schema, tool_specs = _visibility_inputs(public)
    eligible_seen = False
    action_failures: list[dict[str, Any]] = []
    selected_cases = (required_start_case,) if required_start_case is not None else cases
    for start_case in selected_cases:
        for attempt in range(2):
            case_root = root / start_case.case_id / f"attempt-{attempt + 1}"
            before_instance = case_root / "before"
            after_instance = case_root / "after"
            before_actor = _open_candidate_actor(candidate, before_instance, public, config)
            after_actor = _open_candidate_actor(candidate, after_instance, public, config)
            try:
                before_reset_observation = before_actor.reset(start_case.reset_input)
                reset_observation = after_actor.reset(start_case.reset_input)
                action_instance_before_digest = _tree_manifest(after_instance).digest
                before_facts = _readonly_semantic_call(
                    transport,
                    "inspect",
                    {"instance_directory": str(before_instance)},
                    before_instance,
                )
                raw_bindings = _readonly_semantic_call(
                    transport,
                    "enumerate_bindings",
                    {"capability_id": capability.capability_id, "facts": before_facts},
                    before_instance,
                )
                if not isinstance(raw_bindings, list):
                    raise SemanticQualificationFailure(
                        "semantic_bindings_invalid",
                        "enumerate_bindings must return an array",
                    )
                bindings = tuple(binding_from_document(item) for item in raw_bindings)
                _validate_binding_set(capability, bindings)
                for binding in bindings:
                    _validate_pre_episode_binding_visibility(
                        capability,
                        binding,
                        reset_observation,
                        reset_schema,
                    )
                eligible = sorted(
                    (binding for binding in bindings if binding.eligible),
                    key=lambda item: item.semantic_key,
                )
                if not eligible:
                    break
                selected_binding = (
                    next(
                        (
                            binding
                            for binding in eligible
                            if binding.semantic_key == required_semantic_key
                        ),
                        None,
                    )
                    if required_semantic_key is not None
                    else eligible[0]
                )
                if selected_binding is None:
                    raise SemanticQualificationFailure(
                        "semantic_fresh_replay_binding_missing",
                        "Fresh replay lost the required semantic binding",
                        capability_id=capability.capability_id,
                        semantic_key=required_semantic_key,
                    )
                eligible_seen = True
                episode = run_public_capability_episode(
                    actor=after_actor,
                    capability=capability,
                    binding=selected_binding,
                    reset_observation=reset_observation,
                    reset_schema=reset_schema,
                    public_documents=_load_public_documents(candidate, public),
                    route=route,
                    client_factory=client_factory,
                    max_provider_turns=config.max_turns,
                )
                _validate_post_episode_binding_set_visibility(
                    capability,
                    bindings,
                    reset_observation,
                    reset_schema,
                    episode.trace,
                    tool_specs,
                )
            finally:
                before_actor.close()
                after_actor.close()
            action_instance_after_digest = _tree_manifest(after_instance).digest
            scenario = ConcreteCapabilityScenario(
                capability.capability_id,
                selected_binding.semantic_key,
                role,
                "before",
                "after",
                start_case,
                (),
                episode.trace,
                episode.final_answer,
                action_instance_before_digest,
                action_instance_after_digest,
            )
            try:
                capability_evidence = _qualify_capability(
                    transport,
                    catalog,
                    scenario,
                    case_root,
                    oracle=oracle,
                )
            except SemanticQualificationFailure as exc:
                if exc.code != "semantic_prompted_binding_rejected":
                    raise
                action_failures.append(
                    {
                        "start_case_id": start_case.case_id,
                        "attempt": attempt + 1,
                        "details": exc.details,
                    }
                )
                continue
            return (
                capability_evidence,
                _CapabilityMaterialization(
                    capability.capability_id,
                    start_case,
                    before_instance,
                    after_instance,
                    before_reset_observation,
                    reset_observation,
                    selected_binding,
                    episode,
                    hashlib.sha256(canonical_bytes(before_facts)).hexdigest(),
                ),
            )
    if eligible_seen:
        raise SemanticQualificationFailure(
            "no_public_capability_witness",
            "No bounded public episode satisfied the frozen capability evaluator",
            capability_id=capability.capability_id,
            attempts=action_failures,
        )
    raise SemanticQualificationFailure(
        "semantic_binding_unreachable",
        "No qualified StartCase exposes an eligible before-state binding",
        capability_id=capability.capability_id,
        owner="semantics",
    )


def _open_candidate_actor(
    candidate: Path,
    instance: Path,
    public: dict[str, Any],
    config: QualificationConfig,
) -> ActorProxy:
    actor_factory = public.get("actor_factory")
    start_schema = public.get("start_schema")
    reset_schema = public.get("reset_observation_schema")
    if (
        not isinstance(actor_factory, str)
        or not isinstance(start_schema, dict)
        or not isinstance(reset_schema, dict)
    ):
        raise SemanticQualificationFailure(
            "semantic_public_surface_invalid",
            "Public surface omits the actor factory or reset schemas",
        )
    python = candidate / ".venv/bin/python"
    if not python.is_file():
        raise SemanticQualificationFailure(
            "semantic_actor_runtime_missing",
            "Candidate actor Python is unavailable",
            path=str(python),
        )
    transport = _ChildTransport(
        python,
        Path(__file__).parent / "_actor_runner.py",
        (actor_factory, str(instance)),
        cwd=candidate,
        timeout=config.command_timeout_seconds,
        role="actor",
    )
    return ActorProxy(
        transport,
        start_schema=cast(JSONObject, start_schema),
        reset_observation_schema=cast(JSONObject, reset_schema),
    )


def _load_public_documents(candidate: Path, public: dict[str, Any]) -> dict[str, str]:
    names = public.get("public_documents")
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise SemanticQualificationFailure(
            "semantic_public_surface_invalid",
            "Public surface public_documents must be a string array",
        )
    root = candidate.resolve()
    documents: dict[str, str] = {}
    total_bytes = 0
    for name in names:
        relative = Path(name)
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise SemanticQualificationFailure(
                "semantic_public_document_invalid",
                "Public document path escapes or is unavailable",
                path=name,
                original_message=str(exc),
            ) from exc
        if relative.is_absolute() or path.is_symlink() or not resolved.is_file():
            raise SemanticQualificationFailure(
                "semantic_public_document_invalid",
                "Public document must be a regular release-relative file",
                path=name,
            )
        payload = resolved.read_bytes()
        total_bytes += len(payload)
        if len(payload) > 256_000 or total_bytes > 512_000:
            raise SemanticQualificationFailure(
                "semantic_public_document_too_large",
                "Public episode documents exceed the bounded context budget",
                path=name,
                file_bytes=len(payload),
                total_bytes=total_bytes,
            )
        try:
            documents[name] = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SemanticQualificationFailure(
                "semantic_public_document_invalid",
                "Public episode documents must be UTF-8 text",
                path=name,
            ) from exc
    return documents


def _materialize_physical_wrong_target(
    transport: _ChildTransport,
    capability: CapabilitySpec,
    positive: _CapabilityMaterialization,
    candidate: Path,
    public: dict[str, Any],
    root: Path,
    config: QualificationConfig,
    *,
    oracle: NativeOracleSession,
    route: AgentRoute | None,
    client_factory: ClientFactory | None,
) -> tuple[bool, _CapabilityMaterialization | None]:
    if capability.task_kind == "query":
        return False, None
    reset_schema, tool_specs = _visibility_inputs(public)
    before_instance = root / "before"
    after_instance = root / "after"
    before_actor = _open_candidate_actor(candidate, before_instance, public, config)
    after_actor = _open_candidate_actor(candidate, after_instance, public, config)
    try:
        before_reset = before_actor.reset(positive.start_case.reset_input)
        after_reset = after_actor.reset(positive.start_case.reset_input)
        before_facts = _readonly_semantic_call(
            transport,
            "inspect",
            {"instance_directory": str(before_instance)},
            before_instance,
        )
        raw_bindings = _readonly_semantic_call(
            transport,
            "enumerate_bindings",
            {"capability_id": capability.capability_id, "facts": before_facts},
            before_instance,
        )
        if not isinstance(raw_bindings, list):
            raise SemanticQualificationFailure(
                "semantic_bindings_invalid",
                "enumerate_bindings must return an array",
            )
        bindings = tuple(binding_from_document(item) for item in raw_bindings)
        _validate_binding_set(capability, bindings)
        for binding in bindings:
            _validate_pre_episode_binding_visibility(
                capability,
                binding,
                after_reset,
                reset_schema,
            )
        selected = next(
            (
                binding
                for binding in bindings
                if binding.semantic_key == positive.selected_binding.semantic_key
            ),
            None,
        )
        if selected is None:
            raise SemanticQualificationFailure(
                "semantic_selected_binding_missing",
                "Fresh wrong-target materialization lost the selected binding",
                capability_id=capability.capability_id,
            )
        alternatives = sorted(
            (
                binding
                for binding in bindings
                if binding.eligible and binding.semantic_key != selected.semantic_key
            ),
            key=lambda item: item.semantic_key,
        )
        if not alternatives:
            return False, None
        alternative = alternatives[0]
        episode = run_public_capability_episode(
            actor=after_actor,
            capability=capability,
            binding=alternative,
            reset_observation=after_reset,
            reset_schema=reset_schema,
            public_documents=_load_public_documents(candidate, public),
            route=route,
            client_factory=client_factory,
            max_provider_turns=config.max_turns,
        )
        _validate_post_episode_binding_set_visibility(
            capability,
            bindings,
            after_reset,
            reset_schema,
            episode.trace,
            tool_specs,
        )
    finally:
        before_actor.close()
        after_actor.close()
    after_facts = _readonly_semantic_call(
        transport,
        "inspect",
        {"instance_directory": str(after_instance)},
        after_instance,
    )
    scenario = ConcreteCapabilityScenario(
        capability.capability_id,
        selected.semantic_key,
        "wrong-target",
        "before",
        "after",
        positive.start_case,
        (),
        episode.trace,
        episode.final_answer,
        _tree_manifest(before_instance).digest,
        _tree_manifest(after_instance).digest,
    )
    wrong = _evaluate_reconciled(
        transport,
        oracle,
        capability,
        scenario,
        selected,
        before_facts,
        after_facts,
        before_instance,
        after_instance,
        role="wrong-target",
    )
    if wrong.satisfied:
        raise SemanticQualificationFailure(
            "semantic_physical_wrong_target_accepted",
            "Evaluator accepts a real action performed on another eligible target",
            selected=selected.semantic_key,
            wrong_target=alternative.semantic_key,
        )
    return (
        True,
        _CapabilityMaterialization(
            capability.capability_id,
            positive.start_case,
            before_instance,
            after_instance,
            before_reset,
            after_reset,
            alternative,
            episode,
            hashlib.sha256(canonical_bytes(before_facts)).hexdigest(),
        ),
    )


def _semantic_start_limit(public: dict[str, Any]) -> int:
    starts = {
        canonical_bytes(item.get("arguments", {}).get("start"))
        for item in public.get("public_probe_facts", [])
        if isinstance(item, dict)
        and item.get("operation") == "reset"
        and isinstance(item.get("arguments"), dict)
    }
    return max(4, len(starts))


def _validate_public_surface_schema_evidence(public: dict[str, Any]) -> None:
    reset_schema = public.get("reset_observation_schema")
    raw_specs = public.get("tool_specs")
    facts = public.get("public_probe_facts")
    if (
        not isinstance(reset_schema, dict)
        or not isinstance(raw_specs, list)
        or not isinstance(facts, list)
    ):
        raise SemanticQualificationFailure(
            "semantic_public_surface_invalid",
            "Public surface omits reset schema, ToolSpecs, or public probe facts",
        )
    tool_schemas: dict[str, dict[str, Any]] = {}
    for item in raw_specs:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        output_schema = item.get("output_schema")
        if isinstance(name, str) and isinstance(output_schema, dict):
            tool_schemas[name] = output_schema
    findings: list[dict[str, Any]] = []
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            continue
        operation = fact.get("operation")
        result = fact.get("result")
        if operation == "reset":
            gaps = _explicit_schema_gaps(result, reset_schema)
            if gaps:
                findings.append(
                    {
                        "fact_index": index,
                        "operation": "reset",
                        "missing_paths": _path_shapes(gaps),
                        "missing_leaf_count": len(gaps),
                    }
                )
            continue
        if operation != "invoke" or not isinstance(result, dict) or result.get("ok") is not True:
            continue
        arguments = fact.get("arguments")
        tool_name = arguments.get("tool_name") if isinstance(arguments, dict) else None
        schema = tool_schemas.get(tool_name) if isinstance(tool_name, str) else None
        if schema is None:
            findings.append(
                {
                    "fact_index": index,
                    "operation": "invoke",
                    "tool_name": tool_name,
                    "missing_paths": ["$"],
                }
            )
            continue
        gaps = _explicit_schema_gaps(result.get("data"), schema)
        if gaps:
            findings.append(
                {
                    "fact_index": index,
                    "operation": "invoke",
                    "tool_name": tool_name,
                    "missing_paths": _path_shapes(gaps),
                    "missing_leaf_count": len(gaps),
                }
            )
    if findings:
        raise SemanticQualificationFailure(
            "semantic_public_schema_incomplete",
            "Published schemas must explicitly describe every observed public leaf",
            findings=findings,
            owner="environment",
        )


def _explicit_schema_gaps(instance: Any, schema: dict[str, Any]) -> list[str]:
    return [
        _json_pointer(path)
        for path in _leaf_paths(instance)
        if not _schema_covers_path(schema, schema, instance, path, frozenset())
    ]


def _path_shapes(paths: list[str]) -> list[str]:
    return sorted(
        {"/".join("*" if token.isdigit() else token for token in path.split("/")) for path in paths}
    )


def _leaf_paths(
    value: Any, prefix: tuple[str | int, ...] = ()
) -> tuple[tuple[str | int, ...], ...]:
    if isinstance(value, dict):
        if not value:
            return (prefix,)
        return tuple(
            path for key in sorted(value) for path in _leaf_paths(value[key], (*prefix, key))
        )
    if isinstance(value, list):
        if not value:
            return (prefix,)
        return tuple(
            path for index, item in enumerate(value) for path in _leaf_paths(item, (*prefix, index))
        )
    return (prefix,)


def _schema_covers_path(
    root: dict[str, Any],
    schema: dict[str, Any],
    instance: Any,
    path: tuple[str | int, ...],
    seen_refs: frozenset[str],
) -> bool:
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#") and reference not in seen_refs:
        target = _resolve_local_schema_reference(root, reference)
        if target is not None and _schema_covers_path(
            root, target, instance, path, seen_refs | {reference}
        ):
            return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            try:
                validate_instance(instance, branch, role=f"public schema {keyword} branch")
            except SchemaError:
                continue
            if _schema_covers_path(root, branch, instance, path, seen_refs):
                return True
    local = {
        key: value
        for key, value in schema.items()
        if key not in {"$ref", "allOf", "anyOf", "oneOf"}
    }
    if not path:
        return any(
            key in local
            for key in (
                "type",
                "const",
                "enum",
                "pattern",
                "format",
                "minimum",
                "maximum",
                "minLength",
                "maxLength",
                "properties",
                "items",
            )
        )
    head, *tail = path
    remaining = tuple(tail)
    if isinstance(head, str) and isinstance(instance, dict) and head in instance:
        properties = local.get("properties")
        child = properties.get(head) if isinstance(properties, dict) else None
        if not isinstance(child, dict):
            patterns = local.get("patternProperties")
            if isinstance(patterns, dict):
                child = next(
                    (
                        candidate
                        for pattern, candidate in patterns.items()
                        if isinstance(candidate, dict) and re.search(pattern, head)
                    ),
                    None,
                )
        if not isinstance(child, dict):
            additional = local.get("additionalProperties")
            child = additional if isinstance(additional, dict) else None
        return isinstance(child, dict) and _schema_covers_path(
            root, child, instance[head], remaining, seen_refs
        )
    if isinstance(head, int) and isinstance(instance, list) and 0 <= head < len(instance):
        prefix_items = local.get("prefixItems")
        array_child: Any = None
        if isinstance(prefix_items, list) and head < len(prefix_items):
            array_child = prefix_items[head]
        if not isinstance(array_child, dict):
            array_child = local.get("items")
        return isinstance(array_child, dict) and _schema_covers_path(
            root, array_child, instance[head], remaining, seen_refs
        )
    return False


def _resolve_local_schema_reference(
    root: dict[str, Any],
    reference: str,
) -> dict[str, Any] | None:
    if reference == "#":
        return root
    if not reference.startswith("#/"):
        return None
    node: Any = root
    for raw in reference[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            return None
        node = node[token]
    return node if isinstance(node, dict) else None


def _json_pointer(path: tuple[str | int, ...]) -> str:
    if not path:
        return ""
    return "/" + "/".join(str(item).replace("~", "~0").replace("/", "~1") for item in path)


def _schema_valid_wrong_answer(
    spec: CapabilitySpec,
    answer: JSONValue | None,
) -> JSONObject:
    if not isinstance(answer, dict):
        raise SemanticQualificationFailure(
            "semantic_answer_not_challengeable",
            "Declared answer fields require a structured positive final answer",
            capability_id=spec.capability_id,
        )
    expected_fields = {field.field_id for field in spec.answer_fields}
    if set(answer) != expected_fields:
        raise SemanticQualificationFailure(
            "semantic_answer_not_challengeable",
            "Positive final answer does not exactly match the declared answer fields",
            capability_id=spec.capability_id,
            expected=sorted(expected_fields),
            actual=sorted(answer),
        )
    for field in spec.answer_fields:
        original = answer[field.field_id]
        declared = field.schema.get("enum")
        schema_candidates: tuple[JSONValue, ...] = (
            tuple(declared) if isinstance(declared, list) else ()
        )
        for candidate in (*schema_candidates, *_different_json_values(original)):
            if canonical_bytes(candidate) == canonical_bytes(original):
                continue
            try:
                validate_instance(
                    candidate,
                    field.schema,
                    role=f"wrong-answer candidate {field.field_id!r}",
                )
            except SchemaError:
                continue
            mutated = cast(JSONObject, json.loads(json.dumps(answer)))
            mutated[field.field_id] = candidate
            return mutated
    raise SemanticQualificationFailure(
        "semantic_answer_not_challengeable",
        "No distinct schema-valid wrong answer can be constructed",
        capability_id=spec.capability_id,
    )


def _different_json_values(value: JSONValue) -> tuple[JSONValue, ...]:
    if isinstance(value, bool):
        return (not value,)
    if isinstance(value, int):
        return (value + 1, value - 1, 0)
    if isinstance(value, float):
        return (value + 1.0, value - 1.0, 0.0)
    if isinstance(value, str):
        return (
            f"{value}__wrong__",
            "__wrong__",
            "",
            "2000-01-01T00:00:00Z",
            "2100-01-01T00:00:00Z",
        )
    if isinstance(value, list):
        candidates: list[JSONValue] = [[], [*value, None]]
        if value:
            candidates.append(value[:-1])
            for replacement in _different_json_values(value[0]):
                candidates.append([replacement, *value[1:]])
        return tuple(candidates)
    if isinstance(value, dict):
        candidates = [{}]
        for key in sorted(value):
            for replacement in _different_json_values(value[key]):
                candidate = cast(JSONObject, json.loads(json.dumps(value)))
                candidate[key] = replacement
                candidates.append(candidate)
        return tuple(candidates)
    return ("__wrong__", 0, False, {}, [])


def _visibility_inputs(
    public: dict[str, Any],
) -> tuple[dict[str, Any], tuple[ToolSpec, ...]]:
    return (
        cast(dict[str, Any], public["reset_observation_schema"]),
        cast(tuple[ToolSpec, ...], tuple(public["tool_specs"])),
    )


def _validate_binding_set(
    spec: CapabilitySpec,
    bindings: tuple[BindingCandidate, ...],
) -> None:
    for binding in bindings:
        validate_binding(spec, binding)
    public_owners: dict[bytes, str] = {}
    for candidate in bindings:
        public_bytes = canonical_bytes(candidate.public_document())
        previous = public_owners.setdefault(public_bytes, candidate.semantic_key)
        if previous != candidate.semantic_key:
            raise SemanticQualificationFailure(
                "semantic_public_binding_ambiguous",
                "Different semantic bindings expose the same public binding document",
                capability_id=spec.capability_id,
                semantic_keys=sorted((previous, candidate.semantic_key)),
                public_binding=candidate.public_document(),
            )
    nonliteral_owners: dict[bytes, str] = {}
    task_literal_names = {facet.name for facet in spec.facets if facet.visibility == "task_literal"}
    for candidate in bindings:
        identity = {
            "public_descriptor": candidate.public_descriptor,
            "facets": {
                name: value
                for name, value in candidate.facets.items()
                if name not in task_literal_names
            },
        }
        identity_bytes = canonical_bytes(identity)
        previous = nonliteral_owners.setdefault(identity_bytes, candidate.semantic_key)
        if previous != candidate.semantic_key:
            raise SemanticQualificationFailure(
                "semantic_task_literal_identity_ambiguous",
                "Task-literal facets cannot be the only public binding discriminator",
                capability_id=spec.capability_id,
                semantic_keys=sorted((previous, candidate.semantic_key)),
                nonliteral_identity=identity,
            )


def _validate_pre_episode_binding_visibility(
    spec: CapabilitySpec,
    binding: BindingCandidate,
    reset_observation: JSONValue,
    reset_schema: dict[str, Any],
) -> None:
    _raise_binding_visibility_findings(
        spec,
        binding,
        _pre_episode_binding_visibility_findings(
            spec,
            binding,
            reset_observation,
            reset_schema,
        ),
    )


def _pre_episode_binding_visibility_findings(
    spec: CapabilitySpec,
    binding: BindingCandidate,
    reset_observation: JSONValue,
    reset_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    descriptor_values = _leaf_value_digests(binding.public_descriptor)
    reset_values = _schema_qualified_value_digests(reset_observation, reset_schema)
    if not descriptor_values:
        findings.append({"path": "public_descriptor", "reason": "empty"})
    for path, digest in descriptor_values.items():
        if digest not in reset_values:
            findings.append(
                {
                    "path": f"public_descriptor{path}",
                    "reason": "value_absent_from_current_reset",
                }
            )
    facet_specs = {facet.name: facet for facet in spec.facets}
    for name, value in binding.facets.items():
        facet = facet_specs[name]
        if facet.visibility != "reset":
            continue
        candidate = _schema_qualified_value_at_pointer(
            reset_observation,
            reset_schema,
            facet.output_schema_pointer or "",
        )
        if candidate is _MISSING or canonical_bytes(candidate) != canonical_bytes(value):
            findings.append({"path": f"facets/{name}", "reason": "value_absent_from_reset_path"})
    return findings


def _validate_post_episode_binding_visibility(
    spec: CapabilitySpec,
    binding: BindingCandidate,
    reset_observation: JSONValue,
    reset_schema: dict[str, Any],
    trace: tuple[TraceEvent, ...],
    tool_specs: tuple[ToolSpec, ...],
) -> None:
    findings = _pre_episode_binding_visibility_findings(
        spec,
        binding,
        reset_observation,
        reset_schema,
    )
    reset_values = _schema_qualified_value_digests(reset_observation, reset_schema)
    tool_schemas = {tool["name"]: tool["output_schema"] for tool in tool_specs}
    trace_values: dict[bytes, int] = {}
    argument_values: dict[bytes, int] = {}
    for event in trace:
        for digest in _leaf_value_digests(event.arguments).values():
            argument_values.setdefault(digest, event.seq)
        observation = event.observation
        schema = tool_schemas.get(event.tool_name)
        if observation.get("ok") is not True or not isinstance(schema, dict):
            continue
        for digest in _schema_qualified_value_digests(observation.get("data"), schema):
            trace_values.setdefault(digest, event.seq)

    facet_specs = {facet.name: facet for facet in spec.facets}
    for name, value in binding.facets.items():
        facet = facet_specs[name]
        if facet.visibility != "public_tool":
            continue
        facet_observed_at: int | None = None
        schema = tool_schemas.get(facet.tool_name or "")
        if isinstance(schema, dict):
            for event in trace:
                if event.tool_name != facet.tool_name or event.observation.get("ok") is not True:
                    continue
                candidate = _schema_qualified_value_at_pointer(
                    event.observation.get("data"),
                    schema,
                    facet.output_schema_pointer or "",
                )
                if candidate is not _MISSING and canonical_bytes(candidate) == canonical_bytes(
                    value
                ):
                    facet_observed_at = event.seq
                    break
        if facet_observed_at is None:
            findings.append(
                {"path": f"facets/{name}", "reason": "value_absent_from_current_tool_path"}
            )
            continue
        facet_digests = set(_leaf_value_digests(value).values())
        if any(
            (argument_at := argument_values.get(digest)) is not None
            and argument_at <= facet_observed_at
            and digest not in reset_values
            and trace_values.get(digest, facet_observed_at + 1) >= argument_at
            for digest in facet_digests
        ):
            findings.append({"path": f"facets/{name}", "reason": "value_laundered_from_argument"})
    _raise_binding_visibility_findings(spec, binding, findings)


def _validate_post_episode_binding_set_visibility(
    spec: CapabilitySpec,
    bindings: tuple[BindingCandidate, ...],
    reset_observation: JSONValue,
    reset_schema: dict[str, Any],
    trace: tuple[TraceEvent, ...],
    tool_specs: tuple[ToolSpec, ...],
) -> None:
    for binding in bindings:
        _validate_post_episode_binding_visibility(
            spec,
            binding,
            reset_observation,
            reset_schema,
            trace,
            tool_specs,
        )


def _raise_binding_visibility_findings(
    spec: CapabilitySpec,
    binding: BindingCandidate,
    findings: list[dict[str, Any]],
) -> None:
    if findings:
        raise SemanticQualificationFailure(
            "semantic_public_binding_hidden",
            "Every public binding value must be publicly discoverable",
            capability_id=spec.capability_id,
            semantic_key=binding.semantic_key,
            findings=findings,
        )


_MISSING = object()


def _leaf_value_digests(value: Any, prefix: tuple[str | int, ...] = ()) -> dict[str, bytes]:
    if isinstance(value, dict):
        return {
            path: digest
            for key in sorted(value)
            for path, digest in _leaf_value_digests(value[key], (*prefix, key)).items()
        }
    if isinstance(value, list):
        return {
            path: digest
            for index, item in enumerate(value)
            for path, digest in _leaf_value_digests(item, (*prefix, index)).items()
        }
    return {_json_pointer(prefix): hashlib.sha256(canonical_bytes(value)).digest()}


def _value_at_path(value: Any, path: tuple[str | int, ...]) -> Any:
    node = value
    for token in path:
        if isinstance(token, str) and isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(token, int) and isinstance(node, list) and token < len(node):
            node = node[token]
        else:
            return _MISSING
    return node


def _schema_qualified_value_digests(value: Any, schema: dict[str, Any]) -> set[bytes]:
    return {
        hashlib.sha256(canonical_bytes(candidate)).digest()
        for path in _leaf_paths(value)
        if _schema_covers_path(schema, schema, value, path, frozenset())
        and (candidate := _value_at_path(value, path)) is not _MISSING
    }


def _schema_qualified_value_at_pointer(
    value: Any,
    schema: dict[str, Any],
    pointer: str,
) -> Any:
    if pointer == "":
        path: tuple[str | int, ...] = ()
    elif not pointer.startswith("/"):
        return _MISSING
    else:
        node = value
        tokens: list[str | int] = []
        for raw in pointer[1:].split("/"):
            token = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and token in node:
                tokens.append(token)
                node = node[token]
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                index = int(token)
                tokens.append(index)
                node = node[index]
            else:
                return _MISSING
        path = tuple(tokens)
    if not _schema_covers_path(schema, schema, value, path, frozenset()):
        return _MISSING
    return _value_at_path(value, path)


def _value_at_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        return _MISSING
    node = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
            continue
        if isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
            continue
        return _MISSING
    return node


def _qualify_capability(
    transport: _ChildTransport,
    catalog: dict[str, CapabilitySpec],
    scenario: ConcreteCapabilityScenario,
    instances_root: Path,
    *,
    oracle: NativeOracleSession,
) -> SemanticCapabilityEvidence:
    spec = catalog.get(scenario.capability_id)
    if spec is None:
        raise SemanticQualificationFailure(
            "semantic_capability_missing",
            "Scenario capability is absent from generated catalog",
        )
    before_instance = instances_root / scenario.before_instance
    after_instance = instances_root / scenario.after_instance
    before_facts = _readonly_semantic_call(
        transport,
        "inspect",
        {"instance_directory": str(before_instance)},
        before_instance,
    )
    after_facts = _readonly_semantic_call(
        transport,
        "inspect",
        {"instance_directory": str(after_instance)},
        after_instance,
    )
    if (
        spec.task_kind == "query"
        and scenario.action_instance_before_digest != scenario.action_instance_after_digest
    ):
        raise SemanticQualificationFailure(
            "semantic_query_mutated_state",
            "A public query episode mutated its native actor instance",
            capability_id=scenario.capability_id,
            before_digest=scenario.action_instance_before_digest,
            after_digest=scenario.action_instance_after_digest,
        )
    raw_bindings = _readonly_semantic_call(
        transport,
        "enumerate_bindings",
        {"capability_id": scenario.capability_id, "facts": before_facts},
        before_instance,
    )
    if not isinstance(raw_bindings, list):
        raise SemanticQualificationFailure(
            "semantic_bindings_invalid",
            "enumerate_bindings must return an array",
        )
    bindings = tuple(binding_from_document(item) for item in raw_bindings)
    _validate_binding_set(spec, bindings)
    eligible = [binding for binding in bindings if binding.eligible]
    if not eligible:
        after_bindings = _readonly_semantic_call(
            transport,
            "enumerate_bindings",
            {"capability_id": scenario.capability_id, "facts": after_facts},
            after_instance,
        )
        raise SemanticQualificationFailure(
            "semantic_binding_unreachable",
            "Scenario setup produced no eligible before-state binding",
            owner="scenario"
            if isinstance(after_bindings, list) and after_bindings
            else "semantics",
        )

    binding = next(
        (item for item in eligible if item.semantic_key == scenario.selected_semantic_key),
        None,
    )
    if binding is None:
        raise SemanticQualificationFailure(
            "semantic_prompted_binding_missing",
            "The publicly prompted binding is absent or ineligible in the before state",
            capability_id=scenario.capability_id,
            semantic_key=scenario.selected_semantic_key,
        )
    action_result = _evaluate_reconciled(
        transport,
        oracle,
        spec,
        scenario,
        binding,
        before_facts,
        after_facts,
        before_instance,
        after_instance,
        role=scenario.role,
    )
    if not action_result.satisfied:
        raise SemanticQualificationFailure(
            "semantic_prompted_binding_rejected",
            "The evaluator rejected the exact publicly prompted binding",
            owner="unresolved_semantics_or_scenario",
            semantic_key=binding.semantic_key,
            result=action_result.to_document(),
            action_trace=[item.to_document() for item in scenario.action_trace],
            final_answer=scenario.final_answer,
        )
    _validate_answer_reports(spec, action_result)
    wrong_answer_checked = False
    if spec.answer_fields:
        if action_result.answer_ok is not True:
            raise SemanticQualificationFailure(
                "semantic_answer_not_grounded",
                "A satisfied capability with declared answer fields must return answer_ok=true",
                capability_id=scenario.capability_id,
                result=action_result.to_document(),
            )
        wrong_answer = _schema_valid_wrong_answer(spec, scenario.final_answer)
        wrong_result = _evaluate_reconciled(
            transport,
            oracle,
            spec,
            scenario,
            binding,
            before_facts,
            after_facts,
            before_instance,
            after_instance,
            role="wrong-answer",
            final_answer=wrong_answer,
        )
        if wrong_result.satisfied or wrong_result.answer_ok is not False:
            raise SemanticQualificationFailure(
                "semantic_wrong_answer_accepted",
                "The evaluator accepted a schema-valid wrong answer",
                capability_id=scenario.capability_id,
                correct_answer=scenario.final_answer,
                wrong_answer=wrong_answer,
                result=wrong_result.to_document(),
            )
        wrong_answer_checked = True
    process_challenge_checked = False
    if spec.task_kind == "process":
        process_violation = _evaluate_reconciled(
            transport,
            oracle,
            spec,
            scenario,
            binding,
            before_facts,
            after_facts,
            before_instance,
            after_instance,
            role="process-violation",
            action_trace=(),
        )
        if process_violation.satisfied or process_violation.process_ok is not False:
            raise SemanticQualificationFailure(
                "semantic_process_violation_accepted",
                "The evaluator accepts the same terminal state without the public process",
                capability_id=scenario.capability_id,
                result=process_violation.to_document(),
            )
        process_challenge_checked = True
    no_op = _evaluate_reconciled(
        transport,
        oracle,
        spec,
        scenario,
        binding,
        before_facts,
        before_facts,
        before_instance,
        before_instance,
        role="no-op",
        action_trace=(),
        final_answer=None,
    )
    if no_op.satisfied:
        raise SemanticQualificationFailure(
            "semantic_noop_accepted",
            "Evaluator accepts a no-op before state",
            semantic_key=binding.semantic_key,
        )
    wrong_target_checked = False
    wrong_target_not_applicable_reason: str | None = None
    if spec.task_kind == "query":
        wrong_target_not_applicable_reason = "query read may validly cover multiple bindings"
    else:
        for alternative in eligible:
            if alternative.semantic_key == binding.semantic_key:
                continue
            wrong_target_checked = True
            wrong = _evaluate_reconciled(
                transport,
                oracle,
                spec,
                scenario,
                alternative,
                before_facts,
                after_facts,
                before_instance,
                after_instance,
                role="wrong-target",
            )
            if wrong.satisfied:
                raise SemanticQualificationFailure(
                    "semantic_wrong_target_accepted",
                    "Evaluator accepts the action for another eligible binding",
                    selected=binding.semantic_key,
                    wrong_target=alternative.semantic_key,
                )
    return SemanticCapabilityEvidence(
        scenario.capability_id,
        binding.semantic_key,
        action_result,
        no_op,
        wrong_target_checked,
        wrong_target_not_applicable_reason,
        wrong_answer_checked,
        process_challenge_checked,
    )


def _evaluate(
    transport: _ChildTransport,
    spec: CapabilitySpec,
    scenario: ConcreteCapabilityScenario,
    binding: BindingCandidate,
    before_facts: JSONValue,
    after_facts: JSONValue,
    instance: Path,
    *,
    action_trace: tuple[TraceEvent, ...] | None = None,
    final_answer: JSONValue | None | object = ...,
) -> AtomCheckResult:
    request = AtomCheckRequest(
        scenario.capability_id,
        before_facts,
        after_facts,
        binding.protected_binding,
        scenario.action_trace if action_trace is None else action_trace,
        scenario.final_answer if final_answer is ... else cast(JSONValue | None, final_answer),
    )
    raw = _readonly_semantic_call(
        transport,
        "evaluate_atom",
        {"request": request.to_document()},
        instance,
    )
    try:
        return atom_result_from_document(raw)
    except Exception as exc:
        raise SemanticQualificationFailure(
            "semantic_evaluator_invalid",
            "evaluate_atom returned an invalid result",
            original_message=str(exc),
        ) from exc


def _evaluate_reconciled(
    transport: _ChildTransport,
    oracle: NativeOracleSession,
    spec: CapabilitySpec,
    scenario: ConcreteCapabilityScenario,
    binding: BindingCandidate,
    before_facts: JSONValue,
    after_facts: JSONValue,
    before_instance: Path,
    after_instance: Path,
    *,
    role: str,
    action_trace: tuple[TraceEvent, ...] | None = None,
    final_answer: JSONValue | None | object = ...,
) -> AtomCheckResult:
    selected_trace = scenario.action_trace if action_trace is None else action_trace
    selected_answer = (
        scenario.final_answer if final_answer is ... else cast(JSONValue | None, final_answer)
    )
    result = _evaluate(
        transport,
        spec,
        scenario,
        binding,
        before_facts,
        after_facts,
        after_instance,
        action_trace=selected_trace,
        final_answer=selected_answer,
    )
    try:
        native = oracle.check_atom(
            role=role,
            capability=spec,
            start_case=scenario.start_case,
            before_instance=before_instance,
            after_instance=after_instance,
            public_binding=binding.public_document(),
            trace=selected_trace,
            final_answer=selected_answer,
        )
    except NativeOracleFailure as exc:
        raise SemanticQualificationFailure(
            exc.code,
            str(exc),
            **{key: value for key, value in exc.details.items() if key != "phase"},
        ) from exc
    _require_native_agreement(spec, result, native)
    return result


def _require_native_agreement(
    spec: CapabilitySpec,
    semantic: AtomCheckResult,
    native: NativeAtomEvidence,
) -> None:
    native_result = native.atom_result
    semantic_axes = (
        semantic.initially_satisfied,
        semantic.satisfied,
        semantic.required_effects_ok,
        semantic.collateral_ok,
        semantic.answer_ok,
        semantic.process_ok,
        canonical_bytes(semantic.report_values),
    )
    native_axes = (
        native_result.initially_satisfied,
        native_result.satisfied,
        native_result.required_effects_ok,
        native_result.collateral_ok,
        native_result.answer_ok,
        native_result.process_ok,
        canonical_bytes(native_result.report_values),
    )
    if semantic_axes != native_axes:
        raise SemanticQualificationFailure(
            "semantic_native_disagreement",
            "TaskSemantics disagrees with the independent native oracle",
            capability_id=spec.capability_id,
            materialization_id=native.materialization_id,
            semantic=semantic.to_document(),
            native=native_result.to_document(),
            request_digest=native.request_digest,
            result_digest=native.result_digest,
        )


def _readonly_semantic_call(
    transport: _ChildTransport,
    operation: str,
    arguments: JSONObject,
    instance: Path,
) -> JSONValue:
    before = _tree_manifest(instance)
    try:
        value = transport.call(operation, arguments)
    except Exception as exc:
        raise SemanticQualificationFailure(
            "semantic_call_failed",
            f"Semantics {operation} failed",
            original_code=type(exc).__name__,
            original_message=str(exc),
        ) from exc
    after = _tree_manifest(instance)
    if before.digest != after.digest:
        raise SemanticQualificationFailure(
            "semantic_state_mutation",
            f"Semantics {operation} mutated the actor instance",
        )
    return value


def _validate_answer_reports(spec: CapabilitySpec, result: AtomCheckResult) -> None:
    if not spec.answer_fields:
        return
    missing = [
        field.field_id for field in spec.answer_fields if field.field_id not in result.report_values
    ]
    if missing:
        raise SemanticQualificationFailure(
            "semantic_answer_report_missing",
            "Evaluator omitted declared answer report fields",
            missing=missing,
        )
    for field in spec.answer_fields:
        try:
            validate_instance(
                result.report_values[field.field_id],
                field.schema,
                role=f"semantic answer {field.field_id!r}",
            )
        except SchemaError as exc:
            raise SemanticQualificationFailure(
                "semantic_answer_report_invalid",
                "Evaluator answer report does not match its schema",
                field_id=field.field_id,
                original_message=str(exc),
            ) from exc


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticQualificationFailure(
            "semantic_scenario_input_invalid",
            f"Cannot read {path.name}",
            original_message=str(exc),
        ) from exc
    if not isinstance(value, dict):
        raise SemanticQualificationFailure(
            "semantic_scenario_input_invalid",
            f"{path.name} must be a JSON object",
        )
    return cast(dict[str, Any], value)
