"""Real local rollout consumer for immutable released envpkg v3 packages."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import JsonValue

from agent_world.contracts import (
    CurriculumRequirements,
    EnvironmentPackageManifest,
    EnvironmentSuiteSnapshot,
    LocalEpisodeStart,
    LocalRolloutResult,
    PublicTask,
    RolloutAction,
    RolloutReset,
    RolloutStep,
    Rule,
    SuitePackageSelection,
    TaskMaterializerCall,
    TrustedEvaluatorSpec,
    WorldSpec,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.judge import (
    CandidateComponentRole,
    CandidateProcessRunner,
    CleanCandidate,
    CleanCandidateBuilder,
    HostExecutionPolicy,
    LaunchContract,
    RuntimeSupervisor,
    ToolExecutionEvidence,
    ToolSemanticValidationError,
    actor_projection_schema,
    component_visible_paths,
    validate_tool_execution,
)
from agent_world.judge.rules import (
    RuleEvaluationError,
    RuleExecutionContext,
    contract_rule_index,
    evaluate_rule,
    initially_evaluable_rules,
)
from agent_world.registry import EnvironmentRegistry, ResolvedEnvironmentPackage
from agent_world.task_materialization import (
    TaskMaterializationError,
    TaskMaterializerV3Compiler,
    compile_task_materializer_output_schema,
)

from .evaluator import PortableTrustedEvaluator


class LocalConsumerError(RuntimeError):
    """A released package could not be safely consumed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _MaterializedTask:
    seed: int
    task_type: str
    actor: str
    public_instruction: str
    public_goal: dict[str, JsonValue]
    initial_config: dict[str, JsonValue]
    evaluator_goal: dict[str, JsonValue]
    difficulty: dict[str, JsonValue]

    def public_projection(self) -> PublicTask:
        return PublicTask(
            seed=self.seed,
            task_type=self.task_type,
            actor=self.actor,
            public_instruction=self.public_instruction,
            public_goal=self.public_goal,
            difficulty=self.difficulty,
        )


@dataclass(frozen=True, slots=True)
class _PortableContracts:
    world_spec: WorldSpec
    curriculum: CurriculumRequirements
    materializer_protocol_schema: dict[str, JsonValue]
    task_compiler: TaskMaterializerV3Compiler
    rules: dict[str, Rule]
    evaluator: PortableTrustedEvaluator


class LocalRolloutConsumer:
    """Consume releases without giving candidate code access to the framework process."""

    def __init__(
        self,
        *,
        registry: EnvironmentRegistry,
        clean_builder: CleanCandidateBuilder,
        runtime_execution: HostExecutionPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._clean_builder = clean_builder
        self._runtime_execution = runtime_execution or HostExecutionPolicy(purpose="runtime")
        self._process_runner = CandidateProcessRunner(
            execution=self._runtime_execution,
        )

    async def rollout(
        self,
        snapshot_id: str,
        *,
        seed: int,
        actions: Sequence[RolloutAction],
    ) -> LocalRolloutResult:
        episode = await self.start(snapshot_id, seed=seed)
        async with episode:
            for action in actions:
                if episode.finished:
                    break
                await episode.step(action)
            return episode.result()

    async def start(
        self,
        snapshot_id: str,
        *,
        seed: int,
    ) -> LocalEpisode:
        """Start a live episode and return only after public task/reset are ready."""

        if isinstance(seed, bool) or not 0 <= seed <= 2**64 - 1:
            raise ValueError("rollout seed must be a uint64")
        snapshot = self._registry.load_suite_snapshot(snapshot_id)
        selection = _select_package(snapshot, seed)
        resolved = self._registry.resolve_suite_package(
            snapshot.snapshot_id,
            selection.package_id,
            selection.version,
        )
        materialization = self._clean_builder.materialize(
            resolved.package_root,
            expected_source_files=resolved.manifest.files,
            expected_source_tree_digest=resolved.manifest.candidate_source_tree_digest,
        )
        clean = await materialization.__aenter__()
        try:
            if clean.candidate_source_tree_digest != resolved.manifest.candidate_source_tree_digest:
                raise LocalConsumerError(
                    "materialized_source_tree",
                    "clean materialization differs from the released candidate source tree",
                )
            self._verify_materialized_package(clean.root, resolved)
            contracts = self._load_portable_contracts(clean.root, resolved.manifest)
            task = await self._materialize_task(
                clean.root,
                resolved.manifest,
                selection,
                contracts,
                seed,
            )
            episode = LocalEpisode(
                consumer=self,
                materialization=materialization,
                clean=clean,
                snapshot=snapshot,
                selection=selection,
                manifest=resolved.manifest,
                contracts=contracts,
                task=task,
            )
            try:
                await episode._initialize()
            except BaseException:
                await episode._close_runtime_only()
                raise
            return episode
        except BaseException:
            await materialization.__aexit__(None, None, None)
            raise

    async def _materialize_task(
        self,
        root: Path,
        manifest: EnvironmentPackageManifest,
        selection: SuitePackageSelection,
        contracts: _PortableContracts,
        seed: int,
    ) -> _MaterializedTask:
        requirement = _seeded_choice(
            contracts.curriculum.task_types,
            seed=seed,
            label=f"{selection.manifest_hash}:task-type",
        )
        actor = _seeded_choice(
            requirement.allowed_actor_ids,
            seed=seed,
            label=f"{selection.manifest_hash}:{requirement.task_type}:actor",
        )
        dimensions = {item.dimension: item for item in contracts.curriculum.difficulty_dimensions}
        difficulty: dict[str, JsonValue] = {}
        for dimension_id in requirement.difficulty_dimensions:
            dimension = dimensions[dimension_id]
            difficulty[dimension_id] = _seeded_choice(
                dimension.levels,
                seed=seed,
                label=(f"{selection.manifest_hash}:{requirement.task_type}:{actor}:{dimension_id}"),
            )
        call = TaskMaterializerCall(
            seed=seed,
            task_type=requirement.task_type,
            actor=actor,
            difficulty=difficulty,
        )
        result = await self._process_runner.run_task_materializer(
            root,
            entrypoint=manifest.task_materializer.entrypoint,
            visible_workspace_paths=_role_paths(manifest, "task_materializer"),
            calls=(call.call_arguments(),),
        )
        if not result.succeeded:
            raise LocalConsumerError(
                "task_materializer_failed",
                "released task materializer failed in the framework-owned consumer process",
            )
        try:
            runner_envelope = json.loads(result.stdout)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise LocalConsumerError(
                "task_materializer_protocol",
                "released task materializer emitted invalid JSON",
            ) from exc
        if (
            not isinstance(runner_envelope, dict)
            or runner_envelope.get("protocol") != "agent-world.task-materializer-runner.v3"
            or runner_envelope.get("ok") is not True
            or not isinstance(runner_envelope.get("materializations"), list)
            or len(runner_envelope["materializations"]) != 1
            or not isinstance(runner_envelope["materializations"][0], dict)
        ):
            raise LocalConsumerError(
                "task_materializer_protocol",
                "released task materializer response violated its protocol",
            )
        raw: dict[str, Any] = runner_envelope["materializations"][0]
        try:
            framework_envelope = contracts.task_compiler.materialize(call, raw)
        except TaskMaterializationError as exc:
            raise LocalConsumerError(
                "task_materialization_contract",
                f"released task materializer violated framework contract: {exc.code}",
            ) from exc
        materialization = framework_envelope.materialization
        return _MaterializedTask(
            seed=seed,
            task_type=requirement.task_type,
            actor=actor,
            public_instruction=framework_envelope.public_instruction,
            public_goal=materialization.public_goal,
            initial_config=materialization.initial_config,
            evaluator_goal=framework_envelope.evaluator_goal,
            difficulty=difficulty,
        )

    @staticmethod
    def _verify_materialized_package(
        root: Path,
        resolved: ResolvedEnvironmentPackage,
    ) -> None:
        for declared in resolved.manifest.files:
            _read_verified_file(root, declared.path, declared.content_hash, declared.size_bytes)
        manifest_bytes = _read_regular_file(root, "manifest.json")
        if manifest_bytes != resolved.manifest.stable_json_bytes():
            raise LocalConsumerError(
                "materialized_manifest",
                "clean materialization changed the released manifest",
            )

    @staticmethod
    def _load_portable_contracts(
        root: Path,
        manifest: EnvironmentPackageManifest,
    ) -> _PortableContracts:
        descriptor = manifest.trusted_evaluator
        try:
            world_spec = WorldSpec.model_validate_json(
                _read_declared(root, manifest, descriptor.world_spec_path)
            )
            curriculum = CurriculumRequirements.model_validate_json(
                _read_declared(root, manifest, descriptor.curriculum_path)
            )
            evaluator_spec = TrustedEvaluatorSpec.model_validate_json(
                _read_declared(root, manifest, descriptor.rule_ir_path)
            )
            materializer_protocol_value = json.loads(
                _read_declared(root, manifest, descriptor.materializer_protocol_path)
            )
        except LocalConsumerError:
            raise
        except Exception as exc:
            raise LocalConsumerError(
                "portable_contracts",
                "released package contains invalid portable evaluation contracts",
            ) from exc
        if not isinstance(materializer_protocol_value, dict):
            raise LocalConsumerError(
                "portable_contracts",
                "packaged materializer protocol schema is not an object",
            )
        materializer_protocol_schema: dict[str, JsonValue] = materializer_protocol_value
        if canonical_json_bytes(materializer_protocol_schema) != canonical_json_bytes(
            compile_task_materializer_output_schema(curriculum)
        ):
            raise LocalConsumerError(
                "portable_contracts",
                "packaged materializer protocol schema differs from its curriculum",
            )
        if world_spec.content_digest() != manifest.world_spec_hash:
            raise LocalConsumerError(
                "portable_contracts",
                "packaged WorldSpec differs from the release manifest",
            )
        task_compiler = TaskMaterializerV3Compiler(curriculum)
        return _PortableContracts(
            world_spec=world_spec,
            curriculum=curriculum,
            materializer_protocol_schema=materializer_protocol_schema,
            task_compiler=task_compiler,
            rules=contract_rule_index(world_spec, curriculum),
            evaluator=PortableTrustedEvaluator(world_spec, curriculum, evaluator_spec),
        )

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, JsonValue], world_spec: WorldSpec) -> None:
        observation = snapshot.get("observation")
        if tuple(Draft202012Validator(world_spec.state.root_state_schema).iter_errors(observation)):
            raise LocalConsumerError(
                "runtime_snapshot_schema",
                "Runtime snapshot violates the packaged root-state schema",
            )

    @staticmethod
    def _validate_reset_observation(
        observation: JsonValue,
        actor: str,
        world_spec: WorldSpec,
    ) -> None:
        boundary = next(
            item for item in world_spec.boundary.actors_and_authority if item.actor == actor
        )
        _validate_projection(
            observation,
            schema=world_spec.state.root_state_schema,
            visible_fields=boundary.visibility,
            label="reset observation",
        )

    @staticmethod
    def _validate_invoke_observation(
        observation: JsonValue,
        actor: str,
        tool: Any,
    ) -> None:
        _validate_projection(
            observation,
            schema=tool.surface.observation_schema,
            visible_fields=tool.semantics.observation.visible_fields_by_actor[actor],
            label=f"{tool.surface.tool_id} observation",
        )


class LocalEpisode:
    """One live isolated session; evaluator inputs never leave this trusted object."""

    def __init__(
        self,
        *,
        consumer: LocalRolloutConsumer,
        materialization: AbstractAsyncContextManager[CleanCandidate],
        clean: CleanCandidate,
        snapshot: EnvironmentSuiteSnapshot,
        selection: SuitePackageSelection,
        manifest: EnvironmentPackageManifest,
        contracts: _PortableContracts,
        task: _MaterializedTask,
    ) -> None:
        self._consumer = consumer
        self._materialization = materialization
        self._clean = clean
        self._snapshot = snapshot
        self._selection = selection
        self._manifest = manifest
        self._contracts = contracts
        self._task = task
        self._episode_id = _episode_id(snapshot.snapshot_digest, selection, task.seed)
        self._supervisor = RuntimeSupervisor(
            clean.root,
            LaunchContract(
                argv=manifest.runtime.argv,
                cwd=manifest.runtime.workdir,
            ),
            visible_workspace_paths=_role_paths(manifest, "runtime"),
            execution=consumer._runtime_execution,
            request_timeout_seconds=manifest.runtime.request_timeout_seconds,
            shutdown_grace_seconds=manifest.runtime.shutdown_timeout_seconds,
        )
        self._before: dict[str, JsonValue] | None = None
        self._reset: RolloutReset | None = None
        self._steps: list[RolloutStep] = []
        self._terminated = False
        self._truncated = False
        self._succeeded = False
        self._failed = False
        self._started = False
        self._closed = False

    @property
    def public_task(self) -> PublicTask:
        return self._task.public_projection()

    @property
    def reset(self) -> RolloutReset:
        if self._reset is None:
            raise LocalConsumerError("episode_not_started", "episode reset is not available")
        return self._reset

    @property
    def finished(self) -> bool:
        return self._terminated or self._truncated

    def start_result(self) -> LocalEpisodeStart:
        self._require_active()
        return LocalEpisodeStart(
            episode_id=self._episode_id,
            snapshot_id=self._snapshot.snapshot_id,
            package=self._selection,
            task=self.public_task,
            reset=self.reset,
        )

    async def _initialize(self) -> None:
        handshake = await self._supervisor.start()
        if handshake.result is None:
            raise LocalConsumerError(
                "runtime_handshake",
                "released Runtime omitted its validated handshake",
            )
        reset_response = await self._supervisor.reset(
            seed=self._task.seed,
            actor=self._task.actor,
            config=self._task.initial_config,
        )
        if not reset_response.ok or reset_response.result is None:
            raise LocalConsumerError(
                "runtime_reset",
                "released Runtime rejected a generated task reset",
            )
        initial_snapshot = await self._supervisor.snapshot()
        if not initial_snapshot.ok or initial_snapshot.result is None:
            raise LocalConsumerError(
                "runtime_snapshot",
                "released Runtime could not snapshot its initial state",
            )
        before = dict(initial_snapshot.result)
        self._consumer._validate_snapshot(before, self._contracts.world_spec)
        initial_digest = _content_hash(before.get("state_digest"))
        if reset_response.result["state_digest"] != initial_digest:
            raise LocalConsumerError(
                "runtime_state_digest",
                "reset and immediate snapshot state digests differ",
            )
        self._consumer._validate_reset_observation(
            reset_response.result["observation"],
            self._task.actor,
            self._contracts.world_spec,
        )
        initial_context = RuleExecutionContext(
            actor=self._task.actor,
            pre_state=before["observation"],
            post_state=before["observation"],
            args={},
            tool_result=None,
            error=None,
            observation=reset_response.result["observation"],
            events=[],
            reset_config=self._task.initial_config,
            task_goal=self._task.evaluator_goal,
            seed=self._task.seed,
            terminated=False,
            truncated=False,
        )
        requirement = next(
            item
            for item in self._contracts.curriculum.task_types
            if item.task_type == self._task.task_type
        )
        try:
            for rule in initially_evaluable_rules(
                (
                    *self._contracts.world_spec.invariants,
                    *self._contracts.world_spec.state.initial_state_constraints,
                    *requirement.initial_state_constraints,
                    *self._contracts.curriculum.sampling_constraints,
                )
            ):
                if not evaluate_rule(rule, initial_context).result:
                    raise LocalConsumerError(
                        "generated_task_rule",
                        f"generated task violated packaged Rule {rule.rule_id}",
                    )
        except RuleEvaluationError as exc:
            raise LocalConsumerError(
                "generated_task_rule",
                f"generated task Rule could not be evaluated: {exc}",
            ) from exc
        reset_view: dict[str, JsonValue] = {
            "observation": reset_response.result["observation"],
        }
        tools_value = handshake.result["tools"]
        if not isinstance(tools_value, list) or not all(
            isinstance(item, dict) for item in tools_value
        ):
            raise LocalConsumerError(
                "runtime_handshake",
                "released Runtime handshake tools are invalid",
            )
        self._reset = RolloutReset(
            agent_view=reset_view,
            tools=tuple(cast(dict[str, JsonValue], item) for item in tools_value),
            state_digest=initial_digest,
        )
        self._before = before
        self._started = True

    async def step(self, action: RolloutAction) -> RolloutStep:
        self._require_active()
        if self.finished:
            raise LocalConsumerError("episode_finished", "cannot step a finished episode")
        before = self._before
        assert before is not None
        index = len(self._steps)
        tool = next(
            (
                item
                for item in self._contracts.world_spec.tools
                if item.surface.tool_id == action.tool_id
            ),
            None,
        )
        if tool is None:
            raise LocalConsumerError(
                "unknown_tool",
                f"action references unknown packaged tool {action.tool_id}",
            )
        if tuple(Draft202012Validator(tool.surface.input_schema).iter_errors(action.arguments)):
            raise LocalConsumerError(
                "tool_arguments",
                f"action arguments violate packaged schema for {action.tool_id}",
            )
        invoked = await self._supervisor.invoke(
            tool=action.tool_id,
            args=action.arguments,
            idempotency_key=f"{self._episode_id}:step:{index}",
        )
        after_response = await self._supervisor.snapshot()
        if not after_response.ok or after_response.result is None:
            raise LocalConsumerError(
                "runtime_snapshot",
                "released Runtime could not snapshot a rollout step",
            )
        after = dict(after_response.result)
        self._consumer._validate_snapshot(after, self._contracts.world_spec)
        after_digest = _content_hash(after.get("state_digest"))
        runtime_result = dict(invoked.result or {})
        if runtime_result and runtime_result.get("state_digest") != after_digest:
            raise LocalConsumerError(
                "runtime_state_digest",
                "invoke and immediate snapshot state digests differ",
            )
        observation = runtime_result.get("observation", after["observation"])
        self._consumer._validate_invoke_observation(
            observation,
            self._task.actor,
            tool,
        )
        error_value: JsonValue = None
        error_code: str | None = None
        if invoked.error is not None:
            error_code = invoked.error.code
            error_value = {
                "code": invoked.error.code,
                "message": invoked.error.message,
                "retryable": invoked.error.retryable,
                "details": dict(invoked.error.details),
            }
        context = RuleExecutionContext(
            actor=self._task.actor,
            pre_state=before["observation"],
            post_state=after["observation"],
            args=action.arguments,
            tool_result=runtime_result.get("tool_result"),
            error=error_value,
            observation=observation,
            events=runtime_result.get("events", []),
            reset_config=self._task.initial_config,
            task_goal=self._task.evaluator_goal,
            seed=self._task.seed,
            terminated=bool(runtime_result.get("terminated", False)),
            truncated=bool(runtime_result.get("truncated", False)),
        )
        try:
            validate_tool_execution(
                world_spec=self._contracts.world_spec,
                rules=self._contracts.rules,
                tool=tool,
                context=context,
                evidence=ToolExecutionEvidence(
                    response_ok=invoked.ok,
                    result_present=invoked.result is not None,
                    error_code=error_code,
                    error_message=(invoked.error.message if invoked.error is not None else None),
                    error_details=(
                        dict(invoked.error.details) if invoked.error is not None else {}
                    ),
                    pre_state_digest=_content_hash(before.get("state_digest")),
                    post_state_digest=after_digest,
                ),
            )
        except ToolSemanticValidationError as exc:
            raise LocalConsumerError("runtime_world_semantics", str(exc)) from exc
        trusted = self._contracts.evaluator.evaluate(self._task.task_type, context)
        self._terminated = trusted.terminated
        self._succeeded = trusted.succeeded
        self._failed = trusted.failed
        self._truncated = (
            not self._terminated and index + 1 >= self._selection.curriculum_policy.maximum_steps
        )
        agent_view: dict[str, JsonValue] = {
            "observation": observation,
            "tool_result": runtime_result.get("tool_result"),
        }
        step = RolloutStep(
            step_index=index,
            action=action,
            agent_view=agent_view,
            state_digest=after_digest,
            reward=trusted.reward,
            terminated=self._terminated,
            truncated=self._truncated,
            succeeded=self._succeeded,
            failed=self._failed,
            runtime_ok=invoked.ok,
            runtime_error_code=error_code,
        )
        self._steps.append(step)
        self._before = after
        return step

    def result(self) -> LocalRolloutResult:
        self._require_active()
        return LocalRolloutResult(
            episode_id=self._episode_id,
            snapshot_id=self._snapshot.snapshot_id,
            package=self._selection,
            task=self.public_task,
            reset=self.reset,
            steps=tuple(self._steps),
            terminated=self._terminated,
            truncated=self._truncated,
            succeeded=self._succeeded,
            failed=self._failed,
        )

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._supervisor.close()
        finally:
            await self._materialization.__aexit__(None, None, None)
            self._closed = True

    async def _close_runtime_only(self) -> None:
        await self._supervisor.close()

    async def __aenter__(self) -> LocalEpisode:
        self._require_active()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    def _require_active(self) -> None:
        if not self._started:
            raise LocalConsumerError("episode_not_started", "episode is not initialized")
        if self._closed:
            raise LocalConsumerError("episode_closed", "episode is already closed")


def _select_package(
    snapshot: EnvironmentSuiteSnapshot,
    seed: int,
) -> SuitePackageSelection:
    total = sum((item.weight for item in snapshot.packages), Decimal(0))
    fraction = Decimal(_seeded_integer(seed, f"{snapshot.snapshot_digest}:package")) / Decimal(
        2**256
    )
    threshold = fraction * total
    cumulative = Decimal(0)
    for item in snapshot.packages:
        cumulative += item.weight
        if threshold < cumulative:
            return item
    return snapshot.packages[-1]


def _seeded_choice(values: Sequence[Any], *, seed: int, label: str) -> Any:
    if not values:
        raise ValueError("cannot sample from an empty sequence")
    return values[_seeded_integer(seed, label) % len(values)]


def _seeded_integer(seed: int, label: str) -> int:
    return int.from_bytes(
        hashlib.sha256(canonical_json_bytes({"seed": seed, "label": label})).digest(),
        "big",
    )


def _episode_id(
    snapshot_digest: str,
    selection: SuitePackageSelection,
    seed: int,
) -> str:
    digest = sha256_digest(
        canonical_json_bytes(
            {
                "snapshot_digest": snapshot_digest,
                "package_digest": selection.package_digest,
                "seed": seed,
            }
        )
    )
    return f"episode_{digest.removeprefix('sha256:')}"


def _role_paths(
    manifest: EnvironmentPackageManifest,
    role: str,
) -> tuple[str, ...]:
    if role not in {"runtime", "task_materializer", "public_verifier"}:
        raise LocalConsumerError(
            "package_role_missing",
            f"released package requested unknown component role {role}",
        )
    try:
        return component_visible_paths(
            manifest.files,
            cast(CandidateComponentRole, role),
        )
    except ValueError as exc:
        raise LocalConsumerError(
            "package_role_missing",
            f"released package has no files for required role {role}",
        ) from exc


def _read_declared(
    root: Path,
    manifest: EnvironmentPackageManifest,
    path: str,
) -> bytes:
    descriptor = next((item for item in manifest.files if item.path == path), None)
    if descriptor is None:
        raise LocalConsumerError(
            "portable_contracts",
            f"manifest does not declare required package file {path}",
        )
    return _read_verified_file(root, path, descriptor.content_hash, descriptor.size_bytes)


def _read_verified_file(root: Path, path: str, expected_hash: str, expected_size: int) -> bytes:
    content = _read_regular_file(root, path)
    if len(content) != expected_size or sha256_digest(content) != expected_hash:
        raise LocalConsumerError(
            "materialized_package_hash",
            f"clean materialization changed packaged file {path}",
        )
    return content


def _read_regular_file(root: Path, path: str) -> bytes:
    target = root.joinpath(*PurePosixPath(path).parts)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise LocalConsumerError(
            "materialized_package_file",
            f"cannot safely open packaged file {path}",
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise LocalConsumerError(
                "materialized_package_file",
                f"packaged path is not a regular file: {path}",
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_projection(
    observation: JsonValue,
    *,
    schema: dict[str, JsonValue],
    visible_fields: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(observation, dict):
        raise LocalConsumerError("observation_projection", f"{label} is not an object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise LocalConsumerError(
            "observation_projection",
            f"{label} schema has no object properties",
        )
    visible = set(visible_fields)
    if set(observation) - visible:
        raise LocalConsumerError(
            "observation_projection",
            f"{label} disclosed fields outside the actor projection",
        )
    try:
        projected_schema = actor_projection_schema(schema, visible_fields)
    except ValueError as exc:
        raise LocalConsumerError(
            "observation_projection",
            f"{label} schema cannot compile an actor projection",
        ) from exc
    if tuple(Draft202012Validator(projected_schema).iter_errors(observation)):
        raise LocalConsumerError(
            "observation_projection",
            f"{label} violates the actor-projected schema",
        )


def _content_hash(value: JsonValue | None) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise LocalConsumerError(
            "runtime_state_digest",
            "Runtime snapshot omitted a valid state digest",
        )
    return value


__all__ = ["LocalConsumerError", "LocalEpisode", "LocalRolloutConsumer"]
