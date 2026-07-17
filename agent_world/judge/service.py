"""Framework-owned Judge gates over an untrusted Task Materializer v3 candidate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from pydantic import JsonValue, ValidationError

from agent_world.artifact_store import ArtifactStoreError, ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CandidateManifest,
    CurriculumRequirements,
    EnvironmentCandidate,
    EnvironmentDesign,
    Finding,
    FrameworkTaskEnvelope,
    GateResult,
    IntegrationReport,
    JudgeReport,
    PackageFile,
    PublicTask,
    ReleaseProfile,
    Rule,
    RuntimeAction,
    TaskMaterializerCall,
    TaskRequirement,
    VerifierCase,
    VerifierIR,
    WorldSpec,
    candidate_source_tree_digest,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.contracts.lineage import ImplementationLineage
from agent_world.contracts.reachability import (
    ParameterizedSolveRecipe,
    ReachabilityCertificate,
    ReachabilityInstance,
    ReachabilityPolicy,
    ReachabilityPublicEvidence,
)
from agent_world.contracts.supply_chain import (
    PublicTestExecution,
    StaticAssuranceEvidence,
    SupplyChainEvidence,
)
from agent_world.task_materialization import (
    TaskMaterializationError,
    TaskMaterializerV3Compiler,
)

from .assertions import evaluate_assertion
from .assurance import MAX_PUBLIC_TESTS, inspect_static_sources, inspect_supply_chain
from .models import CaseEvaluation, RuntimeActionObservation
from .protocol import ProtocolViolation, RuntimeResponse
from .reachability import (
    EpisodeDriver,
    EpisodeDriverError,
    EpisodeStepResult,
    InteractiveChallengerStrategy,
    ParameterizedRecipeStrategy,
    ReachabilityOutcome,
)
from .rules import RuleExecutionContext, design_rule_index, evaluate_rule, evaluate_task_reward
from .semantics import ToolExecutionEvidence, validate_tool_execution
from .supervisor import (
    CandidateBuildError,
    CandidateSandboxRunner,
    CleanCandidate,
    CleanCandidateBuilder,
    IsolationPolicy,
    IsolationUnavailable,
    JudgeInfrastructureError,
    LaunchContract,
    RuntimeProcessCrashed,
    RuntimeRequestTimeout,
    RuntimeSupervisor,
    SandboxProcessResult,
)
from .task_semantics import (
    DifficultyContrastCandidate,
    GeneratedTaskSemanticError,
    find_difficulty_contrast_candidates,
)
from .visibility import actor_projection_schema, component_visible_paths

GateStatus = Literal["pass", "fail", "inconclusive", "error"]
FindingOwner = Literal[
    "design",
    "verifier",
    "build",
    "judge_infrastructure",
    "permissions",
    "release_policy",
]

_CANONICAL_GATES = (
    "schema",
    "supply_chain",
    "static_assurance",
    "public_self_check",
    "runtime_protocol",
    "task_materialization",
    "task_reachability",
    "behavior",
    "sealed_release",
    "clean_deployment",
)
_ALWAYS_HARD_GATES = frozenset(
    {
        "schema",
        "supply_chain",
        "static_assurance",
        "runtime_protocol",
        "task_materialization",
        "task_reachability",
        "behavior",
        "sealed_release",
        "clean_deployment",
    }
)
_FORBIDDEN_SOURCE_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "fixtures",
        "mocks",
        "stubs",
        "transcripts",
    }
)


class _CandidateTaskFailure(ValueError):
    """Candidate-owned materializer or Runtime defect safe to route to Builder."""


class _RuntimeContractFailure(_CandidateTaskFailure):
    """Complete deterministic Runtime/WorldSpec contract diff for one handshake."""

    def __init__(self, mismatch_paths: Sequence[str]) -> None:
        self.mismatch_paths = tuple(mismatch_paths)
        joined = ", ".join(self.mismatch_paths)
        super().__init__(f"Runtime handshake differs from WorldSpec at: {joined}")


def _runtime_contract_mismatch_paths(
    raw_tools: object,
    world_spec: WorldSpec,
) -> tuple[str, ...]:
    """Return every deterministic handshake mismatch without short-circuiting.

    The returned paths are safe repair coordinates: the Builder already receives
    the frozen WorldSpec and can inspect the candidate source, so the Judge need
    not duplicate large schemas or candidate-controlled values in a Finding.
    """

    if not isinstance(raw_tools, list):
        return ("tools[type=array]",)

    malformed: list[str] = []
    observed_by_id: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(raw_tools):
        if not isinstance(item, dict):
            malformed.append(f"tools[{index}][type=object]")
            continue
        tool_id = item.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            malformed.append(f"tools[{index}].tool_id[type=non-empty-string]")
            continue
        observed_by_id.setdefault(tool_id, []).append(item)

    expected = {item.surface.tool_id: item.surface for item in world_spec.tools}
    mismatches = list(malformed)
    for tool_id in sorted(expected.keys() - observed_by_id.keys()):
        mismatches.append(f"tools[{tool_id}][missing]")
    for tool_id in sorted(observed_by_id.keys() - expected.keys()):
        mismatches.append(f"tools[{tool_id}][unexpected]")
    for tool_id in sorted(observed_by_id.keys() & expected.keys()):
        entries = observed_by_id[tool_id]
        if len(entries) != 1:
            mismatches.append(f"tools[{tool_id}][duplicate:{len(entries)}]")
            continue
        surface = expected[tool_id]
        contract = {
            "namespace": surface.namespace,
            "name": surface.name,
            "input_schema": surface.input_schema,
            "output_schema": surface.output_schema,
            "observation_schema": surface.observation_schema,
        }
        for key, expected_value in contract.items():
            if canonical_json_bytes(entries[0].get(key)) != canonical_json_bytes(
                expected_value
            ):
                mismatches.append(f"tools[{tool_id}].{key}")
    return tuple(mismatches)


def _candidate_failure_summary(exc: BaseException) -> str:
    """Preserve deterministic protocol coordinates in Builder-safe feedback."""

    summary = str(exc)
    if not isinstance(exc, ProtocolViolation):
        return summary
    details = exc.details
    missing = details.get("missing")
    extra = details.get("extra")
    coordinates: list[str] = []
    if isinstance(missing, list) and missing:
        coordinates.append("missing=" + ",".join(str(item) for item in missing))
    if isinstance(extra, list) and extra:
        coordinates.append("extra=" + ",".join(str(item) for item in extra))
    if coordinates:
        summary += "; " + "; ".join(coordinates)
    return summary


def _schema_validation_coordinates(errors: Sequence[Any]) -> tuple[str, ...]:
    """Project jsonschema failures to value-free, deterministic repair coordinates."""

    coordinates: list[str] = []
    ordered = sorted(
        errors,
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            tuple(str(part) for part in error.absolute_schema_path),
        ),
    )
    for error in ordered:
        path = "/" + "/".join(
            str(part).replace("~", "~0").replace("/", "~1")
            for part in error.absolute_path
        )
        validator = str(error.validator)
        detail = validator
        if validator == "required" and isinstance(error.instance, Mapping):
            required = error.validator_value
            if isinstance(required, list):
                missing = sorted(
                    str(item) for item in required if str(item) not in error.instance
                )
                if missing:
                    detail += "_missing=" + "|".join(missing)
        elif validator == "additionalProperties" and isinstance(error.instance, Mapping):
            properties = error.schema.get("properties", {})
            if isinstance(properties, Mapping):
                extra = sorted(str(item) for item in set(error.instance) - set(properties))
                if extra:
                    detail += "_extra=" + "|".join(extra)
        elif validator == "type":
            expected_type = error.validator_value
            if isinstance(expected_type, str):
                detail += "_expected=" + expected_type
            elif isinstance(expected_type, list):
                detail += "_expected=" + "|".join(str(item) for item in expected_type)
        coordinate = f"{path}:{detail}"
        if coordinate not in coordinates:
            coordinates.append(coordinate)
    maximum_coordinates = 64
    if len(coordinates) > maximum_coordinates:
        omitted = len(coordinates) - maximum_coordinates
        return (*coordinates[:maximum_coordinates], f"/+{omitted}:additional_errors")
    return tuple(coordinates)


@dataclass(frozen=True, slots=True)
class JudgeBundle:
    report: JudgeReport
    report_ref: ArtifactRef
    evidence_refs: tuple[ArtifactRef, ...]


@dataclass(frozen=True, slots=True)
class IntegrationBundle:
    """Early real-execution evidence; never a substitute for Release Judge."""

    report: IntegrationReport
    report_ref: ArtifactRef
    evidence_refs: tuple[ArtifactRef, ...]


@dataclass(frozen=True, slots=True)
class _MaterializationGateResult:
    status: GateStatus
    evidence_ref: ArtifactRef
    summary: str
    episodes: int
    envelopes: tuple[FrameworkTaskEnvelope, ...]
    owner: FindingOwner


@dataclass(frozen=True, slots=True)
class _ReachabilityGateResult:
    status: GateStatus
    evidence_ref: ArtifactRef
    summary: str
    episodes: int
    usage: BudgetUsage
    owner: FindingOwner
    recipe_rework_task_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _AssuranceGateResult:
    status: GateStatus
    evidence_ref: ArtifactRef
    summary: str
    owner: FindingOwner
    tool_calls: int = 0


class _RealEpisodeDriver(EpisodeDriver):
    """One Judge-private adapter over one already-reset real Runtime process."""

    def __init__(
        self,
        *,
        judge: EnvironmentJudge,
        supervisor: RuntimeSupervisor,
        envelope: FrameworkTaskEnvelope,
        reset_observation: JsonValue,
        pre_snapshot: dict[str, JsonValue],
        design: EnvironmentDesign,
    ) -> None:
        self._judge = judge
        self._supervisor = supervisor
        self._envelope = envelope
        self._design = design
        self._pre_snapshot = pre_snapshot
        self._step_index = 0
        self._reset_observation = reset_observation
        self._rules = design_rule_index(design)
        self._tools = {tool.surface.tool_id: tool for tool in design.world_spec.tools}
        actor = envelope.call.actor
        self._tool_schemas = {
            tool.surface.tool_id: tool.surface.input_schema
            for tool in design.world_spec.tools
            if actor in tool.semantics.permission.allowed_actors
        }
        self._public_task = PublicTask(
            seed=envelope.call.seed,
            task_type=envelope.call.task_type,
            actor=actor,
            public_instruction=envelope.public_instruction,
            public_goal=envelope.materialization.public_goal,
            difficulty=envelope.call.difficulty,
        )

    @property
    def public_task(self) -> PublicTask:
        return self._public_task

    @property
    def reset_observation(self) -> JsonValue:
        return self._reset_observation

    @property
    def tool_schemas(self) -> Mapping[str, Mapping[str, JsonValue]]:
        return self._tool_schemas

    @property
    def final_state_digest(self) -> str:
        return cast(str, self._pre_snapshot["state_digest"])

    async def execute(self, action: RuntimeAction) -> EpisodeStepResult:
        tool = self._tools.get(action.tool_id)
        if tool is None or action.tool_id not in self._tool_schemas:
            raise EpisodeDriverError(
                "runtime_action_not_available",
                f"tool {action.tool_id} is unavailable to the bound actor",
            )
        key = action.idempotency_key or self._judge._idempotency_key(
            self._envelope.call.seed,
            self._step_index,
            "reachability",
        )
        try:
            response = await self._supervisor.invoke(
                tool=action.tool_id,
                args=action.arguments,
                idempotency_key=key,
            )
            snapshot_response = await self._supervisor.snapshot()
            if not snapshot_response.ok or snapshot_response.result is None:
                raise _CandidateTaskFailure("Runtime snapshot failed after a solver action")
            post_snapshot = dict(snapshot_response.result)
            self._judge._validate_state_snapshot(post_snapshot, self._design)
            observation, context = self._judge._observation(
                index=self._step_index,
                action=action,
                idempotency_key=key,
                response=response,
                pre_snapshot=self._pre_snapshot,
                post_snapshot=post_snapshot,
                reset_config=self._envelope.materialization.initial_config,
                task_goal=self._envelope.evaluator_goal,
                seed=self._envelope.call.seed,
                actor=self._envelope.call.actor,
                design=self._design,
            )
            self._judge._validate_tool_semantics(
                observation,
                context,
                tool,
                self._design,
                self._rules,
            )
            trusted = evaluate_task_reward(
                self._design,
                self._envelope.call.task_type,
                context,
            )
            self._pre_snapshot = post_snapshot
            self._step_index += 1
            result = response.result
            if result is None:
                raise _CandidateTaskFailure("Runtime invoke omitted its result envelope")
            return EpisodeStepResult(
                observation=result["observation"],
                tool_result=result["tool_result"],
                reward=trusted.reward,
                terminated=trusted.terminated,
                succeeded=trusted.succeeded,
                failed=trusted.failed,
            )
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            raise EpisodeDriverError(
                "candidate_episode_execution_failed",
                str(exc),
            ) from exc
        except JudgeInfrastructureError as exc:
            raise EpisodeDriverError(exc.code, str(exc), infrastructure=True) from exc


class EnvironmentJudge:
    """Build, isolate and independently execute every release claim."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactWriter,
        interactive_challenger: InteractiveChallengerStrategy | None = None,
        clean_builder: CleanCandidateBuilder | None = None,
        runtime_isolation: IsolationPolicy | None = None,
    ) -> None:
        self.artifacts = artifact_store
        self.interactive_challenger = interactive_challenger
        self.clean_builder = clean_builder or CleanCandidateBuilder()
        self.runtime_isolation = runtime_isolation or IsolationPolicy(purpose="runtime")
        if self.runtime_isolation.purpose != "runtime":
            raise ValueError("EnvironmentJudge Runtime isolation must be purpose=runtime")
        self.sandbox_runner = CandidateSandboxRunner(isolation=self.runtime_isolation)

    @staticmethod
    def required_evaluation_episodes(
        *,
        design: EnvironmentDesign,
        verifier: VerifierIR,
    ) -> int:
        """Worst-case lease reservation for the complete successful Judge path."""

        task_call_counts = EnvironmentJudge._task_materializer_call_counts(design.curriculum)
        task_calls = sum(task_call_counts.values())
        protocol = design.verification.minimum_unknown_seed_episodes + 1
        recipes = EnvironmentJudge._recipe_index(verifier.solve_recipes)
        reachability_attempts = sum(
            task_call_counts[requirement.task_type]
            * (
                1
                + int(
                    requirement.task_type in recipes
                    and requirement.reachability_policy.maximum_solver_attempts >= 2
                )
            )
            for requirement in design.curriculum.task_types
        )
        return task_calls + protocol + reachability_attempts + len(verifier.cases) + 2

    def required_evaluation_budget(
        self,
        *,
        design: EnvironmentDesign,
        verifier: VerifierIR,
        available: Budget,
    ) -> Budget:
        """Compile a conservative child lease without exchanging dimensions.

        Discrete Judge work (episodes, turns, tokens and tool calls) is an exact
        worst-case bound.  Container, global wall and monetary dimensions retain
        the Controller-provided ceilings because candidate process duration and
        provider pricing are not knowable from frozen Design/Verifier contracts.
        """

        call_counts = EnvironmentJudge._task_materializer_call_counts(design.curriculum)
        recipes = EnvironmentJudge._recipe_index(verifier.solve_recipes)
        interactive_attempts: dict[str, int] = {}
        reachability_tool_calls = 0
        for requirement in design.curriculum.task_types:
            count = call_counts[requirement.task_type]
            policy = requirement.reachability_policy
            # No recipe means the Challenger is the first strategy.  With a recipe,
            # a second reserved attempt is the real Challenger fallback.
            interactive_attempts[requirement.task_type] = (
                count
                if requirement.task_type not in recipes or policy.maximum_solver_attempts >= 2
                else 0
            )
            recipe = recipes.get(requirement.task_type)
            if recipe is not None:
                reachability_tool_calls += count * min(
                    len(recipe.steps),
                    policy.maximum_steps_per_attempt,
                )
            reachability_tool_calls += (
                interactive_attempts[requirement.task_type] * policy.maximum_steps_per_attempt
            )
        return Budget(
            llm_tokens=sum(
                interactive_attempts[item.task_type]
                * item.reachability_policy.maximum_llm_tokens_per_attempt
                for item in design.curriculum.task_types
            ),
            agent_turns=sum(
                interactive_attempts[item.task_type]
                * item.reachability_policy.maximum_agent_turns_per_attempt
                for item in design.curriculum.task_types
            ),
            search_calls=0,
            tool_calls=(
                reachability_tool_calls
                + sum(len(case.actions) for case in verifier.cases)
                + MAX_PUBLIC_TESTS
                + 2
            ),
            build_seconds=self.clean_builder.timeout_seconds,
            evaluation_episodes=EnvironmentJudge.required_evaluation_episodes(
                design=design,
                verifier=verifier,
            ),
            container_seconds=available.container_seconds,
            live_probe_cost=0,
            repair_attempts=0,
            wall_seconds=available.wall_seconds,
            monetary_cost=available.monetary_cost,
        )

    def required_integration_budget(
        self,
        *,
        design: EnvironmentDesign,
        available: Budget,
    ) -> Budget:
        """Reserve real install/reset/invoke work without reserving Challenger work."""

        task_calls = sum(self._task_materializer_call_counts(design.curriculum).values())
        return Budget(
            llm_tokens=0,
            agent_turns=0,
            search_calls=0,
            tool_calls=MAX_PUBLIC_TESTS + 2,
            build_seconds=self.clean_builder.timeout_seconds,
            evaluation_episodes=task_calls + 2,
            container_seconds=available.container_seconds,
            live_probe_cost=0,
            repair_attempts=0,
            wall_seconds=available.wall_seconds,
            monetary_cost=0,
        )

    async def evaluate_integration(
        self,
        *,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        source_dir: Path,
        world_spec: WorldSpec,
        world_spec_ref: ArtifactRef,
        release_profile: ReleaseProfile,
        budget: Budget,
        run_id: str | None = None,
    ) -> IntegrationBundle:
        """Exercise a Build as soon as it exists, independently of Verifier creation.

        Integration proves source closure, offline install, component isolation,
        Runtime handshake/reset/invoke protocol, and Task Materializer execution.
        It deliberately does not prove task reachability, business behavior, or
        sealed release obligations; only :meth:`evaluate` can do that.
        """

        self.artifacts.require_exact_json(
            candidate_ref,
            candidate,
            artifact_types=("build.environment_candidate",),
        )
        self.artifacts.require_exact_json(
            world_spec_ref,
            world_spec,
            artifact_types=("design.world_spec", "expansion.world_spec"),
        )
        design = self.artifacts.get_json(candidate.design_ref, EnvironmentDesign)
        self.artifacts.require_exact_json(
            candidate.design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        if design.world_spec != world_spec:
            raise ArtifactStoreError("candidate design and supplied WorldSpec differ")
        _require_budget_at_least(
            budget,
            self.required_integration_budget(design=design, available=budget),
        )

        integration_id = run_id or f"integration-{uuid.uuid4().hex}"
        started = time.monotonic()
        evidence_refs: list[ArtifactRef] = []
        gate_results: list[GateResult] = []
        findings: list[Finding] = []
        episodes = 0
        tool_calls = 0
        clean_build_seconds = 0.0
        verified_source_tree_digest: str | None = None
        manifest: CandidateManifest | None = None

        try:
            manifest = self.artifacts.get_json(
                candidate.candidate_manifest_ref,
                CandidateManifest,
            )
            self.artifacts.require_exact_json(
                candidate.candidate_manifest_ref,
                manifest,
                artifact_types=("build.candidate_manifest",),
            )
            verified_source_tree_digest = manifest.candidate_source_tree_digest
            schema_record = self._validate_candidate_source(
                source_dir,
                candidate=candidate,
                candidate_ref=candidate_ref,
                manifest=manifest,
                world_spec=world_spec,
                world_spec_ref=world_spec_ref,
                verifier=None,
                verifier_ref=None,
            )
            schema_ref = self._evidence(
                integration_id,
                "integration-schema",
                schema_record,
                dependencies=(candidate_ref, candidate.candidate_manifest_ref),
            )
            evidence_refs.append(schema_ref)
            gate_results.append(
                self._gate(
                    "schema",
                    "pass",
                    candidate_ref,
                    (schema_ref,),
                    release_profile,
                    "Candidate closure and v3 component boundaries are valid.",
                )
            )
        except (ArtifactStoreError, OSError, ValueError, JudgeInfrastructureError) as exc:
            schema_ref = self._evidence(
                integration_id,
                "integration-schema",
                {"status": "fail", "error_type": type(exc).__name__, "message": str(exc)},
                dependencies=(candidate_ref,),
            )
            evidence_refs.append(schema_ref)
            gate_results.append(
                self._gate(
                    "schema",
                    "fail",
                    candidate_ref,
                    (schema_ref,),
                    release_profile,
                    "Candidate source or contract failed independent validation.",
                )
            )
            findings.append(
                self._finding(
                    integration_id,
                    "schema",
                    candidate_ref,
                    schema_ref,
                    owner="build",
                    summary="Candidate source or manifest is invalid.",
                    suggested_repair=str(exc),
                )
            )
            return self._finish_integration(
                run_id=integration_id,
                candidate_ref=candidate_ref,
                gate_results=gate_results,
                findings=findings,
                evidence_refs=evidence_refs,
                report_dependencies=(world_spec_ref,),
                started=started,
                episodes=episodes,
                tool_calls=tool_calls,
                clean_build_seconds=clean_build_seconds,
                candidate_source_tree_digest=verified_source_tree_digest,
            )

        assert manifest is not None
        try:
            async with self.clean_builder.materialize(
                source_dir,
                expected_source_files=manifest.files,
                expected_source_tree_digest=manifest.candidate_source_tree_digest,
            ) as clean:
                clean_build_seconds = clean.install.duration_ms / 1000
                install_ref = self._evidence(
                    integration_id,
                    "integration-clean-install",
                    asdict(clean.install),
                    dependencies=(candidate_ref,),
                )
                evidence_refs.append(install_ref)

                supply_chain = self._supply_chain_gate(
                    integration_id,
                    clean,
                    candidate_ref,
                    manifest,
                )
                self._record_gate(
                    gate_id="supply_chain",
                    status=supply_chain.status,
                    evidence_ref=supply_chain.evidence_ref,
                    summary=supply_chain.summary,
                    owner=supply_chain.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=integration_id,
                )
                static_assurance = await self._static_assurance_gate(
                    integration_id,
                    clean,
                    candidate_ref,
                    manifest,
                )
                tool_calls += static_assurance.tool_calls
                self._record_gate(
                    gate_id="static_assurance",
                    status=static_assurance.status,
                    evidence_ref=static_assurance.evidence_ref,
                    summary=static_assurance.summary,
                    owner=static_assurance.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=integration_id,
                )
                if supply_chain.status != "pass" or static_assurance.status != "pass":
                    return self._finish_integration(
                        run_id=integration_id,
                        candidate_ref=candidate_ref,
                        gate_results=gate_results,
                        findings=findings,
                        evidence_refs=evidence_refs,
                        report_dependencies=(world_spec_ref,),
                        started=started,
                        episodes=episodes,
                        tool_calls=tool_calls,
                        clean_build_seconds=clean_build_seconds,
                        candidate_source_tree_digest=verified_source_tree_digest,
                    )

                public_status, public_ref, public_summary = await self._public_self_check_gate(
                    integration_id,
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                )
                self._record_gate(
                    gate_id="public_self_check",
                    status=public_status,
                    evidence_ref=public_ref,
                    summary=public_summary,
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=integration_id,
                )
                protocol = await self._integration_protocol_gate(
                    integration_id,
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                    world_spec,
                    world_spec_ref,
                )
                self._record_gate(
                    gate_id="runtime_protocol",
                    status=protocol[0],
                    evidence_ref=protocol[1],
                    summary=protocol[2],
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=integration_id,
                )
                materialization = await self._task_materialization_gate(
                    integration_id,
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                    design,
                )
                episodes += materialization.episodes
                self._record_gate(
                    gate_id="task_materialization",
                    status=materialization.status,
                    evidence_ref=materialization.evidence_ref,
                    summary=materialization.summary,
                    owner=materialization.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=integration_id,
                )
                if protocol[0] == "pass" and materialization.status == "pass":
                    deployment = await self._integration_deployment_gate(
                        integration_id,
                        clean,
                        candidate,
                        candidate_ref,
                        install_ref,
                        manifest,
                        world_spec,
                        materialization.envelopes[0],
                    )
                    episodes += deployment[3]
                    tool_calls += deployment[4]
                else:
                    deployment_ref = self._evidence(
                        integration_id,
                        "integration-deployment",
                        {
                            "status": "inconclusive",
                            "reason": "protocol or task materialization failed first",
                        },
                        dependencies=(candidate_ref, materialization.evidence_ref),
                    )
                    deployment = (
                        "inconclusive",
                        deployment_ref,
                        "Deployment probe was not run after an earlier integration failure.",
                        0,
                        0,
                    )
                self._record_gate(
                    gate_id="clean_deployment",
                    status=deployment[0],
                    evidence_ref=deployment[1],
                    summary=deployment[2],
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=integration_id,
                )
        except CandidateBuildError as exc:
            if exc.record is not None:
                clean_build_seconds = exc.record.duration_ms / 1000
            build_ref = self._evidence(
                integration_id,
                "integration-clean-install",
                asdict(exc.record)
                if exc.record is not None
                else {
                    "status": "fail",
                    "failure_class": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                },
                dependencies=(candidate_ref,),
            )
            self._record_gate(
                gate_id="clean_deployment",
                status="fail",
                evidence_ref=build_ref,
                summary="Candidate failed its frozen offline build.",
                owner="build",
                candidate_ref=candidate_ref,
                release_profile=release_profile,
                gate_results=gate_results,
                evidence_refs=evidence_refs,
                findings=findings,
                run_id=integration_id,
            )
        except (IsolationUnavailable, JudgeInfrastructureError) as exc:
            infrastructure_ref = self._evidence(
                integration_id,
                "integration-infrastructure",
                {"status": "error", "code": exc.code, "message": str(exc)},
                dependencies=(candidate_ref,),
            )
            self._record_gate(
                gate_id="clean_deployment",
                status="error",
                evidence_ref=infrastructure_ref,
                summary="Required Integration infrastructure failed closed.",
                owner="judge_infrastructure",
                candidate_ref=candidate_ref,
                release_profile=release_profile,
                gate_results=gate_results,
                evidence_refs=evidence_refs,
                findings=findings,
                run_id=integration_id,
            )

        return self._finish_integration(
            run_id=integration_id,
            candidate_ref=candidate_ref,
            gate_results=gate_results,
            findings=findings,
            evidence_refs=evidence_refs,
            report_dependencies=(world_spec_ref,),
            started=started,
            episodes=episodes,
            tool_calls=tool_calls,
            clean_build_seconds=clean_build_seconds,
            candidate_source_tree_digest=verified_source_tree_digest,
        )

    async def evaluate(
        self,
        *,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        source_dir: Path,
        world_spec: WorldSpec,
        world_spec_ref: ArtifactRef,
        verifier: VerifierIR,
        verifier_ref: ArtifactRef,
        release_profile: ReleaseProfile,
        budget: Budget,
        reachability_workspace: Path,
        run_id: str | None = None,
    ) -> JudgeBundle:
        self.artifacts.require_exact_json(
            candidate_ref,
            candidate,
            artifact_types=("build.environment_candidate",),
        )
        self.artifacts.require_exact_json(
            world_spec_ref,
            world_spec,
            artifact_types=("design.world_spec", "expansion.world_spec"),
        )
        self.artifacts.require_exact_json(
            verifier_ref,
            verifier.persistence_projection(),
            artifact_types=("judge.verifier_ir_projection",),
        )
        design = self.artifacts.get_json(candidate.design_ref, EnvironmentDesign)
        self.artifacts.require_exact_json(
            candidate.design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        if design.world_spec != world_spec:
            raise ArtifactStoreError("candidate design and supplied WorldSpec differ")
        required_budget = self.required_evaluation_budget(
            design=design,
            verifier=verifier,
            available=budget,
        )
        _require_budget_at_least(budget, required_budget)
        reachability_workspace = (
            reachability_workspace.expanduser().resolve()  # noqa: ASYNC240
        )

        run_id = run_id or f"judge-{uuid.uuid4().hex}"
        started = time.monotonic()
        evidence_refs: list[ArtifactRef] = []
        gate_results: list[GateResult] = []
        findings: list[Finding] = []
        episodes = 0
        non_reachability_tool_calls = 0
        reachability_usage = BudgetUsage()
        clean_build_seconds = 0.0
        verified_source_tree_digest: str | None = None

        try:
            manifest = self.artifacts.get_json(
                candidate.candidate_manifest_ref,
                CandidateManifest,
            )
            self.artifacts.require_exact_json(
                candidate.candidate_manifest_ref,
                manifest,
                artifact_types=("build.candidate_manifest",),
            )
            verified_source_tree_digest = manifest.candidate_source_tree_digest
            schema_record = self._validate_candidate_source(
                source_dir,
                candidate=candidate,
                candidate_ref=candidate_ref,
                manifest=manifest,
                world_spec=world_spec,
                world_spec_ref=world_spec_ref,
                verifier=verifier,
                verifier_ref=verifier_ref,
            )
            schema_ref = self._evidence(
                run_id,
                "schema",
                schema_record,
                dependencies=(candidate_ref, candidate.candidate_manifest_ref, verifier_ref),
            )
            evidence_refs.append(schema_ref)
            gate_results.append(
                self._gate(
                    "schema",
                    "pass",
                    candidate_ref,
                    (schema_ref,),
                    release_profile,
                    "Candidate closure, provenance and v3 component boundaries are valid.",
                )
            )
        except (OSError, ValueError, JudgeInfrastructureError) as exc:
            schema_ref = self._evidence(
                run_id,
                "schema",
                {"status": "fail", "error_type": type(exc).__name__, "message": str(exc)},
                dependencies=(candidate_ref, verifier_ref),
            )
            evidence_refs.append(schema_ref)
            gate_results.append(
                self._gate(
                    "schema",
                    "fail",
                    candidate_ref,
                    (schema_ref,),
                    release_profile,
                    "Candidate source or contract failed independent validation.",
                )
            )
            findings.append(
                self._finding(
                    run_id,
                    "schema",
                    candidate_ref,
                    schema_ref,
                    owner="build",
                    summary="Candidate source or manifest is invalid.",
                    suggested_repair=str(exc),
                )
            )
            return self._finish(
                run_id=run_id,
                candidate_ref=candidate_ref,
                gate_results=gate_results,
                findings=findings,
                evidence_refs=evidence_refs,
                report_dependencies=(world_spec_ref, verifier_ref),
                started=started,
                episodes=episodes,
                non_reachability_tool_calls=non_reachability_tool_calls,
                reachability_usage=reachability_usage,
                clean_build_seconds=clean_build_seconds,
                candidate_source_tree_digest=verified_source_tree_digest,
                release_profile=release_profile,
            )

        try:
            async with self.clean_builder.materialize(
                source_dir,
                expected_source_files=manifest.files,
                expected_source_tree_digest=manifest.candidate_source_tree_digest,
            ) as clean:
                clean_build_seconds = clean.install.duration_ms / 1000
                if clean.candidate_source_tree_digest != manifest.candidate_source_tree_digest:
                    raise CandidateBuildError(
                        "candidate_source_digest_mismatch",
                        "clean build changed the CandidateManifest source-tree digest",
                    )
                install_ref = self._evidence(
                    run_id,
                    "clean-install",
                    asdict(clean.install),
                    dependencies=(candidate_ref,),
                )
                evidence_refs.append(install_ref)

                supply_chain = self._supply_chain_gate(
                    run_id,
                    clean,
                    candidate_ref,
                    manifest,
                )
                self._record_gate(
                    gate_id="supply_chain",
                    status=supply_chain.status,
                    evidence_ref=supply_chain.evidence_ref,
                    summary=supply_chain.summary,
                    owner=supply_chain.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )

                static_assurance = await self._static_assurance_gate(
                    run_id,
                    clean,
                    candidate_ref,
                    manifest,
                )
                non_reachability_tool_calls += static_assurance.tool_calls
                self._record_gate(
                    gate_id="static_assurance",
                    status=static_assurance.status,
                    evidence_ref=static_assurance.evidence_ref,
                    summary=static_assurance.summary,
                    owner=static_assurance.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )

                if supply_chain.status != "pass" or static_assurance.status != "pass":
                    return self._finish(
                        run_id=run_id,
                        candidate_ref=candidate_ref,
                        gate_results=gate_results,
                        findings=findings,
                        evidence_refs=evidence_refs,
                        report_dependencies=(world_spec_ref, verifier_ref),
                        started=started,
                        episodes=episodes,
                        non_reachability_tool_calls=non_reachability_tool_calls,
                        reachability_usage=reachability_usage,
                        clean_build_seconds=clean_build_seconds,
                        candidate_source_tree_digest=verified_source_tree_digest,
                        release_profile=release_profile,
                    )

                public_status, public_ref, public_summary = await self._public_self_check_gate(
                    run_id,
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                )
                self._record_gate(
                    gate_id="public_self_check",
                    status=public_status,
                    evidence_ref=public_ref,
                    summary=public_summary,
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )

                (
                    protocol_status,
                    protocol_ref,
                    protocol_summary,
                    protocol_episodes,
                ) = await self._protocol_gate(
                    run_id,
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                    world_spec,
                    world_spec_ref,
                    verifier,
                    design,
                )
                episodes += protocol_episodes
                self._record_gate(
                    gate_id="runtime_protocol",
                    status=protocol_status,
                    evidence_ref=protocol_ref,
                    summary=protocol_summary,
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )

                materialization = await self._task_materialization_gate(
                    run_id,
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                    design,
                )
                episodes += materialization.episodes
                self._record_gate(
                    gate_id="task_materialization",
                    status=materialization.status,
                    evidence_ref=materialization.evidence_ref,
                    summary=materialization.summary,
                    owner=materialization.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )

                if materialization.status == "pass":
                    reachability = await self._task_reachability_gate(
                        run_id,
                        clean,
                        candidate,
                        candidate_ref,
                        manifest,
                        design,
                        verifier,
                        verifier_ref,
                        materialization.envelopes,
                        budget=budget,
                        reachability_workspace=reachability_workspace,
                    )
                else:
                    reachability_ref = self._evidence(
                        run_id,
                        "task-reachability",
                        {
                            "status": "inconclusive",
                            "reason": "task materialization did not produce trusted envelopes",
                            "materialized_instances": 0,
                        },
                        dependencies=(candidate_ref, materialization.evidence_ref),
                    )
                    reachability = _ReachabilityGateResult(
                        "inconclusive",
                        reachability_ref,
                        "Reachability was not attempted because materialization failed.",
                        0,
                        BudgetUsage(),
                        materialization.owner,
                    )
                episodes += reachability.episodes
                reachability_usage = _add_usage(reachability_usage, reachability.usage)
                self._record_gate(
                    gate_id="task_reachability",
                    status=reachability.status,
                    evidence_ref=reachability.evidence_ref,
                    summary=reachability.summary,
                    owner=reachability.owner,
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )
                for task_type in reachability.recipe_rework_task_types:
                    findings.append(
                        self._finding(
                            run_id,
                            "solve_recipe_rework",
                            candidate_ref,
                            reachability.evidence_ref,
                            owner="verifier",
                            summary=(
                                f"Task {task_type} was reachable only through the independent "
                                "interactive fallback."
                            ),
                            suggested_repair=(
                                "Revise the Challenger-authored parameterized solve recipe; "
                                "the candidate Runtime already passed reachability."
                            ),
                            blocks_release=False,
                        )
                    )

                behavior_cases = tuple(
                    case for case in verifier.cases if case.partition in {"public", "repair"}
                )
                behavior = await self._case_gate(
                    run_id,
                    "behavior",
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                    behavior_cases,
                    verifier_ref,
                    design,
                )
                episodes += behavior[3]
                non_reachability_tool_calls += behavior[4]
                self._record_gate(
                    gate_id="behavior",
                    status=behavior[0],
                    evidence_ref=behavior[1],
                    summary=behavior[2],
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )

                sealed_cases = tuple(case for case in verifier.cases if case.partition == "sealed")
                sealed = await self._case_gate(
                    run_id,
                    "sealed-release",
                    clean,
                    candidate,
                    candidate_ref,
                    manifest,
                    sealed_cases,
                    verifier_ref,
                    design,
                )
                episodes += sealed[3]
                non_reachability_tool_calls += sealed[4]
                self._record_gate(
                    gate_id="sealed_release",
                    status=sealed[0],
                    evidence_ref=sealed[1],
                    summary=sealed[2],
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                    disclosure="sealed_summary",
                )

                deployment = await self._deployment_gate(
                    run_id,
                    clean,
                    candidate,
                    candidate_ref,
                    install_ref,
                    manifest,
                    verifier,
                    design,
                )
                episodes += deployment[3]
                non_reachability_tool_calls += deployment[4]
                self._record_gate(
                    gate_id="clean_deployment",
                    status=deployment[0],
                    evidence_ref=deployment[1],
                    summary=deployment[2],
                    owner="build",
                    candidate_ref=candidate_ref,
                    release_profile=release_profile,
                    gate_results=gate_results,
                    evidence_refs=evidence_refs,
                    findings=findings,
                    run_id=run_id,
                )
        except CandidateBuildError as exc:
            if exc.record is not None:
                clean_build_seconds = exc.record.duration_ms / 1000
            value = (
                asdict(exc.record)
                if exc.record is not None
                else {
                    "status": "fail",
                    "failure_class": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                }
            )
            build_ref = self._evidence(
                run_id,
                "clean-install",
                value,
                dependencies=(candidate_ref,),
            )
            self._record_gate(
                gate_id="clean_deployment",
                status="fail",
                evidence_ref=build_ref,
                summary="Candidate failed its frozen offline build.",
                owner="build",
                candidate_ref=candidate_ref,
                release_profile=release_profile,
                gate_results=gate_results,
                evidence_refs=evidence_refs,
                findings=findings,
                run_id=run_id,
            )
        except (IsolationUnavailable, JudgeInfrastructureError) as exc:
            infrastructure_ref = self._evidence(
                run_id,
                "judge-infrastructure",
                {"status": "error", "code": exc.code, "message": str(exc)},
                dependencies=(candidate_ref,),
            )
            self._record_gate(
                gate_id="clean_deployment",
                status="error",
                evidence_ref=infrastructure_ref,
                summary="Required Judge infrastructure failed; no candidate PASS was inferred.",
                owner="judge_infrastructure",
                candidate_ref=candidate_ref,
                release_profile=release_profile,
                gate_results=gate_results,
                evidence_refs=evidence_refs,
                findings=findings,
                run_id=run_id,
            )

        return self._finish(
            run_id=run_id,
            candidate_ref=candidate_ref,
            gate_results=gate_results,
            findings=findings,
            evidence_refs=evidence_refs,
            report_dependencies=(world_spec_ref, verifier_ref),
            started=started,
            episodes=episodes,
            non_reachability_tool_calls=non_reachability_tool_calls,
            reachability_usage=reachability_usage,
            clean_build_seconds=clean_build_seconds,
            candidate_source_tree_digest=verified_source_tree_digest,
            release_profile=release_profile,
        )

    def _supply_chain_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
    ) -> _AssuranceGateResult:
        lineage: ImplementationLineage | None = None
        try:
            lineage = self.artifacts.get_json(
                manifest.implementation_lineage_ref,
                ImplementationLineage,
            )
            self.artifacts.require_exact_json(
                manifest.implementation_lineage_ref,
                lineage,
                artifact_types=("build.implementation_lineage",),
            )
        except (ArtifactStoreError, ValidationError):
            lineage = None

        evidence = inspect_supply_chain(
            evidence_id=f"{run_id}:supply-chain",
            candidate_ref=candidate_ref,
            root=clean.root,
            manifest=manifest,
            implementation_lineage_ref=manifest.implementation_lineage_ref,
            implementation_lineage=lineage,
            installed_tree_hash=clean.installed_tree_hash,
        )
        evidence_ref = self._typed_evidence(
            run_id,
            "supply-chain",
            "judge.supply_chain_evidence",
            evidence,
            dependencies=(
                candidate_ref,
                manifest.implementation_lineage_ref,
            ),
        )
        if evidence.status == "pass":
            summary = (
                "Exact uv lock, clean installed metadata, wheel provenance, and licenses "
                "form a closed supply chain."
            )
        else:
            summary = "Supply-chain assurance failed: " + ", ".join(evidence.failure_codes)
        return _AssuranceGateResult(
            status=evidence.status,
            evidence_ref=evidence_ref,
            summary=summary,
            owner="build",
        )

    async def _static_assurance_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
    ) -> _AssuranceGateResult:
        inspection = inspect_static_sources(clean.root, manifest)
        failures = set(inspection.failure_codes)
        pairs, binding_failures = self._bind_public_tests(manifest)
        failures.update(binding_failures)
        visible_paths = tuple(sorted(item.path for item in manifest.files))

        async def execute(
            path: str,
            ref: ArtifactRef,
        ) -> PublicTestExecution:
            argv = (".venv/bin/python", path)
            result = await self.sandbox_runner.run(
                clean.root,
                argv=argv,
                visible_workspace_paths=visible_paths,
                timeout_seconds=min(30.0, self.sandbox_runner.timeout_seconds),
                max_output_bytes=min(256 * 1024, self.sandbox_runner.max_output_bytes),
                failure_prefix="public_test",
            )
            failure_class = result.failure_class or (
                None if result.succeeded else "public_test_failed"
            )
            return PublicTestExecution(
                path=path,
                public_test_ref=ref,
                argv=argv,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                stdout_hash=sha256_digest(result.stdout.encode("utf-8")),
                stderr_hash=sha256_digest(result.stderr.encode("utf-8")),
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                passed=result.succeeded,
                failure_class=failure_class,
            )

        executions = tuple(await asyncio.gather(*(execute(path, ref) for path, ref in pairs)))
        if not executions:
            failures.add("static_public_tests_missing")
        if any(not item.passed for item in executions):
            failures.add("static_public_test_failed")
        passed = (
            inspection.forbidden_pattern_scan_passed
            and inspection.secret_scan_passed
            and inspection.strict_data_parse_passed
            and inspection.python_compile_passed
            and bool(executions)
            and all(item.passed for item in executions)
            and not failures
        )
        evidence = StaticAssuranceEvidence(
            evidence_id=f"{run_id}:static-assurance",
            candidate_ref=candidate_ref,
            candidate_source_tree_digest=manifest.candidate_source_tree_digest,
            status="pass" if passed else "fail",
            files=inspection.files,
            public_tests=executions,
            forbidden_pattern_scan_passed=inspection.forbidden_pattern_scan_passed,
            secret_scan_passed=inspection.secret_scan_passed,
            strict_data_parse_passed=inspection.strict_data_parse_passed,
            python_compile_passed=inspection.python_compile_passed,
            failure_codes=tuple(sorted(failures)),
        )
        evidence_ref = self._typed_evidence(
            run_id,
            "static-assurance",
            "judge.static_assurance_evidence",
            evidence,
            dependencies=(candidate_ref, *manifest.public_test_refs),
        )
        if evidence.status == "pass":
            summary = (
                "Framework AST/compile, strict data parsing, scans, and isolated public tests "
                "passed."
            )
        else:
            failed_public_tests = tuple(
                item.path for item in evidence.public_tests if not item.passed
            )
            summary = "Static assurance failed: " + ", ".join(evidence.failure_codes)
            if failed_public_tests:
                summary += "; failed public tests: " + ", ".join(failed_public_tests)
        return _AssuranceGateResult(
            status=evidence.status,
            evidence_ref=evidence_ref,
            summary=summary,
            owner="build",
            tool_calls=len(executions),
        )

    def _bind_public_tests(
        self,
        manifest: CandidateManifest,
    ) -> tuple[tuple[tuple[str, ArtifactRef], ...], tuple[str, ...]]:
        failures: set[str] = set()
        files = sorted(
            (item for item in manifest.files if item.role == "public_test"),
            key=lambda item: item.path,
        )
        refs = manifest.public_test_refs
        if not files or not refs:
            return (), ("static_public_tests_missing",)
        if len(files) > MAX_PUBLIC_TESTS or len(refs) > MAX_PUBLIC_TESTS:
            failures.add("static_public_test_limit_exceeded")
        if len(files) != len(refs):
            failures.add("static_public_test_binding_invalid")

        remaining = list(files)
        pairs: list[tuple[str, ArtifactRef]] = []
        for ref in refs[:MAX_PUBLIC_TESTS]:
            try:
                if ref.artifact_type != "build.public_test":
                    raise ArtifactStoreError("public test ref has the wrong artifact type")
                data = self.artifacts.get_blob(ref)
                if sha256_digest(data) != ref.content_hash:
                    raise ArtifactStoreError("public test artifact content changed")
                match = next(
                    (
                        item
                        for item in remaining
                        if item.content_hash == ref.content_hash and item.size_bytes == len(data)
                    ),
                    None,
                )
                if match is None:
                    raise ArtifactStoreError("public test ref is not bound to a manifest file")
                remaining.remove(match)
                pairs.append((match.path, ref))
            except ArtifactStoreError:
                failures.add("static_public_test_binding_invalid")
        if remaining:
            failures.add("static_public_test_binding_invalid")
        return tuple(pairs), tuple(sorted(failures))

    async def _public_self_check_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
    ) -> tuple[GateStatus, ArtifactRef, str]:
        descriptor = candidate.public_self_check
        result = await self.sandbox_runner.run(
            clean.root,
            argv=descriptor.argv,
            visible_workspace_paths=self._role_visible_paths(manifest, "public_verifier"),
            timeout_seconds=descriptor.timeout_seconds,
            max_output_bytes=descriptor.max_output_bytes,
            failure_prefix="public_self_check",
        )
        passed = result.succeeded
        evidence_ref = self._evidence(
            run_id,
            "public-self-check",
            {
                "status": "pass" if passed else "fail",
                "protocol": descriptor.protocol,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "failure_class": result.failure_class,
                "stdout_hash": sha256_digest(result.stdout.encode()),
                "stderr_hash": sha256_digest(result.stderr.encode()),
                "network": "disabled",
                "workspace": "read-only",
            },
            dependencies=(candidate_ref, candidate.public_verifier_ref),
        )
        return (
            "pass" if passed else "fail",
            evidence_ref,
            "Public self-check passed in the clean sandbox."
            if passed
            else "Public self-check failed in the clean sandbox.",
        )

    async def _integration_protocol_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
        world_spec: WorldSpec,
        world_spec_ref: ArtifactRef,
    ) -> tuple[GateStatus, ArtifactRef, str]:
        """Verify the exact Runtime surface without consuming a Verifier case."""

        try:
            async with self._supervisor(clean, candidate, manifest) as supervisor:
                response = supervisor.handshake_response
                if response is None or not response.ok or response.result is None:
                    raise _CandidateTaskFailure("Runtime handshake did not succeed")
                raw_tools = response.result["tools"]
                mismatch_paths = _runtime_contract_mismatch_paths(raw_tools, world_spec)
                if mismatch_paths:
                    raise _RuntimeContractFailure(mismatch_paths)
                expected = {item.surface.tool_id: item.surface for item in world_spec.tools}
            record: dict[str, Any] = {
                "status": "pass",
                "tool_ids": sorted(expected),
                "contract_match": "exact",
            }
            status: GateStatus = "pass"
            summary = "Runtime handshake exactly matches the frozen WorldSpec."
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            failure_summary = _candidate_failure_summary(exc)
            record = {
                "status": "fail",
                "failure_class": type(exc).__name__,
                "message": failure_summary,
            }
            if isinstance(exc, ProtocolViolation):
                record["protocol_code"] = exc.code
                record["protocol_details"] = dict(exc.details)
            if isinstance(exc, _RuntimeContractFailure):
                record["mismatch_paths"] = list(exc.mismatch_paths)
            status = "fail"
            summary = failure_summary
        evidence_ref = self._evidence(
            run_id,
            "integration-runtime-protocol",
            record,
            dependencies=(candidate_ref, world_spec_ref),
        )
        return status, evidence_ref, summary

    async def _protocol_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
        world_spec: WorldSpec,
        world_spec_ref: ArtifactRef,
        verifier: VerifierIR,
        design: EnvironmentDesign,
    ) -> tuple[GateStatus, ArtifactRef, str, int]:
        episodes = 0
        try:
            async with self._supervisor(clean, candidate, manifest) as supervisor:
                response = supervisor.handshake_response
                if response is None or not response.ok or response.result is None:
                    raise _CandidateTaskFailure("Runtime handshake did not succeed")
                raw_tools = response.result["tools"]
                mismatch_paths = _runtime_contract_mismatch_paths(raw_tools, world_spec)
                if mismatch_paths:
                    raise _RuntimeContractFailure(mismatch_paths)
                expected = {item.surface.tool_id: item.surface for item in world_spec.tools}

            base_case = verifier.cases[0]
            seed_count = design.verification.minimum_unknown_seed_episodes
            seeds = tuple(
                int.from_bytes(
                    hashlib.sha256(f"{run_id}\0protocol\0{index}".encode()).digest()[:8],
                    "big",
                )
                for index in range(seed_count)
            )
            views: list[dict[str, JsonValue]] = []
            for seed in seeds:
                views.append(
                    await self._reset_probe(
                        clean,
                        candidate,
                        manifest,
                        seed,
                        base_case.actor,
                        base_case.reset_config,
                        design,
                    )
                )
                episodes += 1
            replay = await self._reset_probe(
                clean,
                candidate,
                manifest,
                seeds[0],
                base_case.actor,
                base_case.reset_config,
                design,
            )
            episodes += 1
            if canonical_json_bytes(views[0]) != canonical_json_bytes(replay):
                raise _CandidateTaskFailure("same-seed reset differs after Runtime restart")
            if len({str(item["state_digest"]) for item in views}) < 2:
                raise _CandidateTaskFailure("unknown seeds do not alter Runtime state")
            record = {
                "status": "pass",
                "tool_ids": sorted(expected),
                "unknown_seed_probe_count": seed_count,
                "same_seed_restart_replay": "exact",
            }
            status: GateStatus = "pass"
            summary = "Runtime handshake and reproducible unknown-seed lifecycle passed."
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            failure_summary = _candidate_failure_summary(exc)
            record = {
                "status": "fail",
                "failure_class": type(exc).__name__,
                "message": failure_summary,
            }
            if isinstance(exc, ProtocolViolation):
                record["protocol_code"] = exc.code
                record["protocol_details"] = dict(exc.details)
            if isinstance(exc, _RuntimeContractFailure):
                record["mismatch_paths"] = list(exc.mismatch_paths)
            status = "fail"
            summary = failure_summary
        evidence_ref = self._evidence(
            run_id,
            "runtime-protocol",
            record,
            dependencies=(candidate_ref, world_spec_ref),
        )
        return status, evidence_ref, summary, episodes

    async def _task_materialization_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
        design: EnvironmentDesign,
    ) -> _MaterializationGateResult:
        episodes = 0
        calls: tuple[TaskMaterializerCall, ...] = ()
        try:
            schema, curriculum = self._load_task_contract(candidate)
            if curriculum != design.curriculum:
                raise _CandidateTaskFailure(
                    "candidate curriculum differs from its frozen EnvironmentDesign"
                )
            compiler = TaskMaterializerV3Compiler(curriculum)
            if canonical_json_bytes(schema) != canonical_json_bytes(compiler.output_schema):
                raise _CandidateTaskFailure(
                    "candidate output schema differs from the framework-compiled v3 schema"
                )
            calls = self._task_materializer_calls(
                run_id=run_id,
                candidate_ref=candidate_ref,
                curriculum=curriculum,
            )
            payload_calls = tuple(
                call.model_dump(mode="json", exclude={"schema_version"}) for call in calls
            )
            first_result = await self.sandbox_runner.run_task_materializer(
                clean.root,
                entrypoint=candidate.task_materializer.entrypoint,
                calls=payload_calls,
                visible_workspace_paths=self._role_visible_paths(manifest, "task_materializer"),
            )
            second_result = await self.sandbox_runner.run_task_materializer(
                clean.root,
                entrypoint=candidate.task_materializer.entrypoint,
                calls=payload_calls,
                visible_workspace_paths=self._role_visible_paths(manifest, "task_materializer"),
            )
            first = self._task_runner_outputs(first_result, expected_count=len(calls))
            second = self._task_runner_outputs(second_result, expected_count=len(calls))
            if canonical_json_bytes(first) != canonical_json_bytes(second):
                raise _CandidateTaskFailure(
                    "Task Materializer is not deterministic across isolated invocations"
                )
            envelopes = tuple(
                compiler.materialize(call, output)
                for call, output in zip(calls, first, strict=True)
            )
            task_hashes: dict[str, set[str]] = {
                requirement.task_type: set() for requirement in curriculum.task_types
            }
            initial_hashes: dict[str, set[str]] = {
                requirement.task_type: set() for requirement in curriculum.task_types
            }
            for envelope in envelopes:
                task_type = envelope.call.task_type
                task_hashes[task_type].add(envelope.materializer_digest)
                initial_hashes[task_type].add(
                    sha256_digest(canonical_json_bytes(envelope.materialization.initial_config))
                )
            for requirement in curriculum.task_types:
                if len(initial_hashes[requirement.task_type]) < (
                    curriculum.minimum_distinct_initial_states
                ):
                    raise _CandidateTaskFailure(
                        f"task {requirement.task_type} lacks distinct initial configurations"
                    )
                if len(task_hashes[requirement.task_type]) < (
                    curriculum.minimum_distinct_tasks_per_type
                ):
                    raise _CandidateTaskFailure(
                        f"task {requirement.task_type} lacks distinct materializations"
                    )

            contrasts = find_difficulty_contrast_candidates(
                envelopes=envelopes,
                curriculum=curriculum,
            )
            requirements = {item.task_type: item for item in curriculum.task_types}
            runtime_initial_views: dict[int, tuple[str, JsonValue]] = {}
            for index, envelope in enumerate(envelopes):
                async with self._episode_driver(
                    clean,
                    candidate,
                    manifest,
                    envelope,
                    design,
                ) as driver:
                    episodes += 1
                    runtime_initial_views[index] = (
                        driver.final_state_digest,
                        driver.reset_observation,
                    )
                    snapshot = driver._pre_snapshot
                    context = RuleExecutionContext(
                        actor=envelope.call.actor,
                        pre_state=snapshot["observation"],
                        post_state=snapshot["observation"],
                        args={},
                        tool_result=None,
                        error=None,
                        observation=snapshot["observation"],
                        events=[],
                        reset_config=envelope.materialization.initial_config,
                        task_goal=envelope.evaluator_goal,
                        seed=envelope.call.seed,
                        terminated=False,
                        truncated=False,
                    )
                    requirement = requirements[envelope.call.task_type]
                    for rule in (
                        *design.world_spec.invariants,
                        *design.world_spec.state.initial_state_constraints,
                        *requirement.initial_state_constraints,
                        *design.curriculum.sampling_constraints,
                    ):
                        if not evaluate_rule(rule, context).result:
                            raise _CandidateTaskFailure(
                                f"materialized task violates framework Rule {rule.rule_id}"
                            )
            difficulty_evidence = self._validate_runtime_difficulty_contrasts(
                contrasts,
                runtime_initial_views,
            )
            record = {
                "status": "pass",
                "protocol": candidate.task_materializer.protocol,
                "callable": "materialize(seed, task_type, actor, difficulty)",
                "materialized_count": len(envelopes),
                "deterministic_replay_count": len(second),
                "task_type_counts": dict(
                    sorted(Counter(item.call.task_type for item in envelopes).items())
                ),
                "distinct_initial_config_counts": {
                    key: len(value) for key, value in sorted(initial_hashes.items())
                },
                "distinct_materialization_counts": {
                    key: len(value) for key, value in sorted(task_hashes.items())
                },
                "difficulty_contrasts": difficulty_evidence,
                "runtime_reset_count": episodes,
                "call_campaign_commitment": sha256_digest(
                    canonical_json_bytes([call.model_dump(mode="json") for call in calls])
                ),
                "candidate_output_fields": [
                    "schema_version",
                    "task_schema_version",
                    "seed",
                    "task_type",
                    "actor",
                    "difficulty",
                    "public_goal",
                    "initial_config",
                ],
                "framework_owned_fields": ["public_instruction", "evaluator_goal"],
                "runtime_received_fields": ["seed", "actor", "initial_config"],
                "network": "disabled",
                "workspace": "read-only",
            }
            status: GateStatus = "pass"
            summary = (
                "Task Materializer v3 passed exact echo, closed schema, deterministic rendering, "
                "diversity, difficulty and real Runtime initial-state checks."
            )
            owner: FindingOwner = "build"
        except (
            TaskMaterializationError,
            GeneratedTaskSemanticError,
            _CandidateTaskFailure,
            ProtocolViolation,
            RuntimeProcessCrashed,
            RuntimeRequestTimeout,
            ValidationError,
        ) as exc:
            record = {
                "status": "fail",
                "failure_class": type(exc).__name__,
                "framework_call_count": len(calls),
                "runtime_reset_count": episodes,
                "candidate_output_authority": "public_goal_and_initial_config_only",
            }
            status = "fail"
            summary = str(exc)
            owner = "build"
            envelopes = ()
        except JudgeInfrastructureError as exc:
            record = {
                "status": "error",
                "failure_class": exc.code,
                "framework_call_count": len(calls),
            }
            status = "error"
            summary = str(exc)
            owner = "judge_infrastructure"
            envelopes = ()
        evidence_ref = self._evidence(
            run_id,
            "task-materialization",
            record,
            dependencies=(
                candidate_ref,
                candidate.task_materializer.output_schema_ref,
                candidate.task_materializer.curriculum_ref,
            ),
        )
        return _MaterializationGateResult(
            status,
            evidence_ref,
            summary,
            episodes,
            envelopes,
            owner,
        )

    async def _task_reachability_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
        design: EnvironmentDesign,
        verifier: VerifierIR,
        verifier_ref: ArtifactRef,
        envelopes: tuple[FrameworkTaskEnvelope, ...],
        *,
        budget: Budget,
        reachability_workspace: Path,
    ) -> _ReachabilityGateResult:
        recipes = self._recipe_index(verifier.solve_recipes)
        requirements = {item.task_type: item for item in design.curriculum.task_types}
        certificates: list[ReachabilityCertificate] = []
        task_type_counts: Counter[str] = Counter()
        strategy_counts: Counter[str] = Counter()
        failure_classes: Counter[str] = Counter()
        failure_codes: Counter[str] = Counter()
        usage = BudgetUsage()
        episodes = 0
        terminal_status: GateStatus = "pass"
        terminal_owner: FindingOwner = "verifier"
        recipe_rework_task_types: set[str] = set()

        for envelope in envelopes:
            requirement = requirements[envelope.call.task_type]
            policy = requirement.reachability_policy
            task_type_counts[envelope.call.task_type] += 1
            outcome: ReachabilityOutcome | None = None
            used_strategy: Literal["parameterized_recipe", "interactive_challenger"] | None = None
            recipe = recipes.get(envelope.call.task_type)
            if recipe is not None:
                episodes += 1
                try:
                    async with self._episode_driver(
                        clean,
                        candidate,
                        manifest,
                        envelope,
                        design,
                    ) as driver:
                        async with asyncio.timeout(policy.maximum_wall_seconds_per_attempt):
                            outcome = await ParameterizedRecipeStrategy(
                                maximum_steps=policy.maximum_steps_per_attempt
                            ).solve(
                                driver=driver,
                                recipe=recipe,
                                required_tool_ids=requirement.required_tool_ids,
                                minimum_tool_calls=requirement.minimum_tool_calls,
                            )
                        if outcome.certified:
                            certificates.append(
                                self._certificate(
                                    candidate,
                                    candidate_ref,
                                    design,
                                    envelope,
                                    driver.final_state_digest,
                                    outcome,
                                    strategy="parameterized_recipe",
                                    strategy_version=ParameterizedRecipeStrategy.strategy_version,
                                )
                            )
                            strategy_counts["parameterized_recipe"] += 1
                            used_strategy = "parameterized_recipe"
                        usage = _add_usage(usage, outcome.usage)
                except (
                    ProtocolViolation,
                    RuntimeProcessCrashed,
                    RuntimeRequestTimeout,
                    ValueError,
                ) as exc:
                    outcome = _candidate_outcome(str(exc))
                except TimeoutError:
                    outcome = _budget_outcome(
                        "recipe_wall_budget_exhausted",
                        "parameterized recipe exceeded its task-local wall budget",
                    )
                except JudgeInfrastructureError as exc:
                    outcome = _infrastructure_outcome(exc.code, str(exc))

            if used_strategy is None:
                if outcome is not None and outcome.failure_classification == "candidate":
                    pass
                elif outcome is not None and outcome.failure_classification != "recipe":
                    pass
                elif recipe is not None and policy.maximum_solver_attempts < 2:
                    outcome = _inconclusive_recipe_outcome(
                        "recipe_failed_without_fallback_budget",
                        "recipe failed and policy reserved no interactive fallback attempt",
                    )
                else:
                    (
                        interactive_outcome,
                        interactive_final_digest,
                        interactive_episode_started,
                    ) = await self._run_interactive_attempt(
                        run_id=run_id,
                        clean=clean,
                        candidate=candidate,
                        manifest=manifest,
                        envelope=envelope,
                        design=design,
                        requirement=requirement,
                        budget=self._solver_attempt_budget(policy, budget),
                        reachability_workspace=reachability_workspace,
                    )
                    episodes += int(interactive_episode_started)
                    usage = _add_usage(usage, interactive_outcome.usage)
                    outcome = interactive_outcome
                    if interactive_outcome.certified and interactive_final_digest is not None:
                        certificates.append(
                            self._certificate(
                                candidate,
                                candidate_ref,
                                design,
                                envelope,
                                interactive_final_digest,
                                interactive_outcome,
                                strategy="interactive_challenger",
                                strategy_version=(InteractiveChallengerStrategy.strategy_version),
                            )
                        )
                        strategy_counts["interactive_challenger"] += 1
                        used_strategy = "interactive_challenger"
                        if recipe is not None:
                            recipe_rework_task_types.add(envelope.call.task_type)

            if used_strategy is not None:
                continue
            assert outcome is not None
            failure_class = outcome.failure_classification or "infrastructure"
            failure_code = outcome.failure_code or "unclassified_reachability_failure"
            failure_classes[failure_class] += 1
            failure_codes[failure_code] += 1
            status, owner = _reachability_failure_route(outcome)
            terminal_status, terminal_owner = _worse_reachability_route(
                (terminal_status, terminal_owner),
                (status, owner),
            )

        commitment_inputs = [certificate.content_digest() for certificate in certificates]
        commitment_inputs.extend(
            f"failure:{key}:{value}" for key, value in sorted(failure_codes.items())
        )
        campaign_commitment = sha256_digest(canonical_json_bytes(commitment_inputs))
        failed_count = len(envelopes) - len(certificates)
        serve_policy_counts = Counter(
            requirements[envelope.call.task_type].reachability_policy.mode for envelope in envelopes
        )
        public_serve_policy_counts = {str(key): value for key, value in serve_policy_counts.items()}
        if terminal_status == "pass" and failed_count == 0:
            public_evidence = ReachabilityPublicEvidence(
                campaign_commitment=campaign_commitment,
                candidate_ref=candidate_ref,
                materialized_instances=len(envelopes),
                certified_instances=len(certificates),
                failed_instances=failed_count,
                task_type_counts=dict(task_type_counts),
                strategy_counts=dict(strategy_counts),
                serve_policy_counts=public_serve_policy_counts,
                budget_usage=usage,
            )
            evidence_ref = self.artifacts.put_json(
                artifact_id=f"{run_id}:task-reachability-public-evidence",
                artifact_type="judge.reachability_public_evidence",
                value=public_evidence,
                dependencies=(candidate_ref, verifier_ref),
            )
        else:
            record: dict[str, Any] = {
                "status": terminal_status,
                "release_claim": "no-reachability-claim",
                "campaign_commitment": campaign_commitment,
                "candidate_ref": candidate_ref.model_dump(mode="json"),
                "materialized_instances": len(envelopes),
                "certified_instances": 0,
                "failed_instances": failed_count,
                "task_type_counts": dict(task_type_counts),
                "strategy_counts": {},
                "serve_policy_counts": public_serve_policy_counts,
                "budget_usage": usage.model_dump(mode="json"),
                "failure_class_counts": dict(sorted(failure_classes.items())),
                "failure_code_counts": dict(sorted(failure_codes.items())),
            }
            evidence_ref = self._evidence(
                run_id,
                "task-reachability",
                record,
                dependencies=(candidate_ref, verifier_ref),
            )
        if terminal_status == "pass" and failed_count == 0:
            summary = (
                f"{len(certificates)}/{len(envelopes)} materialized tasks reached trusted "
                "terminal success in fresh real Runtime episodes."
            )
        else:
            summary = (
                f"Reachability certified {len(certificates)}/{len(envelopes)} tasks; "
                "no unproven task can pass the hard gate."
            )
        return _ReachabilityGateResult(
            terminal_status,
            evidence_ref,
            summary,
            episodes,
            usage,
            terminal_owner,
            tuple(sorted(recipe_rework_task_types)),
        )

    async def _run_interactive_attempt(
        self,
        *,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        manifest: CandidateManifest,
        envelope: FrameworkTaskEnvelope,
        design: EnvironmentDesign,
        requirement: TaskRequirement,
        budget: Budget,
        reachability_workspace: Path,
    ) -> tuple[ReachabilityOutcome, str | None, bool]:
        if self.interactive_challenger is None:
            return (
                _infrastructure_outcome(
                    "interactive_solver_not_configured",
                    "real InvocationBackend, solver profile, workspace and budget are required",
                    status="inconclusive",
                ),
                None,
                False,
            )
        manager = self._episode_driver(
            clean,
            candidate,
            manifest,
            envelope,
            design,
        )
        try:
            driver = await manager.__aenter__()
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            return _candidate_outcome(str(exc)), None, True
        except JudgeInfrastructureError as exc:
            return _infrastructure_outcome(exc.code, str(exc)), None, True
        try:
            async with asyncio.timeout(
                requirement.reachability_policy.maximum_wall_seconds_per_attempt
            ):
                outcome = await self.interactive_challenger.solve(
                    driver=driver,
                    lineage_id=(
                        f"{run_id}:reachability:{envelope.call.task_type}:"
                        f"{envelope.materializer_digest.removeprefix('sha256:')[:24]}"
                    ),
                    workspace=reachability_workspace,
                    budget=budget,
                    required_tool_ids=requirement.required_tool_ids,
                    minimum_tool_calls=requirement.minimum_tool_calls,
                    maximum_agent_turns=(
                        requirement.reachability_policy.maximum_agent_turns_per_attempt
                    ),
                    maximum_steps=(requirement.reachability_policy.maximum_steps_per_attempt),
                )
            return outcome, driver.final_state_digest, True
        except TimeoutError:
            return (
                _budget_outcome(
                    "interactive_solver_wall_budget_exhausted",
                    "interactive Challenger exceeded its task-local wall budget",
                ),
                None,
                True,
            )
        finally:
            await manager.__aexit__(None, None, None)

    @asynccontextmanager
    async def _episode_driver(
        self,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        manifest: CandidateManifest,
        envelope: FrameworkTaskEnvelope,
        design: EnvironmentDesign,
    ) -> AsyncIterator[_RealEpisodeDriver]:
        async with self._supervisor(clean, candidate, manifest) as supervisor:
            reset = await supervisor.reset(
                seed=envelope.call.seed,
                actor=envelope.call.actor,
                config=envelope.materialization.initial_config,
            )
            if not reset.ok or reset.result is None:
                raise _CandidateTaskFailure("Runtime rejected a v3 materialized initial_config")
            initialization_failures: list[str] = []
            try:
                self._validate_reset_observation(
                    reset.result["observation"],
                    envelope.call.actor,
                    design,
                )
            except ValueError as exc:
                initialization_failures.append(str(exc))
            snapshot_response = await supervisor.snapshot()
            if not snapshot_response.ok or snapshot_response.result is None:
                raise _CandidateTaskFailure("Runtime could not snapshot its initial state")
            snapshot = dict(snapshot_response.result)
            try:
                self._validate_state_snapshot(snapshot, design)
            except ValueError as exc:
                initialization_failures.append(str(exc))
            if reset.result["state_digest"] != snapshot["state_digest"]:
                initialization_failures.append(
                    "Runtime reset and immediate snapshot state digests differ"
                )
            if initialization_failures:
                raise _CandidateTaskFailure("; ".join(initialization_failures))
            yield _RealEpisodeDriver(
                judge=self,
                supervisor=supervisor,
                envelope=envelope,
                reset_observation=reset.result["observation"],
                pre_snapshot=snapshot,
                design=design,
            )

    async def _case_gate(
        self,
        run_id: str,
        label: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
        cases: tuple[VerifierCase, ...],
        verifier_ref: ArtifactRef,
        design: EnvironmentDesign,
    ) -> tuple[GateStatus, ArtifactRef, str, int, int]:
        if not cases:
            evidence_ref = self._evidence(
                run_id,
                label,
                {"status": "fail", "reason": "no cases configured"},
                dependencies=(candidate_ref, verifier_ref),
            )
            return "fail", evidence_ref, f"{label} has no cases", 0, 0
        rules = design_rule_index(design)
        try:
            evaluations = tuple(
                [
                    await self._run_case(clean, candidate, manifest, case, design, rules)
                    for case in cases
                ]
            )
            results = tuple(item[0] for item in evaluations)
            tool_calls = sum(item[1] for item in evaluations)
            passed = all(item.passed for item in results)
            record = {
                "status": "pass" if passed else "fail",
                "partition": label,
                "case_count": len(results),
                "passed_count": sum(item.passed for item in results),
                "cases": (
                    [
                        self._sealed_case_projection(index, item)
                        for index, item in enumerate(results)
                    ]
                    if label == "sealed-release"
                    else [item.model_dump(mode="json") for item in results]
                ),
            }
            status: GateStatus = "pass" if passed else "fail"
            summary = f"{label}: {record['passed_count']}/{record['case_count']} cases passed."
        except JudgeInfrastructureError as exc:
            record = {"status": "error", "failure_class": exc.code}
            status = "error"
            summary = str(exc)
            tool_calls = 0
        evidence_ref = self._evidence(
            run_id,
            label,
            record,
            dependencies=(candidate_ref, verifier_ref),
        )
        return status, evidence_ref, summary, len(cases), tool_calls

    async def _run_case(
        self,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        manifest: CandidateManifest,
        case: VerifierCase,
        design: EnvironmentDesign,
        rules: dict[str, Rule],
    ) -> tuple[CaseEvaluation, int]:
        observations: list[RuntimeActionObservation] = []
        contexts: list[RuleExecutionContext] = []
        tool_calls = 0
        try:
            async with self._supervisor(clean, candidate, manifest) as supervisor:
                reset = await supervisor.reset(
                    seed=case.seed,
                    actor=case.actor,
                    config=case.reset_config,
                )
                if not reset.ok or reset.result is None:
                    raise _CandidateTaskFailure("Runtime rejected a valid verifier reset")
                self._validate_reset_observation(reset.result["observation"], case.actor, design)
                snapshot_response = await supervisor.snapshot()
                if not snapshot_response.ok or snapshot_response.result is None:
                    raise _CandidateTaskFailure("snapshot failed after verifier reset")
                before = dict(snapshot_response.result)
                self._validate_state_snapshot(before, design)
                tools = {tool.surface.tool_id: tool for tool in design.world_spec.tools}
                for index, action in enumerate(case.actions):
                    key = action.idempotency_key or self._idempotency_key(
                        case.seed,
                        index,
                        action.tool_id,
                    )
                    tool_calls += 1
                    response = await supervisor.invoke(
                        tool=action.tool_id,
                        args=action.arguments,
                        idempotency_key=key,
                    )
                    snapshot_response = await supervisor.snapshot()
                    if not snapshot_response.ok or snapshot_response.result is None:
                        raise _CandidateTaskFailure("snapshot failed after verifier action")
                    after = dict(snapshot_response.result)
                    self._validate_state_snapshot(after, design)
                    observation, context = self._observation(
                        index=index,
                        action=action,
                        idempotency_key=key,
                        response=response,
                        pre_snapshot=before,
                        post_snapshot=after,
                        reset_config=case.reset_config,
                        task_goal=case.evaluator_goal,
                        seed=case.seed,
                        actor=case.actor,
                        design=design,
                    )
                    self._validate_tool_semantics(
                        observation,
                        context,
                        tools[action.tool_id],
                        design,
                        rules,
                    )
                    trusted = evaluate_task_reward(design, case.task_type, context)
                    observations.append(
                        observation.model_copy(
                            update={
                                "trusted_reward": trusted.reward,
                                "trusted_terminated": trusted.terminated,
                                "trusted_succeeded": trusted.succeeded,
                                "trusted_failed": trusted.failed,
                            }
                        )
                    )
                    contexts.append(context)
                    before = after
            assertions = tuple(
                evaluate_assertion(assertion, rules[assertion.rule_id], tuple(contexts))
                for assertion in case.assertions
            )
            return (
                CaseEvaluation(
                    case_id=case.case_id,
                    partition=case.partition,
                    seed=case.seed,
                    passed=all(item.passed for item in assertions),
                    reset_ok=True,
                    actions=tuple(observations),
                    assertions=assertions,
                ),
                tool_calls,
            )
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            return (
                CaseEvaluation(
                    case_id=case.case_id,
                    partition=case.partition,
                    seed=case.seed,
                    passed=False,
                    reset_ok=bool(observations),
                    actions=tuple(observations),
                    assertions=(),
                    failure_class="runtime_execution_failed",
                    failure_summary=f"{type(exc).__name__}: {exc}",
                ),
                tool_calls,
            )

    async def _integration_deployment_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        install_ref: ArtifactRef,
        manifest: CandidateManifest,
        world_spec: WorldSpec,
        envelope: FrameworkTaskEnvelope,
    ) -> tuple[GateStatus, ArtifactRef, str, int, int]:
        """Run concurrent clean Runtime reset/invoke probes before Verifier exists.

        The Invoke need only produce a valid protocol success or error envelope.
        Semantic success and state-transition obligations remain Release Judge work.
        """

        requirement = next(
            item
            for item in self.artifacts.get_json(
                candidate.task_materializer.curriculum_ref,
                CurriculumRequirements,
            ).task_types
            if item.task_type == envelope.call.task_type
        )
        tool_id = requirement.required_tool_ids[0]
        surfaces = {item.surface.tool_id: item.surface for item in world_spec.tools}
        surface = surfaces[tool_id]
        arguments = self._minimal_schema_instance(surface.input_schema)
        if not isinstance(arguments, dict):
            arguments = {}
        if not Draft202012Validator(surface.input_schema).is_valid(arguments):
            # A schema-invalid call is still useful here: Runtime must return a
            # typed error instead of crashing. Release Judge later supplies
            # semantically valid, task-directed actions.
            arguments = {}

        async def probe(index: int) -> dict[str, JsonValue]:
            async with self._supervisor(clean, candidate, manifest) as supervisor:
                reset = await supervisor.reset(
                    seed=(envelope.call.seed + index) % (2**64),
                    actor=envelope.call.actor,
                    config=envelope.materialization.initial_config,
                )
                if not reset.ok or reset.result is None:
                    raise _CandidateTaskFailure("integration deployment reset failed")
                invoked = await supervisor.invoke(
                    tool=tool_id,
                    args=arguments,
                    idempotency_key=self._idempotency_key(
                        envelope.call.seed,
                        index,
                        "integration-deployment",
                    ),
                )
                if invoked.result is None and invoked.error is None:
                    raise _CandidateTaskFailure(
                        "integration invoke omitted both result and typed error"
                    )
                return {
                    "reset_state_digest": reset.result["state_digest"],
                    "invoke_ok": invoked.ok,
                    "invoke_error_code": invoked.error.code if invoked.error is not None else None,
                    "invoke_state_digest": (
                        invoked.result["state_digest"]
                        if invoked.result is not None
                        else reset.result["state_digest"]
                    ),
                }

        try:
            first, second = await asyncio.gather(probe(0), probe(1))
            record: dict[str, Any] = {
                "status": "pass",
                "clean_install": True,
                "tool_id": tool_id,
                "input_schema_valid": Draft202012Validator(surface.input_schema).is_valid(
                    arguments
                ),
                "concurrent_runtime_probes": [first, second],
                "teardown_observed": 2,
                "package_relative_launch": True,
                "semantic_authority": "none; Release Judge owns behavior claims",
            }
            status: GateStatus = "pass"
            summary = "Clean install and concurrent reset/invoke/teardown probes passed."
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            record = {
                "status": "fail",
                "failure_class": type(exc).__name__,
                "message": str(exc),
            }
            status = "fail"
            summary = str(exc)
        evidence_ref = self._evidence(
            run_id,
            "integration-deployment",
            record,
            dependencies=(candidate_ref, install_ref),
        )
        return status, evidence_ref, summary, 2, 2

    @classmethod
    def _minimal_schema_instance(cls, schema: Mapping[str, JsonValue]) -> JsonValue:
        """Deterministically synthesize a small schema-shaped smoke input."""

        if "const" in schema:
            return schema["const"]
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]
        if "default" in schema:
            return schema["default"]
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            schema_type = next((item for item in schema_type if item != "null"), "null")
        if schema_type == "object":
            properties = schema.get("properties")
            required = schema.get("required")
            if not isinstance(properties, dict) or not isinstance(required, list):
                return {}
            result: dict[str, JsonValue] = {}
            for name in required:
                if not isinstance(name, str):
                    continue
                child = properties.get(name)
                if isinstance(child, dict):
                    result[name] = cls._minimal_schema_instance(cast(dict[str, JsonValue], child))
            return result
        if schema_type == "array":
            items = schema.get("items")
            minimum = schema.get("minItems", 0)
            count = int(minimum) if isinstance(minimum, int) and minimum > 0 else 0
            child = cast(dict[str, JsonValue], items) if isinstance(items, dict) else {}
            return [cls._minimal_schema_instance(child) for _ in range(min(count, 8))]
        if schema_type == "string":
            minimum = schema.get("minLength", 1)
            length = int(minimum) if isinstance(minimum, int) and minimum > 0 else 1
            return "x" * min(length, 128)
        if schema_type == "integer":
            minimum = schema.get("minimum", 0)
            return int(minimum) if isinstance(minimum, (int, float)) else 0
        if schema_type == "number":
            minimum = schema.get("minimum", 0)
            return float(minimum) if isinstance(minimum, (int, float)) else 0.0
        if schema_type == "boolean":
            return False
        return None

    async def _deployment_gate(
        self,
        run_id: str,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        install_ref: ArtifactRef,
        manifest: CandidateManifest,
        verifier: VerifierIR,
        design: EnvironmentDesign,
    ) -> tuple[GateStatus, ArtifactRef, str, int, int]:
        base_case = verifier.cases[0]
        base_action = base_case.actions[0]
        tool_calls = 0

        async def probe(index: int) -> dict[str, JsonValue]:
            nonlocal tool_calls
            async with self._supervisor(clean, candidate, manifest) as supervisor:
                reset = await supervisor.reset(
                    seed=(base_case.seed + index) % (2**64),
                    actor=base_case.actor,
                    config=base_case.reset_config,
                )
                if not reset.ok or reset.result is None:
                    raise _CandidateTaskFailure("parallel deployment reset failed")
                tool_calls += 1
                invoked = await supervisor.invoke(
                    tool=base_action.tool_id,
                    args=base_action.arguments,
                    idempotency_key=self._idempotency_key(base_case.seed, index, "deployment"),
                )
                if invoked.result is None:
                    raise _CandidateTaskFailure("parallel deployment invoke failed")
                return {
                    "reset_state_digest": reset.result["state_digest"],
                    "invoke_state_digest": invoked.result["state_digest"],
                }

        try:
            first, second = await asyncio.gather(probe(0), probe(1))
            record = {
                "status": "pass",
                "clean_install": True,
                "concurrent_runtime_probes": [first, second],
                "teardown_observed": 2,
                "package_relative_launch": True,
            }
            status: GateStatus = "pass"
            summary = "Clean install and concurrent start/teardown probes passed."
        except (ProtocolViolation, RuntimeProcessCrashed, RuntimeRequestTimeout, ValueError) as exc:
            record = {"status": "fail", "failure_class": type(exc).__name__}
            status = "fail"
            summary = str(exc)
        evidence_ref = self._evidence(
            run_id,
            "deployment",
            record,
            dependencies=(candidate_ref, install_ref),
        )
        return status, evidence_ref, summary, 2, tool_calls

    async def _reset_probe(
        self,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        manifest: CandidateManifest,
        seed: int,
        actor: str,
        reset_config: dict[str, JsonValue],
        design: EnvironmentDesign,
    ) -> dict[str, JsonValue]:
        async with self._supervisor(clean, candidate, manifest) as supervisor:
            reset = await supervisor.reset(seed=seed, actor=actor, config=reset_config)
            if not reset.ok or reset.result is None:
                raise _CandidateTaskFailure("Runtime reset probe failed")
            self._validate_reset_observation(reset.result["observation"], actor, design)
            return dict(reset.result)

    def _load_task_contract(
        self,
        candidate: EnvironmentCandidate,
    ) -> tuple[dict[str, Any], CurriculumRequirements]:
        try:
            raw_schema = self.artifacts.get_json(candidate.task_materializer.output_schema_ref)
            curriculum = self.artifacts.get_json(
                candidate.task_materializer.curriculum_ref,
                CurriculumRequirements,
            )
            if not isinstance(raw_schema, dict):
                raise TypeError("task output schema artifact is not an object")
            Draft202012Validator.check_schema(raw_schema)
        except (ArtifactStoreError, OSError, SchemaError, TypeError, ValidationError) as exc:
            raise JudgeInfrastructureError(
                "task_contract_artifact_invalid",
                "framework-owned task schema or curriculum is unavailable or invalid",
            ) from exc
        return raw_schema, curriculum

    @staticmethod
    def _task_materializer_call_counts(
        curriculum: CurriculumRequirements,
    ) -> dict[str, int]:
        """Compile each task type's finite stratified release sample."""

        return {
            requirement.task_type: (
                len(requirement.allowed_actor_ids)
                * (
                    max(
                        2,
                        curriculum.minimum_distinct_initial_states,
                        curriculum.minimum_distinct_tasks_per_type,
                        requirement.reachability_policy.samples_per_task_actor,
                    )
                    + 2 * len(requirement.difficulty_dimensions)
                )
                + requirement.reachability_policy.random_tail_samples
            )
            for requirement in curriculum.task_types
        }

    @staticmethod
    def _task_materializer_calls(
        *,
        run_id: str,
        candidate_ref: ArtifactRef,
        curriculum: CurriculumRequirements,
    ) -> tuple[TaskMaterializerCall, ...]:
        dimensions = {item.dimension: item for item in curriculum.difficulty_dimensions}
        calls: list[TaskMaterializerCall] = []

        def seed_for(label: str) -> int:
            return int.from_bytes(
                hashlib.sha256(
                    f"{run_id}\0{candidate_ref.content_hash}\0{label}".encode()
                ).digest()[:8],
                "big",
            )

        for requirement in curriculum.task_types:
            policy = requirement.reachability_policy
            count = max(
                2,
                curriculum.minimum_distinct_initial_states,
                curriculum.minimum_distinct_tasks_per_type,
                policy.samples_per_task_actor,
            )
            for actor in requirement.allowed_actor_ids:
                for index in range(count):
                    difficulty: dict[str, JsonValue] = {
                        dimension_id: dimensions[dimension_id].levels[
                            (index + offset) % len(dimensions[dimension_id].levels)
                        ]
                        for offset, dimension_id in enumerate(requirement.difficulty_dimensions)
                    }
                    calls.append(
                        TaskMaterializerCall(
                            seed=seed_for(f"{requirement.task_type}:{actor}:base:{index}"),
                            task_type=requirement.task_type,
                            actor=actor,
                            difficulty=difficulty,
                        )
                    )
                base_difficulty: dict[str, JsonValue] = cast(
                    dict[str, JsonValue],
                    {
                        dimension_id: dimensions[dimension_id].levels[0]
                        for dimension_id in requirement.difficulty_dimensions
                    },
                )
                for dimension_id in requirement.difficulty_dimensions:
                    contrast_seed = seed_for(
                        f"{requirement.task_type}:{actor}:contrast:{dimension_id}"
                    )
                    alternate = dict(base_difficulty)
                    alternate[dimension_id] = dimensions[dimension_id].levels[-1]
                    for contrast_difficulty in (base_difficulty, alternate):
                        calls.append(
                            TaskMaterializerCall(
                                seed=contrast_seed,
                                task_type=requirement.task_type,
                                actor=actor,
                                difficulty=dict(contrast_difficulty),
                            )
                        )
            for index in range(policy.random_tail_samples):
                actor = requirement.allowed_actor_ids[index % len(requirement.allowed_actor_ids)]
                label = f"{requirement.task_type}:{actor}:tail:{index}"
                difficulty = cast(
                    dict[str, JsonValue],
                    {
                        dimension_id: dimensions[dimension_id].levels[
                            seed_for(f"{label}:{dimension_id}")
                            % len(dimensions[dimension_id].levels)
                        ]
                        for dimension_id in requirement.difficulty_dimensions
                    },
                )
                calls.append(
                    TaskMaterializerCall(
                        seed=seed_for(label),
                        task_type=requirement.task_type,
                        actor=actor,
                        difficulty=difficulty,
                    )
                )
        return tuple(calls)

    @staticmethod
    def _task_runner_outputs(
        result: SandboxProcessResult,
        *,
        expected_count: int,
    ) -> tuple[dict[str, Any], ...]:
        if not result.succeeded:
            raise _CandidateTaskFailure(
                "Task Materializer exited unsuccessfully, timed out, or exceeded limits"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise _CandidateTaskFailure("Task Materializer runner output was not JSON") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"protocol", "ok", "materializations"}
            or payload.get("protocol") != "agent-world.task-materializer-runner.v3"
            or payload.get("ok") is not True
            or not isinstance(payload.get("materializations"), list)
            or len(payload["materializations"]) != expected_count
            or any(not isinstance(item, dict) for item in payload["materializations"])
        ):
            raise _CandidateTaskFailure(
                "Task Materializer runner response violated the closed v3 contract"
            )
        return tuple(payload["materializations"])

    @staticmethod
    def _validate_runtime_difficulty_contrasts(
        candidates: dict[str, dict[str, tuple[DifficultyContrastCandidate, ...]]],
        runtime_initial_views: dict[int, tuple[str, JsonValue]],
    ) -> dict[str, dict[str, dict[str, JsonValue]]]:
        evidence: dict[str, dict[str, dict[str, JsonValue]]] = {}
        for task_type, dimensions in candidates.items():
            task_evidence: dict[str, dict[str, JsonValue]] = {}
            for dimension, pairs in dimensions.items():
                accepted: tuple[DifficultyContrastCandidate, bool] | None = None
                for pair in pairs:
                    left_digest, left_observation = runtime_initial_views[pair.left_index]
                    right_digest, right_observation = runtime_initial_views[pair.right_index]
                    runtime_changed = left_digest != right_digest or canonical_json_bytes(
                        left_observation
                    ) != canonical_json_bytes(right_observation)
                    if pair.evaluator_goal_changed or (
                        pair.initial_config_changed and runtime_changed
                    ):
                        accepted = (pair, runtime_changed)
                        break
                if accepted is None:
                    raise _CandidateTaskFailure(
                        f"task {task_type} difficulty {dimension} changes only ignored fields"
                    )
                pair, runtime_changed = accepted
                task_evidence[dimension] = {
                    "mechanism": (
                        "framework_evaluator_projection"
                        if pair.evaluator_goal_changed
                        else "runtime_reset_state"
                    ),
                    "runtime_state_changed": runtime_changed,
                    "evaluator_goal_changed": pair.evaluator_goal_changed,
                    "semantic_pair_commitment": sha256_digest(
                        canonical_json_bytes([pair.left_semantic_hash, pair.right_semantic_hash])
                    ),
                }
            evidence[task_type] = task_evidence
        return evidence

    @staticmethod
    def _recipe_index(
        recipes: Sequence[ParameterizedSolveRecipe],
    ) -> dict[str, ParameterizedSolveRecipe]:
        grouped: dict[str, list[ParameterizedSolveRecipe]] = {}
        for recipe in recipes:
            grouped.setdefault(recipe.task_type, []).append(recipe)
        return {
            task_type: sorted(
                values,
                key=lambda recipe: (not recipe.preferred, recipe.recipe_id),
            )[0]
            for task_type, values in grouped.items()
        }

    @staticmethod
    def _solver_attempt_budget(
        policy: ReachabilityPolicy,
        available: Budget,
    ) -> Budget:
        """Return one task-local hard lease; no dimension is exchanged."""

        return Budget(
            llm_tokens=policy.maximum_llm_tokens_per_attempt,
            agent_turns=policy.maximum_agent_turns_per_attempt,
            search_calls=0,
            tool_calls=policy.maximum_steps_per_attempt,
            build_seconds=0,
            evaluation_episodes=1,
            container_seconds=min(
                available.container_seconds,
                policy.maximum_wall_seconds_per_attempt,
            ),
            live_probe_cost=0,
            repair_attempts=0,
            wall_seconds=min(
                available.wall_seconds,
                policy.maximum_wall_seconds_per_attempt,
            ),
            monetary_cost=0,
        )

    @staticmethod
    def _certificate(
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        design: EnvironmentDesign,
        envelope: FrameworkTaskEnvelope,
        final_state_digest: str,
        outcome: ReachabilityOutcome,
        *,
        strategy: Literal["parameterized_recipe", "interactive_challenger"],
        strategy_version: str,
    ) -> ReachabilityCertificate:
        trace_commitment = sha256_digest(
            canonical_json_bytes(
                {
                    "actions": [item.model_dump(mode="json") for item in outcome.actual_actions],
                    "steps": [asdict(item) for item in outcome.step_results],
                    "final_state_digest": final_state_digest,
                }
            )
        )
        instance = ReachabilityInstance(
            instance_id=f"instance:{envelope.materializer_digest.removeprefix('sha256:')[:24]}",
            materialization_digest=envelope.materializer_digest,
            seed=envelope.call.seed,
            task_type=envelope.call.task_type,
            actor=envelope.call.actor,
            difficulty=envelope.call.difficulty,
        )
        return ReachabilityCertificate(
            certificate_id=f"certificate:{uuid.uuid4().hex}",
            candidate_ref=candidate_ref,
            world_spec_hash=design.world_spec.content_digest(),
            runtime_source_ref=candidate.build_artifact_ref,
            task_materializer_ref=candidate.source_workspace_snapshot_ref,
            renderer_version=envelope.renderer_version,
            projector_version=envelope.projector_version,
            instance=instance,
            strategy=strategy,
            strategy_version=strategy_version,
            executed_steps=len(outcome.actual_actions),
            executed_tool_ids=tuple(item.tool_id for item in outcome.actual_actions),
            final_state_digest=final_state_digest,
            trace_commitment=trace_commitment,
            certified_at=datetime.now(UTC),
        )

    def _supervisor(
        self,
        clean: CleanCandidate,
        candidate: EnvironmentCandidate,
        manifest: CandidateManifest,
    ) -> RuntimeSupervisor:
        runtime = candidate.runtime
        return RuntimeSupervisor(
            clean.root,
            LaunchContract(argv=runtime.argv, cwd=runtime.workdir),
            visible_workspace_paths=self._role_visible_paths(manifest, "runtime"),
            isolation=self.runtime_isolation,
            request_timeout_seconds=runtime.request_timeout_seconds,
            shutdown_grace_seconds=runtime.shutdown_timeout_seconds,
        )

    @staticmethod
    def _role_visible_paths(
        manifest: CandidateManifest,
        role: Literal["runtime", "task_materializer", "public_verifier"],
    ) -> tuple[str, ...]:
        return component_visible_paths(manifest.files, role)

    @classmethod
    def _observation(
        cls,
        *,
        index: int,
        action: RuntimeAction,
        idempotency_key: str,
        response: RuntimeResponse,
        pre_snapshot: dict[str, JsonValue],
        post_snapshot: dict[str, JsonValue],
        reset_config: dict[str, JsonValue],
        task_goal: dict[str, JsonValue],
        seed: int,
        actor: str,
        design: EnvironmentDesign,
    ) -> tuple[RuntimeActionObservation, RuleExecutionContext]:
        if response.result is None:
            raise ValueError("invoke returned no result envelope")
        result = dict(response.result)
        if result["state_digest"] != post_snapshot["state_digest"]:
            raise ValueError("invoke and snapshot state digests differ")
        tool = next(
            item for item in design.world_spec.tools if item.surface.tool_id == action.tool_id
        )
        cls._validate_invoke_observation(result["observation"], actor, tool)
        if response.ok and tuple(
            Draft202012Validator(tool.surface.output_schema).iter_errors(result["tool_result"])
        ):
            raise ValueError(f"{action.tool_id} tool_result violates WorldSpec schema")
        cls._reject_redacted_fields(
            result["observation"],
            frozenset(tool.semantics.observation.redacted_fields_by_actor[actor]),
        )
        error = response.error
        error_value: JsonValue = None
        if error is not None:
            error_value = {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "details": dict(error.details),
            }
        context = RuleExecutionContext(
            actor=actor,
            pre_state=pre_snapshot["observation"],
            post_state=post_snapshot["observation"],
            args=action.arguments,
            tool_result=result["tool_result"],
            error=error_value,
            observation=result["observation"],
            events=result["events"],
            reset_config=reset_config,
            task_goal=task_goal,
            seed=seed,
            terminated=cast(bool, result["terminated"]),
            truncated=cast(bool, result["truncated"]),
        )
        observed = RuntimeActionObservation(
            action_index=index,
            tool_id=action.tool_id,
            arguments=action.arguments,
            idempotency_key=idempotency_key,
            response_ok=response.ok,
            result=result,
            error_code=error.code if error else None,
            error_message=error.message if error else None,
            error_details=dict(error.details) if error else {},
            events=result["events"],
            pre_snapshot=pre_snapshot,
            snapshot=post_snapshot,
            state_digest=post_snapshot["state_digest"],
            reward=float(cast(int | float, result["reward"])),
            terminated=cast(bool, result["terminated"]),
            truncated=cast(bool, result["truncated"]),
        )
        return observed, context

    @classmethod
    def _validate_reset_observation(
        cls,
        observation: JsonValue,
        actor: str,
        design: EnvironmentDesign,
    ) -> None:
        boundary = next(
            (
                item
                for item in design.world_spec.boundary.actors_and_authority
                if item.actor == actor
            ),
            None,
        )
        if boundary is None:
            raise ValueError(f"Runtime reset used unknown actor {actor}")
        cls._validate_actor_projection(
            observation,
            schema=design.world_spec.state.root_state_schema,
            visible_fields=boundary.visibility,
            label=f"reset observation for actor {actor}",
        )

    @classmethod
    def _validate_invoke_observation(cls, observation: JsonValue, actor: str, tool: Any) -> None:
        try:
            visible_fields = tool.semantics.observation.visible_fields_by_actor[actor]
        except KeyError as exc:
            raise ValueError(
                f"tool {tool.surface.tool_id} has no observation projection for {actor}"
            ) from exc
        cls._validate_actor_projection(
            observation,
            schema=tool.surface.observation_schema,
            visible_fields=visible_fields,
            label=f"{tool.surface.tool_id} observation for actor {actor}",
        )

    @staticmethod
    def _validate_actor_projection(
        observation: JsonValue,
        *,
        schema: dict[str, JsonValue],
        visible_fields: tuple[str, ...],
        label: str,
    ) -> None:
        if not isinstance(observation, dict):
            raise ValueError(f"{label} must be an object")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"{label} schema lacks properties")
        visible = set(visible_fields)
        if set(observation) - visible:
            raise ValueError(f"{label} disclosed non-visible fields")
        projected = actor_projection_schema(schema, visible_fields)
        errors = tuple(Draft202012Validator(projected).iter_errors(observation))
        if errors:
            coordinates = _schema_validation_coordinates(errors)
            raise ValueError(
                f"{label} violates actor-projected WorldSpec schema at: "
                + ", ".join(coordinates)
            )

    @staticmethod
    def _validate_state_snapshot(snapshot: dict[str, JsonValue], design: EnvironmentDesign) -> None:
        errors = tuple(
            Draft202012Validator(design.world_spec.state.root_state_schema).iter_errors(
                snapshot["observation"]
            )
        )
        if errors:
            coordinates = _schema_validation_coordinates(errors)
            raise ValueError(
                "snapshot violates WorldSpec root state schema at: "
                + ", ".join(coordinates)
            )

    @staticmethod
    def _validate_tool_semantics(
        observation: RuntimeActionObservation,
        context: RuleExecutionContext,
        tool: Any,
        design: EnvironmentDesign,
        rules: dict[str, Rule],
    ) -> None:
        validate_tool_execution(
            world_spec=design.world_spec,
            rules=rules,
            tool=tool,
            context=context,
            evidence=ToolExecutionEvidence(
                response_ok=observation.response_ok,
                result_present=observation.result is not None,
                error_code=observation.error_code,
                error_message=observation.error_message,
                error_details=observation.error_details,
                pre_state_digest=cast(str, observation.pre_snapshot["state_digest"]),
                post_state_digest=cast(str, observation.snapshot["state_digest"]),
            ),
        )

    @staticmethod
    def _reject_redacted_fields(value: JsonValue, redacted: frozenset[str]) -> None:
        if isinstance(value, dict):
            if redacted & set(value):
                raise ValueError("Runtime observation disclosed redacted fields")
            for child in value.values():
                EnvironmentJudge._reject_redacted_fields(child, redacted)
        elif isinstance(value, list):
            for child in value:
                EnvironmentJudge._reject_redacted_fields(child, redacted)

    @staticmethod
    def _sealed_case_projection(index: int, evaluation: CaseEvaluation) -> dict[str, JsonValue]:
        return {
            "ordinal": index,
            "passed": evaluation.passed,
            "reset_ok": evaluation.reset_ok,
            "action_count": len(evaluation.actions),
            "obligation_count": len(evaluation.assertions),
            "failed_obligation_count": sum(not item.passed for item in evaluation.assertions),
            "failure_class": evaluation.failure_class,
        }

    def _validate_candidate_source(
        self,
        source_dir: Path,
        *,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        manifest: CandidateManifest,
        world_spec: WorldSpec,
        world_spec_ref: ArtifactRef,
        verifier: VerifierIR | None,
        verifier_ref: ArtifactRef | None,
    ) -> dict[str, Any]:
        if source_dir.expanduser().is_symlink():
            raise ValueError("candidate source root cannot be a symlink")
        root = source_dir.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("candidate source must be a directory")
        if manifest.candidate_id != candidate.candidate_id:
            raise ValueError("candidate manifest id differs from EnvironmentCandidate")
        if (
            manifest.design_ref != candidate.design_ref
            or manifest.runtime != candidate.runtime
            or manifest.task_materializer != candidate.task_materializer
            or manifest.public_self_check != candidate.public_self_check
            or manifest.public_verifier_ref != candidate.public_verifier_ref
            or manifest.implementation_lineage_ref != candidate.implementation_lineage_ref
        ):
            raise ValueError("candidate manifest differs from EnvironmentCandidate")
        if (verifier is None) != (verifier_ref is None):
            raise ValueError("VerifierIR and its artifact ref must be supplied together")
        if verifier is not None and verifier_ref is not None:
            if (
                verifier.design_ref != candidate.design_ref
                or verifier.world_spec_ref != world_spec_ref
            ):
                raise ValueError("VerifierIR is not bound to this candidate design and WorldSpec")
            if verifier_ref.artifact_type != "judge.verifier_ir_projection":
                raise ValueError("VerifierIR ref must contain only its persistence projection")
        if world_spec_ref.content_hash != world_spec.content_digest():
            raise ValueError("WorldSpec differs from its immutable artifact reference")

        declared = {entry.path: entry for entry in manifest.files}
        actual: set[str] = set()
        for directory, names, files in os.walk(root, topdown=True, followlinks=False):
            directory_path = Path(directory)
            names[:] = sorted(names)
            files.sort()
            for name in names:
                child = directory_path / name
                if child.is_symlink() or name in _FORBIDDEN_SOURCE_PARTS:
                    raise ValueError(f"forbidden candidate directory: {child.relative_to(root)}")
            for name in files:
                path = directory_path / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    raise ValueError(f"candidate file is a symlink: {relative}")
                file_stat = path.stat(follow_symlinks=False)
                if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                    raise ValueError(f"candidate file is not an independent file: {relative}")
                if relative == ".agent-world-root":
                    continue
                if any(part in _FORBIDDEN_SOURCE_PARTS for part in PurePosixPath(relative).parts):
                    raise ValueError(f"forbidden candidate path: {relative}")
                actual.add(relative)
                if relative not in declared:
                    raise ValueError(f"candidate contains undeclared file: {relative}")
                self._validate_file(path, declared[relative])
        if set(declared) != actual:
            raise ValueError(f"manifest declares missing files: {sorted(set(declared) - actual)}")
        roles = {entry.role for entry in manifest.files}
        required_roles = {
            "dependency_lock",
            "public_test",
            "public_verifier",
            "runtime",
            "task_materializer",
        }
        if not required_roles <= roles:
            raise ValueError("candidate manifest lacks required executable/source roles")
        if "pyproject.toml" not in declared or "uv.lock" not in declared:
            raise ValueError("candidate project requires pyproject.toml and uv.lock")
        physical_digest = candidate_source_tree_digest(manifest.files)
        if physical_digest != manifest.candidate_source_tree_digest:
            raise ValueError("candidate source tree differs from manifest digest")
        record: dict[str, Any] = {
            "status": "pass",
            "candidate_ref": candidate_ref.revision_id,
            "file_count": len(actual),
            "declared_roles": sorted(roles),
            "world_spec_hash": world_spec.content_digest(),
            "candidate_source_tree_digest": physical_digest,
        }
        if verifier_ref is not None:
            record["verifier_ref"] = verifier_ref.revision_id
        return record

    @staticmethod
    def _validate_file(path: Path, declared: PackageFile) -> None:
        content = path.read_bytes()
        if len(content) != declared.size_bytes:
            raise ValueError(f"file size differs from manifest: {declared.path}")
        if sha256_digest(content) != declared.content_hash:
            raise ValueError(f"file hash differs from manifest: {declared.path}")
        if bool(path.stat().st_mode & stat.S_IXUSR) != declared.executable:
            raise ValueError(f"executable bit differs from manifest: {declared.path}")

    def _record_gate(
        self,
        *,
        gate_id: str,
        status: GateStatus,
        evidence_ref: ArtifactRef,
        summary: str,
        owner: FindingOwner,
        candidate_ref: ArtifactRef,
        release_profile: ReleaseProfile,
        gate_results: list[GateResult],
        evidence_refs: list[ArtifactRef],
        findings: list[Finding],
        run_id: str,
        disclosure: Literal["public", "repair", "sealed_summary"] = "repair",
    ) -> None:
        evidence_refs.append(evidence_ref)
        gate_results.append(
            self._gate(
                gate_id,
                status,
                candidate_ref,
                (evidence_ref,),
                release_profile,
                summary,
            )
        )
        if status != "pass":
            findings.append(
                self._finding(
                    run_id,
                    gate_id,
                    candidate_ref,
                    evidence_ref,
                    owner=owner,
                    summary=f"{gate_id} did not pass.",
                    suggested_repair=summary,
                    disclosure=disclosure,
                )
            )

    def _evidence(
        self,
        run_id: str,
        label: str,
        value: Any,
        *,
        dependencies: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        safe_label = re.sub(r"[^A-Za-z0-9._:-]+", "-", label)
        return self.artifacts.put_json(
            artifact_id=f"{run_id}:evidence:{safe_label}",
            artifact_type="judge.evaluation_evidence",
            value=_sanitize_evidence(value),
            dependencies=dependencies,
        )

    def _typed_evidence(
        self,
        run_id: str,
        label: str,
        artifact_type: Literal[
            "judge.static_assurance_evidence",
            "judge.supply_chain_evidence",
        ],
        value: StaticAssuranceEvidence | SupplyChainEvidence,
        *,
        dependencies: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        safe_label = re.sub(r"[^A-Za-z0-9._:-]+", "-", label)
        return self.artifacts.put_json(
            artifact_id=f"{run_id}:evidence:{safe_label}",
            artifact_type=artifact_type,
            value=value,
            dependencies=dependencies,
        )

    @staticmethod
    def _gate(
        gate_id: str,
        status: GateStatus,
        candidate_ref: ArtifactRef,
        evidence_refs: tuple[ArtifactRef, ...],
        release_profile: ReleaseProfile,
        summary: str,
    ) -> GateResult:
        return GateResult(
            gate_id=gate_id,
            status=status,
            hard=(gate_id in _ALWAYS_HARD_GATES or gate_id in release_profile.required_hard_gates),
            subject_ref=candidate_ref,
            evidence_refs=evidence_refs,
            duration_seconds=0,
            summary=summary or status,
        )

    @staticmethod
    def _finding(
        run_id: str,
        category: str,
        candidate_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
        *,
        owner: FindingOwner,
        summary: str,
        suggested_repair: str,
        disclosure: Literal["public", "repair", "sealed_summary"] = "repair",
        blocks_release: bool = True,
    ) -> Finding:
        fingerprint = sha256_digest(
            canonical_json_bytes(
                {
                    "category": category,
                    "owner": owner,
                    "summary": " ".join(summary.casefold().split()),
                }
            )
        )
        observation_digest = sha256_digest(
            canonical_json_bytes(
                {
                    "run_id": run_id,
                    "category": category,
                    "candidate": candidate_ref.revision_id,
                    "evidence": evidence_ref.revision_id,
                }
            )
        )
        return Finding(
            finding_id=f"finding:{observation_digest.removeprefix('sha256:')[:24]}",
            category=category,
            severity="high" if blocks_release else "medium",
            owner=owner,
            subject_ref=candidate_ref,
            summary=summary,
            evidence_refs=(evidence_ref,),
            fingerprint=fingerprint,
            disclosure=disclosure,
            suggested_repair=suggested_repair,
            blocks_release=blocks_release,
        )

    def _finish_integration(
        self,
        *,
        run_id: str,
        candidate_ref: ArtifactRef,
        gate_results: list[GateResult],
        findings: list[Finding],
        evidence_refs: list[ArtifactRef],
        report_dependencies: tuple[ArtifactRef, ...],
        started: float,
        episodes: int,
        tool_calls: int,
        clean_build_seconds: float,
        candidate_source_tree_digest: str | None,
    ) -> IntegrationBundle:
        if not gate_results or not evidence_refs:
            raise ValueError("Integration must persist evidence for every terminal result")
        if len({item.gate_id for item in gate_results}) != len(gate_results):
            raise ValueError("Integration produced duplicate gate results")
        elapsed = time.monotonic() - started
        timed_gates = tuple(
            item.model_copy(update={"duration_seconds": elapsed}) for item in gate_results
        )
        if any(item.status == "error" for item in timed_gates):
            status: Literal["ready", "failed", "error"] = "error"
        elif any(item.status != "pass" for item in timed_gates) or any(
            item.blocks_release for item in findings
        ):
            status = "failed"
        else:
            status = "ready"
        report = IntegrationReport(
            report_id=f"integration-report:{uuid.uuid4().hex}",
            revision=1,
            candidate_ref=candidate_ref,
            candidate_source_tree_digest=candidate_source_tree_digest,
            status=status,
            gate_results=timed_gates,
            findings=tuple(findings),
            evidence_refs=tuple(evidence_refs),
            budget_usage=BudgetUsage(
                tool_calls=tool_calls,
                build_seconds=clean_build_seconds,
                evaluation_episodes=episodes,
                container_seconds=elapsed,
                wall_seconds=0,
            ),
        )
        report_ref = self.artifacts.put_json(
            artifact_id=f"{run_id}:integration-report",
            artifact_type="judge.integration_report",
            value=report,
            dependencies=(candidate_ref, *report_dependencies, *evidence_refs),
        )
        return IntegrationBundle(report, report_ref, tuple(evidence_refs))

    def _finish(
        self,
        *,
        run_id: str,
        candidate_ref: ArtifactRef,
        gate_results: list[GateResult],
        findings: list[Finding],
        evidence_refs: list[ArtifactRef],
        report_dependencies: tuple[ArtifactRef, ...],
        started: float,
        episodes: int,
        non_reachability_tool_calls: int,
        reachability_usage: BudgetUsage,
        clean_build_seconds: float,
        candidate_source_tree_digest: str | None,
        release_profile: ReleaseProfile,
    ) -> JudgeBundle:
        observed = {gate.gate_id: gate for gate in gate_results}
        if len(observed) != len(gate_results):
            raise ValueError("Judge produced duplicate canonical gate results")
        fallback_ref = evidence_refs[-1]
        ordered_gates: list[GateResult] = []
        for gate_id in _CANONICAL_GATES:
            gate = observed.get(gate_id)
            if gate is None:
                gate = GateResult(
                    gate_id=gate_id,
                    status="inconclusive",
                    hard=(
                        gate_id in _ALWAYS_HARD_GATES
                        or gate_id in release_profile.required_hard_gates
                    ),
                    subject_ref=candidate_ref,
                    evidence_refs=(fallback_ref,),
                    duration_seconds=0,
                    summary="Gate was not reached after an earlier terminal failure.",
                )
            ordered_gates.append(gate)
        gate_results = ordered_gates
        if any(gate.status == "error" for gate in gate_results):
            verdict: Literal["pass", "fail", "inconclusive", "error"] = "error"
        elif any(gate.hard and gate.status == "fail" for gate in gate_results):
            verdict = "fail"
        elif any(gate.hard and gate.status == "inconclusive" for gate in gate_results):
            verdict = "inconclusive"
        elif any(finding.blocks_release for finding in findings):
            verdict = "fail"
        else:
            verdict = "pass"
        elapsed = time.monotonic() - started
        report = JudgeReport(
            report_id=f"report:{uuid.uuid4().hex}",
            revision=1,
            candidate_ref=candidate_ref,
            candidate_source_tree_digest=candidate_source_tree_digest,
            verdict=verdict,
            gate_results=tuple(
                gate.model_copy(update={"duration_seconds": elapsed}) for gate in gate_results
            ),
            findings=tuple(findings),
            evaluation_evidence_refs=tuple(evidence_refs),
            budget_usage=BudgetUsage(
                llm_tokens=reachability_usage.llm_tokens,
                agent_turns=reachability_usage.agent_turns,
                tool_calls=(reachability_usage.tool_calls + non_reachability_tool_calls),
                build_seconds=clean_build_seconds,
                evaluation_episodes=episodes,
                container_seconds=elapsed,
                # The Controller owns the global run clock.  Judge reports only
                # additive child consumption to avoid charging wall time twice.
                wall_seconds=0,
                monetary_cost=reachability_usage.monetary_cost,
            ),
        )
        report_ref = self.artifacts.put_json(
            artifact_id=f"{run_id}:judge-report",
            artifact_type="judge_report",
            value=report,
            dependencies=(candidate_ref, *report_dependencies, *evidence_refs),
        )
        return JudgeBundle(report, report_ref, tuple(evidence_refs))

    @staticmethod
    def _idempotency_key(seed: int, index: int, label: str) -> str:
        return hashlib.sha256(f"{seed}\0{index}\0{label}".encode()).hexdigest()


def _add_usage(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
    return BudgetUsage(
        **{
            name: getattr(left, name) + getattr(right, name)
            for name in BudgetUsage.model_fields
            if name != "schema_version"
        }
    )


def _require_budget_at_least(available: Budget, required: Budget) -> None:
    deficits = tuple(
        name
        for name in Budget.model_fields
        if name != "schema_version" and getattr(available, name) < getattr(required, name)
    )
    if deficits:
        raise ValueError(
            "Judge child lease is below its compiled worst-case reservation: " + ", ".join(deficits)
        )


def _candidate_outcome(summary: str) -> ReachabilityOutcome:
    return ReachabilityOutcome(
        status="failed",
        actual_actions=(),
        step_results=(),
        usage=BudgetUsage(evaluation_episodes=1),
        invocation_results=(),
        failure_classification="candidate",
        failure_code="candidate_episode_start_failed",
        failure_summary=summary,
    )


def _budget_outcome(code: str, summary: str) -> ReachabilityOutcome:
    return ReachabilityOutcome(
        status="inconclusive",
        actual_actions=(),
        step_results=(),
        usage=BudgetUsage(evaluation_episodes=1),
        invocation_results=(),
        failure_classification="budget",
        failure_code=code,
        failure_summary=summary,
    )


def _infrastructure_outcome(
    code: str,
    summary: str,
    *,
    status: Literal["inconclusive", "infrastructure_error"] = "infrastructure_error",
) -> ReachabilityOutcome:
    return ReachabilityOutcome(
        status=status,
        actual_actions=(),
        step_results=(),
        usage=BudgetUsage(evaluation_episodes=1),
        invocation_results=(),
        failure_classification="infrastructure",
        failure_code=code,
        failure_summary=summary,
    )


def _inconclusive_recipe_outcome(code: str, summary: str) -> ReachabilityOutcome:
    return ReachabilityOutcome(
        status="inconclusive",
        actual_actions=(),
        step_results=(),
        usage=BudgetUsage(evaluation_episodes=1),
        invocation_results=(),
        failure_classification="recipe",
        failure_code=code,
        failure_summary=summary,
    )


def _reachability_failure_route(
    outcome: ReachabilityOutcome,
) -> tuple[GateStatus, FindingOwner]:
    if outcome.failure_classification == "candidate":
        return "fail", "build"
    if outcome.failure_classification == "infrastructure":
        return (
            "inconclusive" if outcome.status == "inconclusive" else "error",
            "judge_infrastructure",
        )
    if outcome.failure_classification == "budget":
        return "inconclusive", "release_policy"
    return "inconclusive", "verifier"


def _worse_reachability_route(
    left: tuple[GateStatus, FindingOwner],
    right: tuple[GateStatus, FindingOwner],
) -> tuple[GateStatus, FindingOwner]:
    """Select one whole failure route so status and owner cannot diverge."""

    rank = {"pass": 0, "inconclusive": 1, "fail": 2, "error": 3}
    return left if rank[left[0]] >= rank[right[0]] else right


_SENSITIVE_EVIDENCE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "credential_value",
        "evaluator_goal",
        "password_value",
        "private_key",
        "refresh_token",
        "secret",
        "secret_value",
        "transcript",
    }
)


def _sanitize_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_EVIDENCE_KEYS:
                digest = hashlib.sha256(str(key).encode()).hexdigest()[:12]
                sanitized[f"redacted_field_{digest}"] = "[redacted]"
            else:
                sanitized[str(key)] = _sanitize_evidence(child)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_evidence(item) for item in value]
    return value


__all__ = ["EnvironmentJudge", "JudgeBundle"]
