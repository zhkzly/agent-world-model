"""Host-owned physical conformance for one frozen v3 actor project."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agent_env_foundry.builder import (
    ACTOR_FACTORY,
    STATE_READER_FACTORY,
    CandidateBuild,
)
from agent_env_foundry.conformance_v3 import (
    EnvironmentConformanceReceipt,
    make_conformance_receipt,
)
from agent_env_foundry.diagnostic_scenarios import (
    DIAGNOSTIC_SCENARIOS_PATH,
    DiagnosticContractError,
    DiagnosticScenario,
    DiagnosticSuite,
    parse_diagnostic_suite,
)
from agent_env_foundry.environment import JSONObject, JSONValue, ToolObservation, ToolSpec
from agent_env_foundry.environment_semantic_qualification import (
    SemanticQualification,
    make_qualified_conformance_evidence,
)
from agent_env_foundry.physical_runtime import (
    ActorProxy,
    PreparationExecutionError,
    PreparationSettings,
    ProjectMaterializationInput,
    RuntimeLock,
    StateSnapshotEvent,
    StateSnapshotProxy,
    _ChildTransport,
    materialize_project,
)
from agent_env_foundry.project_identity import compute_authored_project_digest
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.research import BuilderProjection
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_schema_document,
)

_EXPECTED_BUILDER_PHASES = (
    "lock",
    "sync",
    "build",
    "tests",
    "public_contract",
    "source_determinism",
    "live_contract",
)
_FORBIDDEN_ACTOR_MODULES = ("agent_env_foundry",)


@dataclass(frozen=True, slots=True)
class ConformedEnvironmentV3:
    receipt: EnvironmentConformanceReceipt
    evidence: JSONObject
    start_schema: JSONObject
    reset_observation_schema: JSONObject
    state_schema: JSONObject
    tool_specs: tuple[ToolSpec, ...]
    diagnostic_evidence: tuple[JSONObject, ...]


def run_environment_conformance_v3_internal(
    candidate: CandidateBuild,
    runtime_root: Path,
    *,
    settings: PreparationSettings,
) -> ConformedEnvironmentV3:
    """Execute task-neutral Host checks and issue one receipt over exact evidence."""

    actor_root = Path(candidate.workspace)
    phases = tuple(item.phase for item in candidate.checks)
    base_checks = candidate.checks[: len(_EXPECTED_BUILDER_PHASES)]
    trailing_checks = candidate.checks[len(_EXPECTED_BUILDER_PHASES) :]
    if (
        tuple(item.phase for item in base_checks) != _EXPECTED_BUILDER_PHASES
        or not all(item.passed for item in base_checks)
        or (
            trailing_checks
            and (
                len(trailing_checks) != 1
                or trailing_checks[0].phase != "semantic_qualification"
                or not trailing_checks[0].passed
            )
        )
    ):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "builder_evidence_incomplete",
            "v3 conformance requires the complete passing Builder check sequence",
            expected=list(_EXPECTED_BUILDER_PHASES),
            actual=list(phases),
        )
    actor_digest = compute_authored_project_digest(
        actor_root,
        "actor",
        require_locked_project=True,
    )
    if actor_digest != candidate.candidate_digest:
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "builder_identity_drift",
            "actor bytes changed after Builder acceptance",
            expected=candidate.candidate_digest,
            actual=actor_digest,
        )
    start = _schema(actor_root / "docs/schemas/start.json", "start schema", object_root=True)
    reset = _schema(actor_root / "docs/schemas/reset.json", "reset schema")
    state = _schema(actor_root / "docs/schemas/state.json", "state schema")
    runtime = materialize_project(
        ProjectMaterializationInput(
            actor_root,
            actor_digest,
            "generated_environment",
            _FORBIDDEN_ACTOR_MODULES,
            "actor",
        ),
        Path(runtime_root),
        settings=settings,
    )
    instance_a = Path(runtime_root) / "conformance-instance-a"
    instance_b = Path(runtime_root) / "conformance-instance-b"
    reset_a, tools = _reset_candidate(runtime, instance_a, start, reset, settings)
    state_a, state_a_events = _read_candidate_state(runtime, instance_a, state, settings)
    _reopen_candidate(runtime, instance_a, start, reset, settings)
    reopened_state, reopen_events = _read_candidate_state(runtime, instance_a, state, settings)
    if canonical_bytes(reopened_state) != canonical_bytes(state_a):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "state_reopen_drift",
            "actor state changed across close/reopen without a public mutation",
        )
    reset_b, tools_b = _reset_candidate(runtime, instance_b, start, reset, settings)
    state_b, state_b_events = _read_candidate_state(runtime, instance_b, state, settings)
    if canonical_bytes(_replay_projection(reset_a, instance_a)) != canonical_bytes(
        _replay_projection(reset_b, instance_b)
    ) or canonical_bytes(_replay_projection(state_a, instance_a)) != canonical_bytes(
        _replay_projection(state_b, instance_b)
    ):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "reset_replay_drift",
            "default reset did not reconstruct the same controlled initial state",
        )
    if canonical_bytes([dict(item) for item in tools]) != canonical_bytes(
        [dict(item) for item in tools_b]
    ):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "tool_catalog_nondeterministic",
            "fresh actor instances returned different ToolSpecs",
        )
    state_a_after_b, isolation_events = _read_candidate_state(runtime, instance_a, state, settings)
    if canonical_bytes(state_a_after_b) != canonical_bytes(state_a):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "instance_isolation_failed",
            "resetting a second instance changed the first instance",
        )
    diagnostic_suite = _load_diagnostic_suite(
        actor_root,
        tool_names=tuple(item["name"] for item in tools),
    )
    diagnostic_results, diagnostic_evidence = _run_diagnostic_suite(
        runtime,
        diagnostic_suite,
        Path(runtime_root),
        start,
        reset,
        state,
        settings,
    )

    evidence: JSONObject = {
        "format": "environment-conformance-evidence/3",
        "actor_project_digest": actor_digest,
        "builder_checks": cast(
            JSONValue,
            [item.to_document() for item in candidate.checks],
        ),
        "host_checks": {
            "public_tool_specs": cast(JSONValue, [dict(item) for item in tools]),
            "tool_catalog_digest": sha256_hex(
                canonical_bytes({"tools": [dict(item) for item in tools]})
            ),
            "reset_observation_digest": sha256_hex(canonical_bytes(reset_a)),
            "initial_state_digest": sha256_hex(canonical_bytes(state_a)),
            "protected_read_events": cast(
                JSONValue,
                state_a_events + reopen_events + state_b_events + isolation_events,
            ),
            "reopen_persistence": True,
            "controlled_reset_replay": True,
            "replay_projection": "instance-root-token/1",
            "instance_isolation": True,
            "diagnostic_suite_digest": sha256_hex(canonical_bytes(diagnostic_suite.to_document())),
            "diagnostic_results": diagnostic_results,
            "diagnostic_evidence": cast(JSONValue, list(diagnostic_evidence)),
        },
    }
    receipt = make_conformance_receipt(
        actor_project_digest=actor_digest,
        actor_factory=ACTOR_FACTORY,
        state_reader_factory=STATE_READER_FACTORY,
        start_schema=start,
        reset_observation_schema=reset,
        state_schema=state,
        tool_specs=tools,
        evidence=evidence,
    )
    return ConformedEnvironmentV3(
        receipt,
        evidence,
        start,
        reset,
        state,
        tools,
        diagnostic_evidence,
    )


def bind_environment_semantics_v3(
    conformed: ConformedEnvironmentV3,
    *,
    projection: BuilderProjection,
    qualification: SemanticQualification,
) -> ConformedEnvironmentV3:
    evidence = make_qualified_conformance_evidence(
        conformed.evidence,
        projection=projection,
        tool_specs=conformed.tool_specs,
        diagnostic_evidence=conformed.diagnostic_evidence,
        qualification=qualification,
    )
    receipt = make_conformance_receipt(
        actor_project_digest=conformed.receipt.actor_project_digest,
        actor_factory=conformed.receipt.actor_factory,
        state_reader_factory=conformed.receipt.state_reader_factory,
        start_schema=conformed.start_schema,
        reset_observation_schema=conformed.reset_observation_schema,
        state_schema=conformed.state_schema,
        tool_specs=conformed.tool_specs,
        evidence=evidence,
    )
    return ConformedEnvironmentV3(
        receipt,
        evidence,
        conformed.start_schema,
        conformed.reset_observation_schema,
        conformed.state_schema,
        conformed.tool_specs,
        conformed.diagnostic_evidence,
    )


def _schema(
    path: Path,
    role: str,
    *,
    object_root: bool = False,
) -> JSONObject:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if object_root:
            require_object_root(document, role=role)
        else:
            validate_schema_document(document, role=role)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        raise PreparationExecutionError(
            "EnvironmentDefect", "actor_schema_invalid", str(exc), path=str(path)
        ) from exc
    return cast(JSONObject, document)


def _load_diagnostic_suite(
    actor_root: Path,
    *,
    tool_names: tuple[str, ...],
) -> DiagnosticSuite:
    path = actor_root / DIAGNOSTIC_SCENARIOS_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return parse_diagnostic_suite(document, tool_names=tool_names)
    except (OSError, json.JSONDecodeError, DiagnosticContractError) as exc:
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_contract_invalid",
            str(exc),
            path=DIAGNOSTIC_SCENARIOS_PATH.as_posix(),
        ) from exc


def _run_diagnostic_suite(
    runtime: RuntimeLock,
    suite: DiagnosticSuite,
    runtime_root: Path,
    start_schema: JSONObject,
    reset_schema: JSONObject,
    state_schema: JSONObject,
    settings: PreparationSettings,
) -> tuple[list[JSONValue], tuple[JSONObject, ...]]:
    results: list[JSONValue] = []
    evidence: list[JSONObject] = []
    for scenario in suite.scenarios:
        first_root = runtime_root / f"diagnostic-{scenario.scenario_id}-a"
        second_root = runtime_root / f"diagnostic-{scenario.scenario_id}-b"
        first = _run_diagnostic_scenario(
            runtime,
            scenario,
            first_root,
            start_schema,
            reset_schema,
            state_schema,
            settings,
        )
        second = _run_diagnostic_scenario(
            runtime,
            scenario,
            second_root,
            start_schema,
            reset_schema,
            state_schema,
            settings,
        )
        projected_first = _replay_projection(first, first_root)
        projected_second = _replay_projection(second, second_root)
        if canonical_bytes(projected_first) != canonical_bytes(projected_second):
            raise PreparationExecutionError(
                "EnvironmentDefect",
                "diagnostic_replay_drift",
                "identical diagnostic actions produced different observations or state",
                scenario_id=scenario.scenario_id,
            )
        evidence.append(_qualification_evidence(projected_first, scenario.scenario_id))
        results.append(
            {
                "scenario_id": scenario.scenario_id,
                "step_count": len(scenario.steps),
                "trace_digest": sha256_hex(canonical_bytes(projected_first)),
            }
        )
    return results, tuple(evidence)


def _qualification_evidence(value: JSONValue, scenario_id: str) -> JSONObject:
    if not isinstance(value, dict):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_evidence_invalid",
            "Host diagnostic execution did not produce an object",
            scenario_id=scenario_id,
        )
    steps = value.get("steps")
    if not isinstance(steps, list) or any(not isinstance(item, dict) for item in steps):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_evidence_invalid",
            "Host diagnostic execution did not produce structured steps",
            scenario_id=scenario_id,
        )
    return {
        "scenario_id": scenario_id,
        "reset": {
            "evidence_ref": f"{scenario_id}:reset",
            "reset_observation": value.get("reset_observation"),
            "initial_state": value.get("initial_state"),
        },
        "steps": [
            {
                "evidence_ref": f"{scenario_id}:step:{position}",
                **cast(JSONObject, step),
            }
            for position, step in enumerate(steps)
        ],
        "lifecycle": [
            {
                "evidence_ref": f"{scenario_id}:reopen",
                "operation": "close_reopen",
                "before_state": value.get("final_state"),
                "after_state": value.get("state_after_reopen"),
            },
            {
                "evidence_ref": f"{scenario_id}:reset-after-actions",
                "operation": "reset_after_actions",
                "reset_observation": value.get("post_reset_observation"),
                "before_state": value.get("state_after_reopen"),
                "after_state": value.get("post_reset_state"),
            },
        ],
        "final_state": value.get("final_state"),
    }


def _run_diagnostic_scenario(
    runtime: RuntimeLock,
    scenario: DiagnosticScenario,
    instance: Path,
    start_schema: JSONObject,
    reset_schema: JSONObject,
    state_schema: JSONObject,
    settings: PreparationSettings,
) -> JSONObject:
    instance.mkdir(parents=True, exist_ok=True)
    actor = _open_candidate_actor(runtime, instance, start_schema, reset_schema, settings)
    trace_steps: list[JSONValue] = []
    try:
        reset_observation = actor.reset(scenario.reset)
        current_state, _events = _read_candidate_state(runtime, instance, state_schema, settings)
        initial_state = current_state
        for position, step in enumerate(scenario.steps):
            before_state = current_state
            observation = actor.invoke(step.tool, step.arguments)
            current_state, _events = _read_candidate_state(
                runtime, instance, state_schema, settings
            )
            _validate_diagnostic_step(
                scenario,
                position,
                step.expected_ok,
                step.expected_error_code,
                step.state_effect,
                observation,
                before_state,
                current_state,
            )
            trace_step: JSONObject = {
                "tool": step.tool,
                "arguments": step.arguments,
                "observation": cast(JSONValue, dict(observation)),
                "before_state": before_state,
                "after_state": current_state,
            }
            if canonical_bytes(before_state) != canonical_bytes(current_state):
                actor.close()
                actor = _open_candidate_actor(
                    runtime,
                    instance,
                    start_schema,
                    reset_schema,
                    settings,
                )
                actor.tools()
                state_after_step_reopen, _events = _read_candidate_state(
                    runtime,
                    instance,
                    state_schema,
                    settings,
                )
                if canonical_bytes(state_after_step_reopen) != canonical_bytes(current_state):
                    raise PreparationExecutionError(
                        "EnvironmentDefect",
                        "diagnostic_step_reopen_persistence",
                        "a successful state transition did not persist across immediate reopen",
                        scenario_id=scenario.scenario_id,
                        step=position,
                    )
                trace_step["state_after_reopen"] = state_after_step_reopen
            trace_steps.append(trace_step)
    finally:
        actor.close()
    state_after_close, _events = _read_candidate_state(runtime, instance, state_schema, settings)
    if canonical_bytes(state_after_close) != canonical_bytes(current_state):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_close_persistence",
            "diagnostic state changed after actor close",
            scenario_id=scenario.scenario_id,
        )
    _reopen_candidate(runtime, instance, start_schema, reset_schema, settings)
    state_after_reopen, _events = _read_candidate_state(runtime, instance, state_schema, settings)
    if canonical_bytes(state_after_reopen) != canonical_bytes(current_state):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_reopen_persistence",
            "diagnostic state changed after actor reopen",
            scenario_id=scenario.scenario_id,
        )
    post_reset_observation, _tools = _reset_candidate(
        runtime,
        instance,
        start_schema,
        reset_schema,
        settings,
        start_value=scenario.reset,
    )
    post_reset_state, _events = _read_candidate_state(runtime, instance, state_schema, settings)
    if canonical_bytes(post_reset_observation) != canonical_bytes(
        reset_observation
    ) or canonical_bytes(post_reset_state) != canonical_bytes(initial_state):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_reset_restoration",
            "reset after diagnostic actions did not restore the same controlled initial state",
            scenario_id=scenario.scenario_id,
        )
    return {
        "scenario_id": scenario.scenario_id,
        "reset_observation": reset_observation,
        "initial_state": initial_state,
        "steps": trace_steps,
        "final_state": current_state,
        "state_after_reopen": state_after_reopen,
        "post_reset_observation": post_reset_observation,
        "post_reset_state": post_reset_state,
    }


def _validate_diagnostic_step(
    scenario: DiagnosticScenario,
    position: int,
    expected_ok: bool,
    expected_error_code: str | None,
    state_effect: str,
    observation: ToolObservation,
    before_state: JSONValue,
    after_state: JSONValue,
) -> None:
    actual_ok = observation["ok"]
    if actual_ok is not expected_ok:
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_outcome_mismatch",
            "diagnostic observation success/refusal differs from its authored case",
            scenario_id=scenario.scenario_id,
            step=position,
            expected_ok=expected_ok,
            actual_ok=actual_ok,
        )
    if not expected_ok:
        error = observation["error"]
        actual_code = error.get("code") if isinstance(error, dict) else None
        if actual_code != expected_error_code:
            raise PreparationExecutionError(
                "EnvironmentDefect",
                "diagnostic_error_code_mismatch",
                "diagnostic refusal returned a different public error code",
                scenario_id=scenario.scenario_id,
                step=position,
                expected=expected_error_code,
                actual=actual_code,
            )
    changed = canonical_bytes(before_state) != canonical_bytes(after_state)
    expected_changed = state_effect == "changed"
    if changed is not expected_changed:
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "diagnostic_state_effect_mismatch",
            "diagnostic protected-state effect differs from its authored case",
            scenario_id=scenario.scenario_id,
            step=position,
            expected=state_effect,
            actual="changed" if changed else "unchanged",
        )


def _replay_projection(value: JSONValue, instance_root: Path) -> JSONValue:
    """Remove only the Host-assigned instance locator from cross-instance comparison."""

    root = str(instance_root.resolve())
    if isinstance(value, str):
        if value == root:
            return "<INSTANCE_ROOT>"
        prefix = root + "/"
        if value.startswith(prefix):
            return "<INSTANCE_ROOT>/" + value[len(prefix) :]
        return value
    if isinstance(value, list):
        return [_replay_projection(item, instance_root) for item in value]
    if isinstance(value, dict):
        return {key: _replay_projection(item, instance_root) for key, item in value.items()}
    return value


def _reset_candidate(
    runtime: RuntimeLock,
    instance: Path,
    start: JSONObject,
    reset: JSONObject,
    settings: PreparationSettings,
    *,
    start_value: JSONObject | None = None,
) -> tuple[JSONValue, tuple[ToolSpec, ...]]:
    instance.mkdir(parents=True, exist_ok=True)
    transport = _ChildTransport(
        runtime.python,
        Path(__file__).resolve().parent / "_actor_runner.py",
        (ACTOR_FACTORY, str(instance.resolve())),
        cwd=runtime.project_root,
        timeout=settings.command_timeout_seconds,
        role="actor",
    )
    actor = ActorProxy(
        transport,
        start_schema=start,
        reset_observation_schema=reset,
    )
    try:
        tools = actor.tools()
        observation = actor.reset(start_value)
        return observation, tools
    finally:
        actor.close()


def _open_candidate_actor(
    runtime: RuntimeLock,
    instance: Path,
    start: JSONObject,
    reset: JSONObject,
    settings: PreparationSettings,
) -> ActorProxy:
    transport = _ChildTransport(
        runtime.python,
        Path(__file__).resolve().parent / "_actor_runner.py",
        (ACTOR_FACTORY, str(instance.resolve())),
        cwd=runtime.project_root,
        timeout=settings.command_timeout_seconds,
        role="actor",
    )
    return ActorProxy(
        transport,
        start_schema=start,
        reset_observation_schema=reset,
    )


def _reopen_candidate(
    runtime: RuntimeLock,
    instance: Path,
    start: JSONObject,
    reset: JSONObject,
    settings: PreparationSettings,
) -> None:
    transport = _ChildTransport(
        runtime.python,
        Path(__file__).resolve().parent / "_actor_runner.py",
        (ACTOR_FACTORY, str(instance.resolve())),
        cwd=runtime.project_root,
        timeout=settings.command_timeout_seconds,
        role="actor",
    )
    actor = ActorProxy(
        transport,
        start_schema=start,
        reset_observation_schema=reset,
    )
    try:
        actor.tools()
    finally:
        actor.close()


def _read_candidate_state(
    runtime: RuntimeLock,
    instance: Path,
    state_schema: JSONObject,
    settings: PreparationSettings,
) -> tuple[JSONValue, list[JSONValue]]:
    transport = _ChildTransport(
        runtime.python,
        Path(__file__).resolve().parent / "_state_runner.py",
        (STATE_READER_FACTORY,),
        cwd=runtime.project_root,
        timeout=settings.command_timeout_seconds,
        role="actor",
    )
    events: list[StateSnapshotEvent] = []
    proxy = StateSnapshotProxy(transport, state_schema=state_schema, events=events)
    try:
        first = proxy.read(instance)
        proxy.read(instance)
    finally:
        proxy.close()
    return first, [event.to_document() for event in events]


__all__ = [
    "ConformedEnvironmentV3",
    "bind_environment_semantics_v3",
    "run_environment_conformance_v3_internal",
]
