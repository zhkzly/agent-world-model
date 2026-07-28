"""Real-Agent Environment Builder with a framework-owned trust boundary."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import stat
import tarfile
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import JsonValue, ValidationError

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    CandidateManifest,
    EnvironmentCandidate,
    EnvironmentDesign,
    Finding,
    ImplementationLineage,
    PermissionScope,
    PublicSelfCheckDescriptor,
    RuntimeLaunch,
    TaskMaterializerDescriptor,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.decision import StructuredRepairMode
from agent_world.control.feedback import RepairTargetRef
from agent_world.control.repair import StructuredRepairAuthority, StructuredRepairDenied
from agent_world.control.validation import (
    SafeValidationIssue,
    ValidationDiagnostic,
    pydantic_validation_diagnostic,
)
from agent_world.invocation import (
    AgentOutputAuthority,
    CapabilityResolutionError,
    ExternalCapabilitySet,
    InvocationBackend,
    InvocationError,
    InvocationLimits,
    InvocationRequest,
    InvocationSession,
    InvocationStatus,
    InvocationUsage,
    NodeCapabilityRequirement,
    ResolvedAgentProfile,
    assert_agent_output_advisory,
)
from agent_world.invocation.redaction import Redactor, redacted_terminal_diagnostic_excerpt
from agent_world.invocation.structured_diagnostics import (
    safe_terminal_code,
    safe_terminal_condition,
    safe_terminal_details,
    safe_terminal_expected_category,
    terminal_failure_retryable,
)
from agent_world.task_materialization import compile_task_materializer_output_schema

from .models import (
    BuilderWorkspaceProgress,
    BuildRecord,
    CandidateCompletion,
    ImplementationContract,
    ImplementationPlan,
    RepairDisclosure,
    RuntimeOperationContract,
    RuntimeWireContract,
    TaskMaterializerContract,
    ToolBindingRequirement,
    normalize_candidate_completion_output,
)
from .workspace import (
    CandidateWorkspaceDiagnostic,
    CandidateWorkspaceError,
    CandidateWorkspaceValidator,
    ValidatedCandidateFile,
    ValidatedCandidateWorkspace,
)

_FORBIDDEN_RUNTIME_KEYS = (
    "task_id",
    "case_id",
    "case_label",
    "framework_private",
    "expected_answer",
    "expected_state",
    "expected_output",
    "evaluator_goal",
    "private_goal",
    "oracle",
    "oracle_data",
    "sealed_case",
    "sealed_data",
    "verifier_ir",
    "verifier_spec",
    "release_decision",
    "release_label",
    "release_threshold",
)
_BUILD_VALIDATIONS = (
    "declared_file_closure",
    "regular_file_only",
    "no_symlink_or_hardlink",
    "utf8_source_only",
    "secret_literal_scan",
    "portable_path_scan",
    "python_uv_project",
    "locked_dependencies",
    "virtual_non_installed_root",
    "offline_wheel_only_dependencies",
    "required_component_paths",
    "deterministic_source_snapshot",
)
_DERIVED_CACHE_DIRECTORIES = frozenset(
    {".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)


class AgentProfileProvider(Protocol):
    """Resolve the dedicated Engineer profile without leaking adapter types."""

    def resolve(
        self,
        *,
        role: str,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        permissions: PermissionScope,
        requirement: NodeCapabilityRequirement,
        rollout_token_limit: int | None = None,
        invocation_timeout_seconds: float | None = None,
    ) -> ResolvedAgentProfile: ...


@dataclass(frozen=True, slots=True)
class BuilderSessionState:
    """Ephemeral continuation state; it must never be stored in envpkg/artifacts."""

    run_id: str
    attempt_id: str
    lineage_id: str
    candidate_id: str
    workspace: Path
    profile: ResolvedAgentProfile
    invocation_session: InvocationSession | None
    # The resolved profile may carry a larger logical session envelope.  These
    # are the bounded reservation limits for one physical Scheduler turn and
    # therefore also cap unknown usage when a Provider omits metering.
    physical_turn_token_limit: int
    physical_turn_timeout_seconds: float
    design: EnvironmentDesign
    design_ref: ArtifactRef
    implementation_contract: ImplementationContract
    implementation_contract_ref: ArtifactRef
    input_hashes: tuple[tuple[str, str], ...]
    parent_workspace_refs: tuple[ArtifactRef, ...]
    implementation_plan_ref: ArtifactRef | None = None
    prior_snapshot_refs: tuple[ArtifactRef, ...] = ()
    repair_count: int = 0


@dataclass(frozen=True, slots=True)
class BuildInvocationSummary:
    """Non-transcript execution metadata safe for the controller to inspect."""

    invocation_id: str
    status: InvocationStatus
    duration_ms: int
    usage: InvocationUsage | None
    backend_version: str | None
    turns: int = 1
    total_tokens: int = 0
    unknown_token_upper_bounds: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class BuildBundle:
    implementation_contract: ImplementationContract
    implementation_contract_ref: ArtifactRef
    source_snapshot_ref: ArtifactRef
    implementation_lineage: ImplementationLineage
    implementation_lineage_ref: ArtifactRef
    candidate_manifest: CandidateManifest
    candidate_manifest_ref: ArtifactRef
    build_record: BuildRecord
    build_artifact_ref: ArtifactRef
    candidate: EnvironmentCandidate
    candidate_ref: ArtifactRef
    project_root: Path
    session: InvocationSession | None
    state: BuilderSessionState | None
    invocation: BuildInvocationSummary


class BuilderError(RuntimeError):
    """Honest terminal failure with optional same-session repair state."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        state: BuilderSessionState | None = None,
        invocation: BuildInvocationSummary | None = None,
        backend_error_code: str | None = None,
        backend_retryable: bool = False,
        backend_error_details: dict[str, JsonValue] | None = None,
        diagnostic_terminal_excerpt: str | None = None,
        permission_denied: bool = False,
    ) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.state = state
        self.invocation = invocation
        self.backend_error_code = backend_error_code
        self.backend_retryable = backend_retryable
        self.backend_error_details = dict(backend_error_details or {})
        # This is a redacted, explicitly opted-in local diagnostic aid.  It
        # must not flow into artifacts, telemetry, Scheduler feedback, or a
        # normal Builder error category.
        self.diagnostic_terminal_excerpt = diagnostic_terminal_excerpt
        self.permission_denied = permission_denied


class EnvironmentBuilder:
    """Compile a frozen design into an untrusted, inspectable candidate project.

    Builder creates no release verdict and executes no Judge/private verifier.
    It invokes only the real Environment Engineer profile.  Failed invocations
    and invalid workspaces raise ``BuilderError``; there is no alternate codegen
    path.
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactWriter,
        invocation_backend: InvocationBackend,
        profile_provider: AgentProfileProvider,
        workspace_validator: CandidateWorkspaceValidator | None = None,
        dependency_network_domains: Sequence[str] = (),
        maximum_repair_attempts: int = 3,
        maximum_precommit_reworks: int = 2,
        workspace_heartbeat_seconds: float = 30.0,
        turn_token_limit: int = 262_144,
        turn_timeout_seconds: float = 2_700.0,
    ) -> None:
        if (
            maximum_repair_attempts < 0
            or maximum_precommit_reworks < 0
            or workspace_heartbeat_seconds <= 0
            or turn_token_limit <= 0
            or turn_timeout_seconds <= 0
        ):
            raise ValueError("Builder rework and workspace heartbeat policy is invalid")
        self.artifacts = artifact_store
        self.backend = invocation_backend
        self.profiles = profile_provider
        self.validator = workspace_validator or CandidateWorkspaceValidator()
        self.dependency_capabilities = ExternalCapabilitySet(
            network_domains=tuple(sorted(dependency_network_domains)),
        )
        self.maximum_repair_attempts = maximum_repair_attempts
        self.maximum_precommit_reworks = maximum_precommit_reworks
        self.workspace_heartbeat_seconds = workspace_heartbeat_seconds
        self.turn_token_limit = turn_token_limit
        self.turn_timeout_seconds = turn_timeout_seconds

    def create_implementation_contract(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
    ) -> tuple[ImplementationContract, ArtifactRef]:
        """Compile and persist the exact, framework-owned codegen contract."""

        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )

        world = design.world_spec
        contract = ImplementationContract(
            contract_id=self._stable_id(
                "implementation-contract",
                design_ref.revision_id,
                world.content_digest(),
            ),
            design_ref=design_ref,
            world_spec_hash=world.content_digest(),
            state_schema_hash=world.state.content_digest(),
            curriculum_hash=design.curriculum.content_digest(),
            runtime=self._runtime_wire_contract(),
            tools=tuple(
                ToolBindingRequirement(
                    tool_id=tool.surface.tool_id,
                    tool_contract_hash=tool.content_digest(),
                )
                for tool in world.tools
            ),
            task_materializer=TaskMaterializerContract(
                task_types=tuple(task.task_type for task in design.curriculum.task_types),
                minimum_distinct_initial_states=(design.curriculum.minimum_distinct_initial_states),
                minimum_distinct_tasks_per_type=(design.curriculum.minimum_distinct_tasks_per_type),
            ),
        )
        contract_ref = self.artifacts.put_json(
            artifact_id=f"{design.design_id}:implementation-contract",
            artifact_type="build.implementation_contract",
            value=contract,
            dependencies=(design_ref,),
        )
        return contract, contract_ref

    def _implementation_contract_for_build(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        implementation_plan: ImplementationPlan | None,
        implementation_plan_ref: ArtifactRef | None,
    ) -> tuple[ImplementationContract, ArtifactRef]:
        """Choose the exact contract that a later CandidateBuild may consume.

        A plan is advisory text, but the framework-owned contract it binds is
        not.  The normal graph passes both values from BuildImplementationPlan;
        direct callers without that preceding node retain the historical
        one-step behavior.  No branch accepts an unbound plan or asks the
        Agent to reconstruct an ArtifactRef from prose.
        """

        if implementation_plan is None and implementation_plan_ref is None:
            return self.create_implementation_contract(design=design, design_ref=design_ref)
        if implementation_plan is None or implementation_plan_ref is None:
            raise BuilderError(
                "implementation_plan",
                "CandidateBuild requires both the exact advisory plan and its ArtifactRef",
            )
        self.artifacts.require_exact_json(
            implementation_plan_ref,
            implementation_plan,
            artifact_types=("build.implementation_plan",),
        )
        if (
            implementation_plan.design_ref != design_ref
            or implementation_plan.world_spec_hash != design.world_spec.content_digest()
            or implementation_plan.curriculum_hash != design.curriculum.content_digest()
        ):
            raise BuilderError(
                "implementation_plan",
                "advisory plan does not bind the exact frozen EnvironmentDesign closure",
            )
        contract_ref = implementation_plan.implementation_contract_ref
        contract = self.artifacts.get_json(contract_ref, ImplementationContract)
        self.artifacts.require_exact_json(
            contract_ref,
            contract,
            artifact_types=("build.implementation_contract",),
        )
        if (
            contract.design_ref != design_ref
            or contract.world_spec_hash != design.world_spec.content_digest()
            or contract.curriculum_hash != design.curriculum.content_digest()
        ):
            raise BuilderError(
                "implementation_plan",
                "implementation plan refers to a contract outside the frozen Design closure",
            )
        return contract, contract_ref

    def recover_committed_candidate(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        workspace: Path,
    ) -> BuildBundle | None:
        """Recover one exact committed candidate without invoking an Agent.

        Recovery is deliberately content- and dependency-driven.  A candidate is
        reusable only when every Builder artifact still binds the exact immutable
        design and the source tar reproduces the complete declared file set.  This
        is a checkpoint adoption path, not a second code-generation path.
        """

        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        lineage_id = self._stable_id("implementation", design_ref.revision_id)
        candidate_id = self._stable_id("candidate", lineage_id)
        recovered: list[tuple[ArtifactRef, EnvironmentCandidate]] = []
        for ref in self.artifacts.list_revisions(f"{candidate_id}:candidate"):
            if ref.artifact_type != "build.environment_candidate":
                raise BuilderError(
                    "recovery",
                    "candidate artifact id contains an unexpected artifact type",
                )
            candidate = self.artifacts.get_json(ref, EnvironmentCandidate)
            self.artifacts.require_exact_json(
                ref,
                candidate,
                artifact_types=("build.environment_candidate",),
            )
            if candidate.design_ref == design_ref:
                recovered.append((ref, candidate))
        if not recovered:
            return None

        latest_revision = max(candidate.revision for _, candidate in recovered)
        latest = tuple(item for item in recovered if item[1].revision == latest_revision)
        if len(latest) != 1:
            raise BuilderError(
                "recovery",
                "multiple committed candidates claim the same latest revision",
            )
        candidate_ref, candidate = latest[0]
        contract = self.artifacts.get_json(
            candidate.implementation_contract_ref,
            ImplementationContract,
        )
        self.artifacts.require_exact_json(
            candidate.implementation_contract_ref,
            contract,
            artifact_types=("build.implementation_contract",),
        )
        manifest = self.artifacts.get_json(
            candidate.candidate_manifest_ref,
            CandidateManifest,
        )
        self.artifacts.require_exact_json(
            candidate.candidate_manifest_ref,
            manifest,
            artifact_types=("build.candidate_manifest",),
        )
        build_record = self.artifacts.get_json(candidate.build_artifact_ref, BuildRecord)
        self.artifacts.require_exact_json(
            candidate.build_artifact_ref,
            build_record,
            artifact_types=("build.record",),
        )
        lineage = self.artifacts.get_json(
            candidate.implementation_lineage_ref,
            ImplementationLineage,
        )
        self.artifacts.require_exact_json(
            candidate.implementation_lineage_ref,
            lineage,
            artifact_types=("build.implementation_lineage",),
        )
        source_ref = candidate.source_workspace_snapshot_ref
        source_revision = self.artifacts.get_revision(source_ref)
        if (
            source_ref.artifact_type != "build.source_workspace_snapshot"
            or source_ref.media_type != "application/x-tar"
            or source_revision.ref != source_ref
        ):
            raise BuilderError("recovery", "candidate source snapshot has an invalid contract")

        expected_contract = ImplementationContract(
            contract_id=self._stable_id(
                "implementation-contract",
                design_ref.revision_id,
                design.world_spec.content_digest(),
            ),
            design_ref=design_ref,
            world_spec_hash=design.world_spec.content_digest(),
            state_schema_hash=design.world_spec.state.content_digest(),
            curriculum_hash=design.curriculum.content_digest(),
            runtime=self._runtime_wire_contract(),
            tools=tuple(
                ToolBindingRequirement(
                    tool_id=tool.surface.tool_id,
                    tool_contract_hash=tool.content_digest(),
                )
                for tool in design.world_spec.tools
            ),
            task_materializer=TaskMaterializerContract(
                task_types=tuple(task.task_type for task in design.curriculum.task_types),
                minimum_distinct_initial_states=(design.curriculum.minimum_distinct_initial_states),
                minimum_distinct_tasks_per_type=(design.curriculum.minimum_distinct_tasks_per_type),
            ),
        )
        uv_lock = next((item for item in manifest.files if item.path == "uv.lock"), None)
        bindings_valid = (
            contract == expected_contract
            and candidate.candidate_id == candidate_id
            and candidate.design_ref == design_ref
            and manifest.candidate_id == candidate_id
            and manifest.design_ref == design_ref
            and candidate.runtime == manifest.runtime
            and candidate.task_materializer == manifest.task_materializer
            and candidate.public_self_check == manifest.public_self_check
            and candidate.public_verifier_ref == manifest.public_verifier_ref
            and candidate.implementation_lineage_ref == manifest.implementation_lineage_ref
            and build_record.candidate_id == candidate_id
            and build_record.candidate_revision == candidate.revision
            and build_record.implementation_contract_ref == candidate.implementation_contract_ref
            and build_record.source_snapshot_ref == source_ref
            and build_record.files == manifest.files
            and lineage.implementation_contract_ref == candidate.implementation_contract_ref
            and lineage.source_snapshot_refs == (source_ref,)
            and uv_lock is not None
            and lineage.dependency_lock_hash == uv_lock.content_hash
        )
        if not bindings_valid:
            raise BuilderError(
                "recovery",
                "committed candidate artifact graph does not close over the exact design",
            )

        self.materialize_implementation_inputs(
            workspace=workspace,
            design=design,
            contract=contract,
        )
        project_root = self._materialize_verified_snapshot(
            workspace=workspace,
            source=self.artifacts.get_blob(source_ref),
            manifest=manifest,
        )
        return BuildBundle(
            implementation_contract=contract,
            implementation_contract_ref=candidate.implementation_contract_ref,
            source_snapshot_ref=source_ref,
            implementation_lineage=lineage,
            implementation_lineage_ref=candidate.implementation_lineage_ref,
            candidate_manifest=manifest,
            candidate_manifest_ref=candidate.candidate_manifest_ref,
            build_record=build_record,
            build_artifact_ref=candidate.build_artifact_ref,
            candidate=candidate,
            candidate_ref=candidate_ref,
            project_root=project_root,
            session=None,
            state=None,
            invocation=BuildInvocationSummary(
                invocation_id=self._stable_id("build-recovery", candidate_ref.revision_id),
                status=InvocationStatus.COMPLETED,
                duration_ms=0,
                usage=None,
                backend_version="artifact-checkpoint-v1",
                turns=0,
                total_tokens=0,
            ),
        )

    def materialize_exact_candidate(
        self,
        *,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
        workspace: Path,
    ) -> Path:
        """Restore exactly one committed Candidate source closure without an Agent.

        Judge leaves must not rely on the Builder process' in-memory workspace:
        a Scheduler restart can happen between Build and Integration.  The
        candidate's immutable source snapshot and manifest are therefore the
        sole recovery inputs.  This is deliberately narrower than
        :meth:`recover_committed_candidate`: no "latest candidate" selection
        is allowed, because the caller already binds one exact Candidate ref.
        """

        self.artifacts.require_exact_json(
            candidate_ref,
            candidate,
            artifact_types=("build.environment_candidate",),
        )
        manifest = self.artifacts.get_json(
            candidate.candidate_manifest_ref,
            CandidateManifest,
        )
        self.artifacts.require_exact_json(
            candidate.candidate_manifest_ref,
            manifest,
            artifact_types=("build.candidate_manifest",),
        )
        if (
            manifest.candidate_id != candidate.candidate_id
            or manifest.design_ref != candidate.design_ref
            or manifest.implementation_lineage_ref != candidate.implementation_lineage_ref
            or manifest.runtime != candidate.runtime
            or manifest.task_materializer != candidate.task_materializer
            or manifest.public_self_check != candidate.public_self_check
        ):
            raise BuilderError("recovery", "candidate and manifest do not bind one closure")
        snapshot_ref = candidate.source_workspace_snapshot_ref
        if (
            snapshot_ref.artifact_type != "build.source_workspace_snapshot"
            or snapshot_ref.media_type != "application/x-tar"
        ):
            raise BuilderError("recovery", "candidate source snapshot has an invalid contract")
        return self._materialize_verified_snapshot(
            workspace=workspace,
            source=self.artifacts.get_blob(snapshot_ref),
            manifest=manifest,
        )

    @staticmethod
    def _materialize_verified_snapshot(
        *,
        workspace: Path,
        source: bytes,
        manifest: CandidateManifest,
    ) -> Path:
        """Materialize a link-free tar only after matching every declared byte."""

        workspace = workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        project_root = workspace / "candidate"
        if project_root.exists() and any(project_root.iterdir()):
            raise BuilderError(
                "recovery.workspace",
                "recovery candidate workspace is not empty",
            )
        declared = {item.path: item for item in manifest.files}
        materialized: dict[str, tuple[bytes, int]] = {}
        try:
            with tarfile.open(fileobj=io.BytesIO(source), mode="r:") as archive:
                for member in archive.getmembers():
                    path = PurePosixPath(member.name)
                    normalized = path.as_posix()
                    if (
                        not member.isfile()
                        or path.is_absolute()
                        or ".." in path.parts
                        or "\\" in member.name
                        or normalized != member.name
                        or normalized not in declared
                        or normalized in materialized
                    ):
                        raise BuilderError(
                            "recovery.snapshot",
                            "source snapshot contains an unsafe or undeclared entry",
                        )
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise BuilderError(
                            "recovery.snapshot",
                            "source snapshot regular file has no readable content",
                        )
                    materialized[normalized] = (handle.read(), member.mode & 0o777)
        except (tarfile.TarError, OSError) as exc:
            raise BuilderError(
                "recovery.snapshot",
                "source snapshot is not a readable regular-file tar",
            ) from exc
        if set(materialized) != set(declared):
            raise BuilderError(
                "recovery.snapshot",
                "source snapshot does not contain the complete declared file closure",
            )
        for relative, descriptor in declared.items():
            data, mode = materialized[relative]
            expected_mode = 0o755 if descriptor.executable else 0o644
            if (
                len(data) != descriptor.size_bytes
                or sha256_digest(data) != descriptor.content_hash
                or mode != expected_mode
            ):
                raise BuilderError(
                    "recovery.snapshot",
                    f"source snapshot differs from manifest at {relative}",
                )

        project_root.mkdir(parents=True, exist_ok=True)
        for relative, descriptor in sorted(declared.items()):
            data, _ = materialized[relative]
            target = project_root.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            file_descriptor = os.open(
                target,
                flags,
                0o755 if descriptor.executable else 0o644,
            )
            try:
                with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
                    handle.write(data)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        return project_root

    async def build_once(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        workspace: Path,
        budget: Budget,
        permissions: PermissionScope,
        parent_workspace_refs: Sequence[ArtifactRef] = (),
        run_id: str,
        attempt_id: str,
        proposal_invocation_id: str | None = None,
        session_token_limit: int | None = None,
        session_wall_seconds: float | None = None,
        implementation_plan: ImplementationPlan | None = None,
        implementation_plan_ref: ArtifactRef | None = None,
        diagnostic_capture_terminal_excerpt: bool = False,
    ) -> BuildBundle:
        """Execute exactly one real Engineer proposal for a scheduler WorkAttempt.

        This is the production leaf shape used by the replacement WorkGraph:
        it may generate and deterministically validate one Candidate, but it may
        not authorize a corrective turn.  An actionable failure is returned to
        the framework Scheduler, which alone decides whether a RepairAction can
        create a later ``repair_once`` attempt.
        """

        return await self._build(
            design=design,
            design_ref=design_ref,
            workspace=workspace,
            budget=budget,
            permissions=permissions,
            parent_workspace_refs=parent_workspace_refs,
            repair_authority=None,
            run_id=run_id,
            attempt_id=attempt_id,
            allow_precommit_rework=False,
            proposal_invocation_id=proposal_invocation_id,
            session_token_limit=session_token_limit,
            session_wall_seconds=session_wall_seconds,
            implementation_plan=implementation_plan,
            implementation_plan_ref=implementation_plan_ref,
            diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
        )

    async def resume_output_limited_build(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        workspace: Path,
        session: InvocationSession,
        budget: Budget,
        permissions: PermissionScope,
        run_id: str,
        attempt_id: str,
        attempt_ordinal: int,
        proposal_invocation_id: str,
        session_token_limit: int,
        session_wall_seconds: float,
        implementation_plan: ImplementationPlan | None = None,
        implementation_plan_ref: ArtifactRef | None = None,
        diagnostic_capture_terminal_excerpt: bool = False,
    ) -> BuildBundle:
        """Resume one exact Builder session after a closed physical output ceiling.

        This method intentionally performs one physical SDK turn only.  It has
        no retry loop and receives no raw Provider text.  Scheduler owns the
        preceding output-limit report, continuation authority and next
        WorkAttempt; the Builder merely proves that its private session and
        workspace still bind the frozen CandidateBuild closure.
        """

        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self._validate_budget(budget, repair=False)
        if not isinstance(diagnostic_capture_terminal_excerpt, bool):
            raise BuilderError(
                "diagnostic",
                "Builder diagnostic terminal-excerpt control must be boolean",
            )
        if attempt_ordinal < 2:
            raise BuilderError(
                "continuation",
                "output-limit continuation requires a successor physical attempt",
            )
        workspace = workspace.expanduser().resolve()  # noqa: ASYNC240 - bounded setup I/O
        if (
            workspace.name != "workspace"
            or workspace.parent.name != ".agent-runtime"
            or not workspace.is_dir()
        ):
            raise BuilderError(
                "continuation",
                "continuation workspace does not match the isolated profile layout",
            )
        materialization_root = workspace.parent.parent
        contract, contract_ref = self._implementation_contract_for_build(
            design=design,
            design_ref=design_ref,
            implementation_plan=implementation_plan,
            implementation_plan_ref=implementation_plan_ref,
        )
        per_turn_token_limit, per_turn_timeout_seconds = self._initial_turn_envelope(
            budget,
            turn_limit=1,
        )
        logical_session_token_limit, logical_session_wall_seconds = self._logical_session_envelope(
            session_token_limit=session_token_limit,
            session_wall_seconds=session_wall_seconds,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
        )
        lineage_id = self._stable_id("implementation", design_ref.revision_id)
        candidate_id = self._stable_id("candidate", lineage_id)
        try:
            assert_agent_output_advisory(
                CandidateCompletion,
                authority=AgentOutputAuthority.WORKSPACE_PROPOSAL,
            )
            profile = self.profiles.resolve(
                role="environment-engineer",
                lineage_id=lineage_id,
                workspace=materialization_root,
                output_schema=CandidateCompletion.model_json_schema(mode="validation"),
                permissions=permissions,
                requirement=NodeCapabilityRequirement.isolated_build(
                    node_id="environment-engineer.runtime-build",
                    external=self.dependency_capabilities,
                ),
                rollout_token_limit=logical_session_token_limit,
                invocation_timeout_seconds=per_turn_timeout_seconds,
            )
        except CapabilityResolutionError as exc:
            raise BuilderError(
                "permissions",
                str(exc),
                permission_denied=True,
            ) from exc
        if profile.workspace != workspace:
            raise BuilderError(
                "continuation",
                "resolved Engineer profile does not preserve the continuation workspace",
            )
        self._validate_profile_budget(
            profile,
            budget,
            authorized_turns=1,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
        )
        input_hashes = self.materialize_implementation_inputs(
            workspace=profile.workspace,
            design=design,
            contract=contract,
            implementation_plan=implementation_plan,
        )
        state = BuilderSessionState(
            run_id=run_id,
            attempt_id=attempt_id,
            lineage_id=lineage_id,
            candidate_id=candidate_id,
            workspace=profile.workspace,
            profile=profile,
            invocation_session=session,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
            design=design,
            design_ref=design_ref,
            implementation_contract=contract,
            implementation_contract_ref=contract_ref,
            input_hashes=input_hashes,
            parent_workspace_refs=(),
            implementation_plan_ref=implementation_plan_ref,
        )
        self._validate_repair_session_binding(state)
        self._verify_framework_inputs(state)
        completion, next_session, invocation = await self._invoke_engineer(
            profile=profile,
            session=session,
            prompt=self._output_limit_continuation_prompt(),
            lineage_id=lineage_id,
            attempt=attempt_ordinal,
            error_state=state,
            invocation_id=proposal_invocation_id,
            diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
        )
        next_state = replace(state, invocation_session=next_session)
        return self._validate_and_commit(
            completion=completion,
            state=next_state,
            invocation=invocation,
        )

    async def resume_validation_repair(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        workspace: Path,
        session: InvocationSession,
        budget: Budget,
        permissions: PermissionScope,
        run_id: str,
        attempt_id: str,
        attempt_ordinal: int,
        proposal_invocation_id: str,
        session_token_limit: int,
        session_wall_seconds: float,
        correction_feedback: bytes,
        implementation_plan: ImplementationPlan | None = None,
        implementation_plan_ref: ArtifactRef | None = None,
        diagnostic_capture_terminal_excerpt: bool = False,
    ) -> BuildBundle:
        """Run one Scheduler-authorized semantic repair in the same workspace.

        This is neither an implicit retry nor a legacy Builder-owned loop.  A
        preceding ``ValidationReport -> FeedbackEvaluation -> RepairAction``
        has already selected this one correction.  The caller supplies only
        the safe data-only correction brief; framework authority, provider
        routing, and the failed candidate declaration remain outside the
        runtime Agent prompt.
        """

        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self._validate_budget(budget, repair=False)
        if not correction_feedback:
            raise BuilderError(
                "repair",
                "Scheduler-authorized Builder repair requires non-empty safe feedback",
            )
        if not isinstance(diagnostic_capture_terminal_excerpt, bool):
            raise BuilderError(
                "diagnostic",
                "Builder diagnostic terminal-excerpt control must be boolean",
            )
        if attempt_ordinal < 2:
            raise BuilderError(
                "repair",
                "semantic Builder repair requires a successor physical attempt",
            )
        workspace = workspace.expanduser().resolve()  # noqa: ASYNC240 - bounded setup I/O
        if (
            workspace.name != "workspace"
            or workspace.parent.name != ".agent-runtime"
            or not workspace.is_dir()
        ):
            raise BuilderError(
                "repair",
                "semantic repair workspace does not match the isolated profile layout",
            )
        materialization_root = workspace.parent.parent
        contract, contract_ref = self._implementation_contract_for_build(
            design=design,
            design_ref=design_ref,
            implementation_plan=implementation_plan,
            implementation_plan_ref=implementation_plan_ref,
        )
        per_turn_token_limit, per_turn_timeout_seconds = self._initial_turn_envelope(
            budget,
            turn_limit=1,
        )
        logical_session_token_limit, logical_session_wall_seconds = self._logical_session_envelope(
            session_token_limit=session_token_limit,
            session_wall_seconds=session_wall_seconds,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
        )
        lineage_id = self._stable_id("implementation", design_ref.revision_id)
        candidate_id = self._stable_id("candidate", lineage_id)
        try:
            assert_agent_output_advisory(
                CandidateCompletion,
                authority=AgentOutputAuthority.WORKSPACE_PROPOSAL,
            )
            profile = self.profiles.resolve(
                role="environment-engineer",
                lineage_id=lineage_id,
                workspace=materialization_root,
                output_schema=CandidateCompletion.model_json_schema(mode="validation"),
                permissions=permissions,
                requirement=NodeCapabilityRequirement.isolated_build(
                    node_id="environment-engineer.runtime-build",
                    external=self.dependency_capabilities,
                ),
                rollout_token_limit=logical_session_token_limit,
                invocation_timeout_seconds=per_turn_timeout_seconds,
            )
        except CapabilityResolutionError as exc:
            raise BuilderError(
                "permissions",
                str(exc),
                permission_denied=True,
            ) from exc
        if profile.workspace != workspace:
            raise BuilderError(
                "repair",
                "resolved Engineer profile does not preserve the repair workspace",
            )
        self._validate_profile_budget(
            profile,
            budget,
            authorized_turns=1,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
        )
        input_hashes = self.materialize_implementation_inputs(
            workspace=profile.workspace,
            design=design,
            contract=contract,
            implementation_plan=implementation_plan,
        )
        disclosure_name = f"scheduler-repair-{attempt_ordinal}.json"
        disclosure_path = profile.workspace / "inputs" / disclosure_name
        self._assert_no_secret_values(correction_feedback, profile.secret_values)
        self._write_immutable(disclosure_path, correction_feedback)
        input_hashes = tuple(
            sorted(
                (
                    *input_hashes,
                    (
                        disclosure_path.relative_to(profile.workspace).as_posix(),
                        sha256_digest(correction_feedback),
                    ),
                )
            )
        )
        state = BuilderSessionState(
            run_id=run_id,
            attempt_id=attempt_id,
            lineage_id=lineage_id,
            candidate_id=candidate_id,
            workspace=profile.workspace,
            profile=profile,
            invocation_session=session,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
            design=design,
            design_ref=design_ref,
            implementation_contract=contract,
            implementation_contract_ref=contract_ref,
            input_hashes=input_hashes,
            parent_workspace_refs=(),
            implementation_plan_ref=implementation_plan_ref,
            repair_count=attempt_ordinal - 1,
        )
        self._validate_repair_session_binding(state)
        self._verify_framework_inputs(state)
        completion, next_session, invocation = await self._invoke_engineer(
            profile=profile,
            session=session,
            prompt=self._scheduler_repair_prompt(attempt_ordinal, disclosure_name),
            lineage_id=lineage_id,
            attempt=attempt_ordinal,
            error_state=state,
            invocation_id=proposal_invocation_id,
            diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
        )
        next_state = replace(state, invocation_session=next_session)
        return self._validate_and_commit(
            completion=completion,
            state=next_state,
            invocation=invocation,
        )

    async def build(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        workspace: Path,
        budget: Budget,
        permissions: PermissionScope,
        parent_workspace_refs: Sequence[ArtifactRef] = (),
        repair_authority: StructuredRepairAuthority | None = None,
        run_id: str,
        attempt_id: str,
        implementation_plan: ImplementationPlan | None = None,
        implementation_plan_ref: ArtifactRef | None = None,
        diagnostic_capture_terminal_excerpt: bool = False,
    ) -> BuildBundle:
        """Legacy multi-turn façade pending the complete Controller cutover.

        New WorkGraph leaf executors must call :meth:`build_once`; this method
        remains only while the old Controller path is being removed as one
        vertical migration, rather than exposing a second production authority.
        """

        return await self._build(
            design=design,
            design_ref=design_ref,
            workspace=workspace,
            budget=budget,
            permissions=permissions,
            parent_workspace_refs=parent_workspace_refs,
            repair_authority=repair_authority,
            run_id=run_id,
            attempt_id=attempt_id,
            allow_precommit_rework=True,
            proposal_invocation_id=None,
            session_token_limit=None,
            session_wall_seconds=None,
            implementation_plan=implementation_plan,
            implementation_plan_ref=implementation_plan_ref,
            diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
        )

    async def _build(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        workspace: Path,
        budget: Budget,
        permissions: PermissionScope,
        parent_workspace_refs: Sequence[ArtifactRef],
        repair_authority: StructuredRepairAuthority | None,
        run_id: str,
        attempt_id: str,
        allow_precommit_rework: bool,
        proposal_invocation_id: str | None,
        session_token_limit: int | None,
        session_wall_seconds: float | None,
        implementation_plan: ImplementationPlan | None,
        implementation_plan_ref: ArtifactRef | None,
        diagnostic_capture_terminal_excerpt: bool,
    ) -> BuildBundle:
        """Run an Engineer proposal, optionally through the legacy correction loop."""

        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self._validate_budget(budget, repair=False)
        if not isinstance(diagnostic_capture_terminal_excerpt, bool):
            raise BuilderError(
                "diagnostic",
                "Builder diagnostic terminal-excerpt control must be boolean",
            )
        workspace = workspace.expanduser().resolve()  # noqa: ASYNC240 - bounded setup I/O
        workspace.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        candidate_root = workspace / "candidate"
        if candidate_root.exists() and any(candidate_root.iterdir()):  # noqa: ASYNC240
            raise BuilderError(
                "workspace",
                "initial candidate workspace is not empty; refusing to overwrite prior state",
            )

        contract, contract_ref = self._implementation_contract_for_build(
            design=design,
            design_ref=design_ref,
            implementation_plan=implementation_plan,
            implementation_plan_ref=implementation_plan_ref,
        )
        input_hashes = self.materialize_implementation_inputs(
            workspace=workspace,
            design=design,
            contract=contract,
            implementation_plan=implementation_plan,
        )
        lineage_id = self._stable_id("implementation", design_ref.revision_id)
        candidate_id = self._stable_id("candidate", lineage_id)
        turn_limit = (
            min(budget.agent_turns, self.maximum_precommit_reworks + 1)
            if allow_precommit_rework
            else 1
        )
        per_turn_token_limit, per_turn_timeout_seconds = self._initial_turn_envelope(
            budget,
            turn_limit=turn_limit,
        )
        logical_session_token_limit, logical_session_wall_seconds = self._logical_session_envelope(
            session_token_limit=session_token_limit,
            session_wall_seconds=session_wall_seconds,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
        )
        try:
            assert_agent_output_advisory(
                CandidateCompletion,
                authority=AgentOutputAuthority.WORKSPACE_PROPOSAL,
            )
            profile = self.profiles.resolve(
                role="environment-engineer",
                lineage_id=lineage_id,
                workspace=workspace,
                output_schema=CandidateCompletion.model_json_schema(mode="validation"),
                permissions=permissions,
                requirement=NodeCapabilityRequirement.isolated_build(
                    node_id="environment-engineer.runtime-build",
                    external=self.dependency_capabilities,
                ),
                rollout_token_limit=logical_session_token_limit,
                invocation_timeout_seconds=per_turn_timeout_seconds,
            )
        except CapabilityResolutionError as exc:
            raise BuilderError(
                "permissions",
                str(exc),
                permission_denied=True,
            ) from exc
        self._validate_profile_budget(
            profile,
            budget,
            authorized_turns=turn_limit,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
        )
        candidate_root = profile.workspace / "candidate"
        if candidate_root.exists() and any(candidate_root.iterdir()):  # noqa: ASYNC240
            raise BuilderError(
                "workspace",
                "resolved Engineer candidate workspace is not empty; refusing to overwrite it",
            )
        provisional_state = BuilderSessionState(
            run_id=run_id,
            attempt_id=attempt_id,
            lineage_id=lineage_id,
            candidate_id=candidate_id,
            workspace=profile.workspace,
            profile=profile,
            invocation_session=None,
            physical_turn_token_limit=per_turn_token_limit,
            physical_turn_timeout_seconds=per_turn_timeout_seconds,
            design=design,
            design_ref=design_ref,
            implementation_contract=contract,
            implementation_contract_ref=contract_ref,
            input_hashes=input_hashes,
            parent_workspace_refs=self._unique_refs(parent_workspace_refs),
            implementation_plan_ref=implementation_plan_ref,
        )
        self._verify_framework_inputs(provisional_state)
        state = provisional_state
        prompt = self._initial_prompt(
            design,
            has_implementation_plan=implementation_plan is not None,
        )
        invocation_summaries: list[BuildInvocationSummary] = []
        active_repair_entry: str | None = None

        async def complete_repair(
            remaining_issue_codes: tuple[str, ...],
            diagnostic: ValidationDiagnostic | None = None,
        ) -> None:
            nonlocal active_repair_entry
            if active_repair_entry is None or repair_authority is None:
                active_repair_entry = None
                return
            try:
                await repair_authority.complete(
                    active_repair_entry,
                    remaining_issue_codes=remaining_issue_codes,
                    continued_session=state.invocation_session is not None,
                    remaining_diagnostic=diagnostic,
                )
            except Exception as exc:
                raise BuilderError(
                    "repair_authority",
                    f"global RepairLedger completion failed: {type(exc).__name__}",
                    state=state,
                    invocation=(
                        self._merge_invocation_summaries(invocation_summaries)
                        if invocation_summaries
                        else None
                    ),
                ) from exc
            active_repair_entry = None

        async def authorize_repair(diagnostic: ValidationDiagnostic) -> None:
            nonlocal active_repair_entry
            if repair_authority is None:
                return
            try:
                active_repair_entry = await repair_authority.authorize(
                    owner_node="build",
                    lineage_id=lineage_id,
                    role="environment-engineer",
                    repair_mode=StructuredRepairMode.BUILDER_PRECOMMIT_CORRECTION,
                    issue_codes=diagnostic.issue_codes,
                    continued_session=True,
                    diagnostic=diagnostic,
                    feedback_contract_id="feedback.build.candidate",
                    repair_target=RepairTargetRef(
                        target_id=sha256_digest(
                            canonical_json_bytes(
                                {
                                    "lineage_id": lineage_id,
                                    "slot": "candidate_workspace",
                                }
                            )
                        ),
                        component="build",
                        artifact_slot="candidate_workspace",
                        lineage_id=lineage_id,
                        immutable_input_refs=(design_ref, contract_ref),
                        allowed_mutation_paths=("/candidate",),
                    ),
                )
            except StructuredRepairDenied as exc:
                raise BuilderError(
                    "repair_denied",
                    "global RepairLedger rejected another Builder pre-commit correction",
                    state=state,
                    invocation=(
                        self._merge_invocation_summaries(invocation_summaries)
                        if invocation_summaries
                        else None
                    ),
                ) from exc
            except Exception as exc:
                raise BuilderError(
                    "repair_authority",
                    f"global RepairLedger authorization failed: {type(exc).__name__}",
                    state=state,
                    invocation=(
                        self._merge_invocation_summaries(invocation_summaries)
                        if invocation_summaries
                        else None
                    ),
                ) from exc

        for turn_index in range(turn_limit):
            try:
                completion, session, invocation = await self._invoke_engineer(
                    profile=profile,
                    session=state.invocation_session,
                    prompt=prompt,
                    lineage_id=lineage_id,
                    attempt=turn_index + 1,
                    error_state=state,
                    invocation_id=(proposal_invocation_id if turn_index == 0 else None),
                    diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
                )
            except BuilderError as exc:
                if exc.invocation is not None:
                    invocation_summaries.append(exc.invocation)
                    exc.invocation = self._merge_invocation_summaries(invocation_summaries)
                diagnostic = self._validation_diagnostic(exc)
                await complete_repair(diagnostic.issue_codes, diagnostic)
                if any(not issue.retryable for issue in diagnostic.issues):
                    # A backend terminal already has an exact safe owner and
                    # retry classification.  Rewrapping it as a generic
                    # framework diagnostic would erase the Provider outcome
                    # before Scheduler can route it.
                    if self._backend_terminal_error(exc) is not None:
                        raise
                    raise BuilderError(
                        "framework.diagnostic",
                        "Builder reached a non-actionable framework diagnostic; refusing "
                        "to spend an Agent repair turn",
                        state=exc.state or state,
                        invocation=exc.invocation,
                        backend_error_code=exc.backend_error_code,
                        backend_retryable=exc.backend_retryable,
                        backend_error_details=exc.backend_error_details,
                        diagnostic_terminal_excerpt=exc.diagnostic_terminal_excerpt,
                    ) from exc
                if (
                    allow_precommit_rework
                    and exc.stage == "agent.output"
                    and exc.state is not None
                    and exc.state.invocation_session is not None
                    and turn_index + 1 < turn_limit
                ):
                    state = exc.state
                    await authorize_repair(diagnostic)
                    prompt = self._precommit_repair_prompt(
                        attempt=turn_index + 2,
                        error=diagnostic.feedback,
                    )
                    continue
                raise
            except Exception:
                await complete_repair(("builder_execution_failure",))
                raise
            invocation_summaries.append(invocation)
            state = replace(state, invocation_session=session)
            aggregate = self._merge_invocation_summaries(invocation_summaries)
            try:
                bundle = self._validate_and_commit(
                    completion=completion,
                    state=state,
                    invocation=aggregate,
                )
                await complete_repair(())
                return bundle
            except BuilderError as exc:
                exc.invocation = aggregate
                diagnostic = self._validation_diagnostic(exc)
                await complete_repair(diagnostic.issue_codes, diagnostic)
                if any(not issue.retryable for issue in diagnostic.issues):
                    if self._backend_terminal_error(exc) is not None:
                        raise
                    raise BuilderError(
                        "framework.diagnostic",
                        "Builder reached a non-actionable framework diagnostic; refusing "
                        "to spend an Agent repair turn",
                        state=exc.state or state,
                        invocation=aggregate,
                        backend_error_code=exc.backend_error_code,
                        backend_retryable=exc.backend_retryable,
                        backend_error_details=exc.backend_error_details,
                        diagnostic_terminal_excerpt=exc.diagnostic_terminal_excerpt,
                    ) from exc
                if (
                    allow_precommit_rework
                    and exc.stage == "candidate.validation"
                    and state.invocation_session is not None
                    and turn_index + 1 < turn_limit
                ):
                    await authorize_repair(diagnostic)
                    prompt = self._precommit_repair_prompt(
                        attempt=turn_index + 2,
                        error=diagnostic.feedback,
                    )
                    continue
                raise
        raise AssertionError("unreachable Builder pre-commit loop")

    @staticmethod
    def _validation_diagnostic(exc: BuilderError) -> ValidationDiagnostic:
        """Translate Builder validation into stable phases without raw workspace data."""

        backend_terminal = EnvironmentBuilder._backend_terminal_error(exc)
        if backend_terminal is not None:
            safe_code = EnvironmentBuilder._safe_backend_issue_code(
                safe_terminal_code(backend_terminal) or "terminal"
            )
            condition = safe_terminal_condition(backend_terminal)
            expected = safe_terminal_expected_category(backend_terminal)
            return ValidationDiagnostic(
                owner_component="build",
                validation_phase="agent_backend",
                frontier_ordinal=0,
                issues=(
                    SafeValidationIssue(
                        f"agent_backend_{safe_code}"[:160],
                        ("provider",),
                        condition,
                        retryable=terminal_failure_retryable(backend_terminal),
                        violated_condition=condition,
                        expected_category=(
                            expected
                            or "a safely classified Provider or transport remediation outside "
                            "this attempt"
                        ),
                    ),
                ),
            )

        # A framework diagnostic is only a safety wrapper around an earlier
        # Builder failure.  Preserve the original typed frontier for an
        # observer and an authorized correction route; the wrapper itself has
        # no semantic information to add.
        if exc.stage == "framework.diagnostic" and isinstance(exc.__cause__, BuilderError):
            return EnvironmentBuilder._validation_diagnostic(exc.__cause__)

        cause = exc.__cause__
        if exc.stage == "agent.output" and isinstance(cause, ValidationError):
            raw_errors = cause.errors(
                include_context=False,
                include_input=False,
                include_url=False,
            )[:64]
            fallback = pydantic_validation_diagnostic(
                cause,
                owner_component="build",
                validation_phase="completion_schema",
                frontier_ordinal=10,
            )
            catalog: dict[str, tuple[str, int, str, str]] = {
                "task_materializer_entrypoint_format": (
                    "completion_entrypoint_format",
                    15,
                    "task_materializer_entrypoint_format",
                    "Use `package.module:materialize`; do not use a path, filename, or "
                    "call expression.",
                ),
                "candidate_path_invalid": (
                    "completion_path_format",
                    12,
                    "candidate_path_invalid",
                    "Use a normalized candidate-relative POSIX path; do not use an absolute "
                    "path, `..`, or backslashes.",
                ),
                "python_entry_path_invalid": (
                    "completion_entrypoint_format",
                    15,
                    "python_entry_path_invalid",
                    "Use a normalized package-relative POSIX `.py` entry path.",
                ),
                "python_entry_path_not_importable": (
                    "completion_entrypoint_binding",
                    16,
                    "python_entry_path_not_importable",
                    "The entry path must map to an importable Python module.",
                ),
                "python_launch_interpreter_invalid": (
                    "completion_launch",
                    17,
                    "python_launch_interpreter_invalid",
                    "Start the launch argv with `.venv/bin/python` or `.venv/bin/python3`.",
                ),
                "python_launch_argument_invalid": (
                    "completion_launch",
                    17,
                    "python_launch_argument_invalid",
                    "Use only bounded relative launch arguments without backslashes, NUL, or `..`.",
                ),
                "python_launch_entrypoint_mismatch": (
                    "completion_launch",
                    17,
                    "python_launch_entrypoint_mismatch",
                    "Use `argv=[.venv/bin/python, -m, package.module]`, where the module is "
                    "derived from the declared `.py` entry_path.",
                ),
                "task_materializer_binding_mismatch": (
                    "completion_entrypoint_binding",
                    16,
                    "task_materializer_binding_mismatch",
                    "Map entry_path to its module by removing `.py`, replacing `/` with "
                    "`.`, ignoring a leading `src/` and trailing `__main__`; that module "
                    "must equal the entrypoint text before `:materialize`.",
                ),
                "completion_blocking_reason_missing": (
                    "completion_declarations",
                    20,
                    "completion_blocking_reason_missing",
                    "A blocked completion must contain one non-empty blocking reason.",
                ),
                "completion_blocked_claims_outputs": (
                    "completion_declarations",
                    20,
                    "completion_blocked_claims_outputs",
                    "A blocked completion must not claim candidate outputs.",
                ),
                "completion_completed_has_blocker": (
                    "completion_declarations",
                    20,
                    "completion_completed_has_blocker",
                    "A completed declaration must not contain a blocking reason.",
                ),
                "completion_missing_declarations": (
                    "completion_declarations",
                    20,
                    "completion_missing_declarations",
                    "A completed output must include every required declaration.",
                ),
                "completion_public_tests_missing": (
                    "completion_declarations",
                    20,
                    "completion_public_tests_missing",
                    "Declare at least one standalone public test.",
                ),
                "completion_files_missing": (
                    "completion_declarations",
                    20,
                    "completion_files_missing",
                    "Declare the complete final candidate file closure.",
                ),
                "completion_file_declarations_duplicate": (
                    "completion_manifest_binding",
                    25,
                    "completion_file_declarations_duplicate",
                    "Declare each candidate-relative file path exactly once.",
                ),
                "completion_required_role_missing": (
                    "completion_manifest_binding",
                    25,
                    "completion_required_role_missing",
                    "Every required component entry path must have its fixed file role.",
                ),
                "completion_public_test_role_invalid": (
                    "completion_manifest_binding",
                    25,
                    "completion_public_test_role_invalid",
                    "Every public test path must be declared with role `public_test`.",
                ),
            }
            conditions: dict[str, tuple[str | None, str | None]] = {
                "candidate_path_invalid": (
                    "candidate declarations must use normalized paths relative to the project root",
                    "one normalized candidate-relative POSIX path",
                ),
                "python_entry_path_invalid": (
                    "a Python component entry_path must be a candidate-relative `.py` file",
                    "one normalized candidate-relative POSIX `.py` path",
                ),
                "python_entry_path_not_importable": (
                    "a Python component entry_path must derive one importable module",
                    "a `.py` path whose module segments are valid Python identifiers",
                ),
                "python_launch_interpreter_invalid": (
                    "a Python component must launch through the isolated uv interpreter",
                    "`.venv/bin/python` or `.venv/bin/python3` as argv[0]",
                ),
                "python_launch_argument_invalid": (
                    "Python launch arguments must be bounded portable relative text",
                    "a safe relative Python launch argv",
                ),
                "python_launch_entrypoint_mismatch": (
                    "Python launch argv must invoke the module derived from its declared "
                    "entry_path",
                    "`python -m package.module` matching entry_path",
                ),
                "task_materializer_entrypoint_format": (
                    "the Task Materializer callable is fixed to `materialize` in one module",
                    "one `package.module:materialize` entrypoint",
                ),
                "task_materializer_binding_mismatch": (
                    "the Task Materializer entrypoint module must equal the module derived "
                    "from entry_path",
                    "`module:materialize` with module mechanically derived from entry_path",
                ),
            }
            translated: list[tuple[int, str, SafeValidationIssue]] = []
            for raw, default_issue in zip(raw_errors, fallback.issues, strict=True):
                error_type = str(raw.get("type", "invalid"))
                mapped = catalog.get(error_type)
                if mapped is not None:
                    phase, frontier, code, message = mapped
                    issue_condition, issue_expected = conditions.get(code, (None, None))
                    translated.append(
                        (
                            frontier,
                            phase,
                            SafeValidationIssue(
                                code,
                                default_issue.location,
                                message,
                                violated_condition=issue_condition,
                                expected_category=issue_expected,
                            ),
                        )
                    )
                    continue
                if error_type.startswith(("value_error", "assertion_error")):
                    translated.append(
                        (
                            10,
                            "framework_diagnostic",
                            SafeValidationIssue(
                                "framework_diagnostic_incomplete",
                                default_issue.location,
                                "A framework-authored semantic validator lacks a typed safe "
                                "diagnostic. Do not retry the Agent until the contract is fixed.",
                                retryable=False,
                            ),
                        )
                    )
                    continue
                translated.append((10, "completion_schema", default_issue))
            frontier = min(item[0] for item in translated)
            phase = next(item[1] for item in translated if item[0] == frontier)
            return ValidationDiagnostic(
                owner_component="build",
                validation_phase=phase,
                frontier_ordinal=frontier,
                issues=tuple(item[2] for item in translated if item[0] == frontier),
            )
        if exc.stage == "agent.output":
            return ValidationDiagnostic(
                owner_component="build",
                validation_phase="completion_transport",
                frontier_ordinal=5,
                issues=(
                    SafeValidationIssue(
                        "completion_output_invalid",
                        ("completion",),
                        "Return one complete CandidateCompletion object matching the "
                        "closed schema.",
                    ),
                ),
            )
        if exc.stage == "candidate.validation":
            workspace_error = exc.__cause__
            if isinstance(workspace_error, CandidateWorkspaceError):
                safe_diagnostic = workspace_error.safe_diagnostic
                if safe_diagnostic is not None:
                    return EnvironmentBuilder._workspace_validation_diagnostic(safe_diagnostic)
            message = str(exc)
            groups: tuple[tuple[tuple[str, ...], str, int, str, str], ...] = (
                (
                    (
                        "declared files are missing",
                        "undeclared files",
                        "declarations are not unique",
                        "project is empty",
                        "file-count limit",
                        "executable mode contradicts",
                    ),
                    "manifest_closure",
                    30,
                    "candidate_manifest_closure",
                    "Make file declarations exactly match the final regular files and modes.",
                ),
                (
                    (
                        "credential",
                        "absolute path",
                        "control characters",
                        "USTAR",
                        "binary/NUL",
                        "UTF-8",
                    ),
                    "secret_path_policy",
                    40,
                    "candidate_secret_path_policy",
                    "Remove credentials, host paths, binary content, and non-portable paths.",
                ),
                (
                    (
                        "pyproject",
                        "uv.lock",
                        "dependency",
                        "wheel",
                        "build-system",
                        "requires-python",
                        "uv.toml",
                    ),
                    "dependency_contract",
                    50,
                    "candidate_dependency_contract",
                    (
                        "Inspect candidate/pyproject.toml and candidate/uv.lock together. "
                        "Keep one non-installed virtual root named [project].name with "
                        'source { virtual = "." }; every non-root dependency must be a '
                        "fixed-registry package with locked wheels, and no build/source override "
                        "may bypass the offline policy."
                    ),
                ),
                (
                    (
                        "entry",
                        "runtime",
                        "materializer",
                        "self-check",
                        "public test",
                    ),
                    "component_contract",
                    60,
                    "candidate_component_contract",
                    "Make every declared component entry point exist and match its required role.",
                ),
            )
            for fragments, phase, frontier, code, feedback in groups:
                if any(fragment in message for fragment in fragments):
                    return ValidationDiagnostic(
                        owner_component="build",
                        validation_phase=phase,
                        frontier_ordinal=frontier,
                        issues=(SafeValidationIssue(code, ("candidate",), feedback),),
                    )
            return ValidationDiagnostic(
                owner_component="build",
                validation_phase="workspace_inventory",
                frontier_ordinal=20,
                issues=(
                    SafeValidationIssue(
                        "candidate_workspace_invalid",
                        ("candidate",),
                        "Produce only bounded regular source files in the isolated candidate root.",
                    ),
                ),
            )
        return ValidationDiagnostic(
            owner_component="build",
            validation_phase="builder_execution",
            frontier_ordinal=0,
            issues=(
                SafeValidationIssue(
                    f"builder_{exc.stage.replace('.', '_')}"[:160],
                    ("builder",),
                    "The Builder could not complete this framework-owned phase.",
                    retryable=False,
                ),
            ),
        )

    @staticmethod
    def _workspace_validation_diagnostic(
        diagnostic: CandidateWorkspaceDiagnostic,
    ) -> ValidationDiagnostic:
        """Project a safe manifest difference, never candidate-controlled paths.

        A completed Builder turn can leave a useful workspace even when its
        ``CandidateCompletion.files`` inventory is wrong.  The correction
        recipient needs to know *which inventory relationship* failed and its
        scope, then inspect the workspace it already owns.  Re-emitting raw
        exception paths would make the feedback channel an arbitrary-text
        carrier, so this projection remains intentionally count-only.
        """

        count = diagnostic.count
        plural = "path" if count == 1 else "paths"
        dependency_details: dict[str, tuple[str, str, str]] = {
            "dependency_virtual_root_source_invalid": (
                "candidate_dependency_virtual_root_source_invalid",
                "the package in uv.lock named by [project].name is not the virtual root",
                'exactly one package named [project].name with source { virtual = "." }',
            ),
            "dependency_virtual_root_name_mismatch": (
                "candidate_dependency_virtual_root_name_mismatch",
                "the virtual root package name in uv.lock does not equal [project].name",
                'exactly one { virtual = "." } package named exactly [project].name',
            ),
            "dependency_virtual_root_count": (
                "candidate_dependency_virtual_root_count",
                (
                    "uv.lock contains "
                    f"{count} package entries named [project].name with source "
                    '{ virtual = "." }'
                ),
                "exactly one virtual, non-installed root package named [project].name",
            ),
        }
        dependency = dependency_details.get(diagnostic.code)
        if dependency is not None:
            code, condition, expected = dependency
            return ValidationDiagnostic(
                owner_component="build",
                validation_phase="dependency_contract",
                frontier_ordinal=50,
                issues=(
                    SafeValidationIssue(
                        code,
                        ("candidate", "uv.lock"),
                        (
                            "Edit only candidate/pyproject.toml and candidate/uv.lock as needed: "
                            "keep the virtual root non-installed, make its lock package name "
                            "equal [project].name, and leave every non-root dependency on the "
                            "approved locked-wheel registry path."
                        ),
                        violated_condition=condition,
                        expected_category=expected,
                    ),
                ),
            )
        details: dict[str, tuple[str, str, str]] = {
            "manifest_declared_missing": (
                "candidate_manifest_declared_missing",
                (
                    "CandidateCompletion.files declares "
                    f"{count} {plural} absent from the final candidate/ tree"
                ),
                "a one-for-one declaration of every final regular candidate file",
            ),
            "manifest_undeclared_files": (
                "candidate_manifest_undeclared_files",
                (
                    "the final candidate/ tree contains "
                    f"{count} regular {plural} absent from CandidateCompletion.files"
                ),
                "a one-for-one declaration of every final regular candidate file",
            ),
            "manifest_declaration_duplicate": (
                "candidate_manifest_declaration_duplicate",
                (f"CandidateCompletion.files repeats {count} candidate-relative {plural}"),
                "one declaration for each final regular candidate file",
            ),
            "manifest_empty": (
                "candidate_manifest_empty",
                "a completed CandidateCompletion has no regular file in candidate/",
                "a non-empty final regular candidate file inventory",
            ),
            "manifest_file_limit": (
                "candidate_manifest_file_limit",
                (
                    "candidate/ contains "
                    f"{count} regular files, exceeding the framework file-count limit"
                ),
                "a bounded final regular candidate file inventory",
            ),
            "manifest_executable_mode": (
                "candidate_manifest_executable_mode",
                (
                    "a final candidate file executable bit disagrees with its "
                    "CandidateCompletion declaration"
                ),
                "an executable declaration matching every final regular file mode",
            ),
        }
        mapped = details.get(diagnostic.code)
        if mapped is None:
            return ValidationDiagnostic(
                owner_component="build",
                validation_phase="framework_diagnostic",
                frontier_ordinal=0,
                issues=(
                    SafeValidationIssue(
                        "framework_diagnostic_incomplete",
                        ("candidate", "files"),
                        "Candidate workspace validation emitted an unknown safe diagnostic. "
                        "Do not retry the Agent until the framework feedback is completed.",
                        retryable=False,
                    ),
                ),
            )
        code, condition, expected = mapped
        return ValidationDiagnostic(
            owner_component="build",
            validation_phase="manifest_closure",
            frontier_ordinal=30,
            issues=(
                SafeValidationIssue(
                    code,
                    ("candidate", "files"),
                    (
                        "Inspect the final candidate/ inventory after cleanup, then return one "
                        "complete CandidateCompletion whose files list and executable flags match "
                        "that inventory exactly."
                    ),
                    violated_condition=condition,
                    expected_category=expected,
                ),
            ),
        )

    @staticmethod
    def _backend_terminal_error(exc: BuilderError) -> InvocationError | None:
        """Reconstruct only safe terminal classification, never provider text."""

        if exc.backend_error_code is None:
            return None
        return InvocationError(
            code=exc.backend_error_code,
            message=exc.backend_error_code,
            retryable=exc.backend_retryable,
            details=exc.backend_error_details,
        )

    @staticmethod
    def _diagnostic_terminal_excerpt(
        error: InvocationError | None,
        *,
        profile: ResolvedAgentProfile,
    ) -> str | None:
        """Defensively re-scrub one explicitly opted-in worker diagnostic.

        The Codex worker has already redacted this optional field.  Builder
        repeats the same narrow scrub with its resolved credential values so
        a future backend cannot accidentally turn the local diagnostic path
        into a transcript carrier.
        """

        if error is None:
            return None
        return redacted_terminal_diagnostic_excerpt(
            error.details.get("diagnostic_error_excerpt"),
            redactor=Redactor.from_values(profile.secret_values),
        )

    @staticmethod
    def _safe_backend_issue_code(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._:-" else "_" for character in value
        ).strip("._:-")
        return (safe or "terminal")[:120]

    async def repair(
        self,
        *,
        state: BuilderSessionState,
        findings: Sequence[Finding],
        budget: Budget,
    ) -> BuildBundle:
        """Apply disclosed build Findings in the same SDK thread and workspace."""

        self.artifacts.require_exact_json(
            state.design_ref,
            state.design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self.artifacts.require_exact_json(
            state.implementation_contract_ref,
            state.implementation_contract,
            artifact_types=("build.implementation_contract",),
        )
        self._validate_budget(budget, repair=True)
        if state.repair_count >= self.maximum_repair_attempts:
            raise BuilderError(
                "budget",
                "Builder repair-attempt limit is exhausted",
                state=state,
            )
        if state.invocation_session is None:
            raise BuilderError(
                "repair",
                "same-session repair requires a resumable Engineer session",
                state=state,
            )
        self._validate_repair_session_binding(state)
        self._validate_profile_budget(
            state.profile,
            budget,
            authorized_turns=1,
            physical_turn_token_limit=state.physical_turn_token_limit,
            physical_turn_timeout_seconds=state.physical_turn_timeout_seconds,
        )
        self._verify_framework_inputs(state)
        disclosures = self._repair_disclosures(findings)
        attempt = state.repair_count + 2
        disclosure_path = state.workspace / "inputs" / f"repair-disclosure-{attempt}.json"
        disclosure_bytes = canonical_json_bytes(
            [item.model_dump(mode="json", exclude_none=False) for item in disclosures]
        )
        self._assert_no_secret_values(disclosure_bytes, state.profile.secret_values)
        self._write_immutable(disclosure_path, disclosure_bytes)
        repair_relative = disclosure_path.relative_to(state.workspace).as_posix()
        repair_state = replace(
            state,
            input_hashes=tuple(
                sorted(
                    (
                        *state.input_hashes,
                        (repair_relative, sha256_digest(disclosure_bytes)),
                    )
                )
            ),
            repair_count=state.repair_count + 1,
        )
        completion, session, invocation = await self._invoke_engineer(
            profile=repair_state.profile,
            session=repair_state.invocation_session,
            prompt=self._repair_prompt(attempt, disclosure_path.name),
            lineage_id=repair_state.lineage_id,
            attempt=attempt,
            error_state=repair_state,
        )
        next_state = replace(
            repair_state,
            invocation_session=session,
        )
        return self._validate_and_commit(
            completion=completion,
            state=next_state,
            invocation=invocation,
        )

    async def _invoke_engineer(
        self,
        *,
        profile: ResolvedAgentProfile,
        session: InvocationSession | None,
        prompt: str,
        lineage_id: str,
        attempt: int,
        error_state: BuilderSessionState,
        invocation_id: str | None = None,
        diagnostic_capture_terminal_excerpt: bool = False,
    ) -> tuple[CandidateCompletion, InvocationSession, BuildInvocationSummary]:
        invocation_id = invocation_id or f"build-{hashlib.sha256(os.urandom(32)).hexdigest()[:24]}"
        invocation_started = time.monotonic()
        self._persist_workspace_progress(error_state, status="turn_started")
        heartbeat = asyncio.create_task(
            self._monitor_workspace_progress(error_state),
            name=f"builder-workspace-heartbeat-{attempt}",
        )
        try:
            try:
                metadata: dict[str, JsonValue] = {
                    "role": "environment-engineer",
                    "lineage_id": lineage_id,
                    "attempt": attempt,
                    "purpose": "compile-environment-candidate",
                }
                if diagnostic_capture_terminal_excerpt:
                    # The local test-node harness is the only caller that
                    # opts in. The backend returns a worker-redacted excerpt
                    # which is deliberately kept out of normal feedback.
                    metadata["diagnostic_capture_terminal_excerpt"] = True
                result = await self.backend.invoke(
                    InvocationRequest(
                        invocation_id=invocation_id,
                        prompt=prompt,
                        profile=profile,
                        session=session,
                        metadata=metadata,
                    )
                )
            except Exception as exc:
                raise BuilderError(
                    "agent.backend",
                    f"Engineer backend raised {type(exc).__name__}",
                    state=error_state,
                    invocation=BuildInvocationSummary(
                        invocation_id=invocation_id,
                        status=InvocationStatus.FAILED,
                        duration_ms=max(
                            0,
                            int((time.monotonic() - invocation_started) * 1000),
                        ),
                        usage=None,
                        backend_version=None,
                        total_tokens=0,
                        unknown_token_upper_bounds=(error_state.physical_turn_token_limit,),
                    ),
                ) from exc
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            self._persist_workspace_progress(error_state, status="turn_terminal")
        summary = BuildInvocationSummary(
            invocation_id=result.invocation_id,
            status=result.status,
            duration_ms=result.duration_ms,
            usage=result.usage,
            backend_version=result.backend_version,
            total_tokens=self._invocation_token_total(result.usage),
            unknown_token_upper_bounds=(
                (error_state.physical_turn_token_limit,)
                if result.usage is None or result.usage.turn is None
                else ()
            ),
        )
        continued_state = replace(
            error_state,
            invocation_session=result.session or error_state.invocation_session,
        )
        if not result.succeeded:
            message = self._redact_runtime_paths(
                result.error.message if result.error else result.status.value,
                profile,
            )
            raise BuilderError(
                "agent",
                message,
                state=continued_state,
                invocation=summary,
                backend_error_code=result.error.code if result.error else None,
                backend_retryable=result.error.retryable if result.error else False,
                backend_error_details=safe_terminal_details(result.error),
                diagnostic_terminal_excerpt=(
                    self._diagnostic_terminal_excerpt(result.error, profile=profile)
                    if diagnostic_capture_terminal_excerpt
                    else None
                ),
            )
        if result.session is None:
            raise BuilderError(
                "agent.session",
                "real backend completed without a resumable session",
                state=continued_state,
                invocation=summary,
            )
        try:
            if result.structured_output is None:
                raise ValueError("real backend returned no structured completion")
            normalized_output = normalize_candidate_completion_output(result.structured_output)
            completion = CandidateCompletion.model_validate_json(
                canonical_json_bytes(normalized_output)
            )
        except ValidationError as exc:
            errors = json.dumps(
                exc.errors(
                    include_context=False,
                    include_input=False,
                    include_url=False,
                ),
                ensure_ascii=False,
            )
            raise BuilderError(
                "agent.output",
                f"candidate completion violates the framework schema: {errors}",
                state=continued_state,
                invocation=summary,
            ) from exc
        except ValueError as exc:
            raise BuilderError(
                "agent.output",
                str(exc),
                state=continued_state,
                invocation=summary,
            ) from exc
        if completion.status == "blocked":
            raise BuilderError(
                "agent.blocked",
                self._redact_runtime_paths(
                    completion.blocking_reason or "Engineer reported an unspecified blocker",
                    profile,
                ),
                state=continued_state,
                invocation=summary,
            )
        return completion, result.session, summary

    async def _monitor_workspace_progress(self, state: BuilderSessionState) -> None:
        last_digest: str | None = None
        while True:
            await asyncio.sleep(self.workspace_heartbeat_seconds)
            try:
                progress = await asyncio.to_thread(
                    self._workspace_progress,
                    state,
                    "changed",
                )
                status = "changed" if progress.metadata_digest != last_digest else "steady"
                last_digest = progress.metadata_digest
                if progress.status != status:
                    progress = BuilderWorkspaceProgress.model_validate(
                        {**progress.model_dump(mode="python"), "status": status}
                    )
            except Exception as exc:
                progress = self._unavailable_workspace_progress(state, exc)
            self._put_workspace_progress_best_effort(state, progress)

    def _persist_workspace_progress(
        self,
        state: BuilderSessionState,
        *,
        status: Literal["turn_started", "changed", "steady", "turn_terminal"],
    ) -> None:
        try:
            progress = self._workspace_progress(state, status)
        except Exception as exc:
            progress = self._unavailable_workspace_progress(state, exc)
        self._put_workspace_progress_best_effort(state, progress)

    @staticmethod
    def _workspace_progress(
        state: BuilderSessionState,
        status: Literal["turn_started", "changed", "steady", "turn_terminal"],
    ) -> BuilderWorkspaceProgress:
        root = state.workspace / "candidate"
        entries: list[tuple[str, int, int]] = []
        if root.is_dir():
            for directory, directory_names, file_names in os.walk(root, followlinks=False):
                directory_names[:] = sorted(
                    name for name in directory_names if not (Path(directory) / name).is_symlink()
                )
                for name in sorted(file_names):
                    path = Path(directory) / name
                    if path.is_symlink() or not path.is_file():
                        continue
                    metadata = path.stat()
                    entries.append(
                        (
                            path.relative_to(root).as_posix(),
                            metadata.st_size,
                            metadata.st_mtime_ns,
                        )
                    )
        return BuilderWorkspaceProgress(
            run_id=state.run_id,
            attempt_id=state.attempt_id,
            lineage_id=state.lineage_id,
            observed_at=datetime.now(UTC),
            status=status,
            file_count=len(entries),
            total_bytes=sum(item[1] for item in entries),
            metadata_digest=sha256_digest(canonical_json_bytes(entries)),
        )

    def _put_workspace_progress(
        self,
        state: BuilderSessionState,
        progress: BuilderWorkspaceProgress,
    ) -> ArtifactRef:
        return self.artifacts.put_json(
            artifact_id=self.workspace_progress_artifact_id(
                state.run_id,
                state.attempt_id,
            ),
            artifact_type="build.workspace_progress",
            value=progress,
            dependencies=(state.design_ref, state.implementation_contract_ref),
        )

    @staticmethod
    def workspace_progress_artifact_id(run_id: str, attempt_id: str) -> str:
        """Return the exact run/attempt-scoped heartbeat stream identity."""

        return f"{run_id}:workspace-progress:{attempt_id}"

    def _put_workspace_progress_best_effort(
        self,
        state: BuilderSessionState,
        progress: BuilderWorkspaceProgress,
    ) -> None:
        # High-frequency observability cannot become a second synchronous Gate.
        # A missing heartbeat remains unknown and is diagnosed from the absence
        # of progress artifacts rather than failing otherwise valid codegen.
        with suppress(Exception):
            self._put_workspace_progress(state, progress)

    def _unavailable_workspace_progress(
        self,
        state: BuilderSessionState,
        exc: BaseException,
    ) -> BuilderWorkspaceProgress:
        return BuilderWorkspaceProgress(
            run_id=state.run_id,
            attempt_id=state.attempt_id,
            lineage_id=state.lineage_id,
            observed_at=datetime.now(UTC),
            status="unavailable",
            file_count=0,
            total_bytes=0,
            error_code=self._safe_progress_code(type(exc).__name__),
        )

    @staticmethod
    def _safe_progress_code(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._:-" else "_" for character in value
        ).strip("._:-")
        return (safe or "workspace_progress_unavailable")[:160]

    @staticmethod
    def _invocation_token_total(usage: InvocationUsage | None) -> int:
        if usage is None or usage.turn is None:
            return 0
        return max(0, usage.turn.total_tokens)

    @staticmethod
    def _merge_invocation_summaries(
        summaries: Sequence[BuildInvocationSummary],
    ) -> BuildInvocationSummary:
        if not summaries:
            raise ValueError("Builder invocation summary merge requires at least one turn")
        latest = summaries[-1]
        return BuildInvocationSummary(
            invocation_id=latest.invocation_id,
            status=latest.status,
            duration_ms=sum(item.duration_ms for item in summaries),
            usage=latest.usage,
            backend_version=latest.backend_version,
            turns=sum(item.turns for item in summaries),
            total_tokens=sum(item.total_tokens for item in summaries),
            unknown_token_upper_bounds=tuple(
                bound for item in summaries for bound in item.unknown_token_upper_bounds
            ),
        )

    @staticmethod
    def _precommit_repair_prompt(*, attempt: int, error: str) -> str:
        return (
            f"Builder pre-commit validation failed before candidate revision {attempt}. "
            "Continue in the same workspace and correct the complete candidate in place. "
            "Remove runtime state, caches, virtual environments, and every undeclared file "
            "from candidate/. Make the structured declarations exactly match the final files. "
            "Return the entire corrected CandidateCompletion, not a patch. "
            f"Framework validation error:\n{error}"
        )

    def _validate_and_commit(
        self,
        *,
        completion: CandidateCompletion,
        state: BuilderSessionState,
        invocation: BuildInvocationSummary,
    ) -> BuildBundle:
        try:
            self._verify_framework_inputs(state)
            candidate_root = state.workspace / "candidate"
            self._remove_derived_candidate_ephemera(candidate_root)
            validated = self.validator.validate(
                candidate_root,
                completion,
                secret_values=state.profile.secret_values,
                forbidden_absolute_paths=(
                    state.workspace,
                    state.profile.materialization_root,
                    state.profile.home,
                    state.profile.codex_home,
                ),
                python_requires=state.implementation_contract.python_requires,
            )
            self._verify_framework_inputs(state)
            return self._commit_candidate(
                completion=completion,
                validated=validated,
                state=state,
                invocation=invocation,
            )
        except CandidateWorkspaceError as exc:
            raise BuilderError(
                "candidate.validation",
                str(exc),
                state=state,
                invocation=invocation,
            ) from exc

    @staticmethod
    def _remove_derived_candidate_ephemera(candidate_root: Path) -> None:
        """Remove only deterministic interpreter/test caches after the Agent stops.

        Cache output has no semantic or supply-chain role and is never packaged.  A
        symlink or non-directory using a cache name is deliberately preserved so the
        independent workspace validator can reject it; cleanup never follows links or
        guesses about ordinary source/build directories.
        """

        if candidate_root.is_symlink() or not candidate_root.is_dir():
            return
        for directory, directory_names, file_names in os.walk(
            candidate_root,
            topdown=True,
            followlinks=False,
        ):
            base = Path(directory)
            for name in tuple(directory_names):
                if name not in _DERIVED_CACHE_DIRECTORIES:
                    continue
                directory_names.remove(name)
                target = base / name
                try:
                    observed = target.lstat()
                except OSError:
                    continue
                if stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode):
                    shutil.rmtree(target)
            for name in file_names:
                if not name.endswith(".pyc"):
                    continue
                target = base / name
                try:
                    observed = target.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(observed.st_mode) and not stat.S_ISLNK(observed.st_mode):
                    target.unlink()

    def _commit_candidate(
        self,
        *,
        completion: CandidateCompletion,
        validated: ValidatedCandidateWorkspace,
        state: BuilderSessionState,
        invocation: BuildInvocationSummary,
    ) -> BuildBundle:
        assert completion.runtime is not None
        assert completion.task_materializer is not None
        assert completion.public_self_check is not None
        assert state.invocation_session is not None
        plan_dependencies = (
            () if state.implementation_plan_ref is None else (state.implementation_plan_ref,)
        )
        revision = state.repair_count + 1
        base_id = f"{state.candidate_id}:r{revision}"
        task_schema_ref = self.artifacts.put_json(
            artifact_id=f"{base_id}:task-materialization-schema",
            artifact_type="build.task_materialization_schema",
            value=self._task_materialization_schema(state.design),
            dependencies=(state.design_ref, state.implementation_contract_ref),
        )
        curriculum_ref = self.artifacts.put_json(
            artifact_id=f"{base_id}:curriculum",
            artifact_type="build.curriculum",
            value=state.design.curriculum,
            dependencies=(state.design_ref,),
        )
        public_verifier_ref = self._put_component_file(
            artifact_id=f"{base_id}:public-verifier",
            artifact_type="build.public_verifier",
            file=validated.file(completion.public_self_check.entry_path),
            dependencies=(state.design_ref, state.implementation_contract_ref),
        )
        public_test_refs = tuple(
            self._put_component_file(
                artifact_id=f"{base_id}:public-test:{index}",
                artifact_type="build.public_test",
                file=validated.file(path),
                dependencies=(state.design_ref, state.implementation_contract_ref),
            )
            for index, path in enumerate(completion.public_test_paths)
        )
        snapshot_dependencies = self._unique_refs(
            (
                state.design_ref,
                state.implementation_contract_ref,
                *plan_dependencies,
                *state.parent_workspace_refs,
                *state.prior_snapshot_refs[-1:],
            )
        )
        source_snapshot_ref = self.artifacts.put_blob(
            artifact_id=f"{base_id}:source-snapshot",
            artifact_type="build.source_workspace_snapshot",
            content=validated.deterministic_tar(),
            media_type="application/x-tar",
            dependencies=snapshot_dependencies,
        )
        lock_hash = validated.file("uv.lock").content_hash
        implementation_lineage = ImplementationLineage(
            lineage_id=self._stable_id("implementation-lineage", source_snapshot_ref.revision_id),
            source_snapshot_refs=(source_snapshot_ref,),
            parent_workspace_refs=self._unique_refs(
                (*state.parent_workspace_refs, *state.prior_snapshot_refs[-1:])
            ),
            builder_profile_hash=f"sha256:{state.profile.profile_hash}",
            backend=state.profile.backend,
            model=state.profile.model,
            session_id=self._stable_id("agent-session", state.invocation_session.thread_id),
            dependency_lock_hash=lock_hash,
            implementation_contract_ref=state.implementation_contract_ref,
        )
        implementation_lineage_ref = self.artifacts.put_json(
            artifact_id=f"{base_id}:implementation-lineage",
            artifact_type="build.implementation_lineage",
            value=implementation_lineage,
            dependencies=(
                source_snapshot_ref,
                state.implementation_contract_ref,
                *plan_dependencies,
                *implementation_lineage.parent_workspace_refs,
            ),
        )
        runtime = RuntimeLaunch(
            argv=completion.runtime.argv,
            workdir=completion.runtime.workdir,
            startup_timeout_seconds=completion.runtime.startup_timeout_seconds,
            request_timeout_seconds=completion.runtime.request_timeout_seconds,
            shutdown_timeout_seconds=completion.runtime.shutdown_timeout_seconds,
        )
        task_materializer = TaskMaterializerDescriptor(
            entrypoint=completion.task_materializer.entrypoint,
            entry_path=completion.task_materializer.entry_path,
            protocol=completion.task_materializer.protocol,
            output_schema_ref=task_schema_ref,
            curriculum_ref=curriculum_ref,
        )
        public_self_check = PublicSelfCheckDescriptor(
            argv=completion.public_self_check.argv,
            entry_path=completion.public_self_check.entry_path,
        )
        candidate_manifest = CandidateManifest(
            candidate_id=state.candidate_id,
            design_ref=state.design_ref,
            candidate_source_tree_digest=validated.candidate_source_tree_digest,
            runtime=runtime,
            task_materializer=task_materializer,
            public_self_check=public_self_check,
            public_verifier_ref=public_verifier_ref,
            public_test_refs=public_test_refs,
            files=validated.package_files,
            implementation_lineage_ref=implementation_lineage_ref,
            known_limits=state.design.unresolved_questions,
        )
        candidate_manifest_ref = self.artifacts.put_json(
            artifact_id=f"{base_id}:candidate-manifest",
            artifact_type="build.candidate_manifest",
            value=candidate_manifest,
            dependencies=(
                state.design_ref,
                source_snapshot_ref,
                implementation_lineage_ref,
                *plan_dependencies,
                public_verifier_ref,
                task_schema_ref,
                curriculum_ref,
                *public_test_refs,
            ),
        )
        build_record = BuildRecord(
            build_id=self._stable_id("build", source_snapshot_ref.revision_id),
            candidate_id=state.candidate_id,
            candidate_revision=revision,
            implementation_contract_ref=state.implementation_contract_ref,
            source_snapshot_ref=source_snapshot_ref,
            completion_hash=completion.content_digest(),
            files=validated.package_files,
            validations=_BUILD_VALIDATIONS,
            agent_turn_number=revision,
            public_self_check_argv=completion.public_self_check.argv,
        )
        build_artifact_ref = self.artifacts.put_json(
            artifact_id=f"{base_id}:build-record",
            artifact_type="build.record",
            value=build_record,
            dependencies=(source_snapshot_ref, candidate_manifest_ref, *plan_dependencies),
        )
        candidate = EnvironmentCandidate(
            candidate_id=state.candidate_id,
            revision=revision,
            design_ref=state.design_ref,
            implementation_contract_ref=state.implementation_contract_ref,
            source_workspace_snapshot_ref=source_snapshot_ref,
            build_artifact_ref=build_artifact_ref,
            runtime=runtime,
            task_materializer=task_materializer,
            public_self_check=public_self_check,
            public_verifier_ref=public_verifier_ref,
            candidate_manifest_ref=candidate_manifest_ref,
            implementation_lineage_ref=implementation_lineage_ref,
        )
        candidate_ref = self.artifacts.put_json(
            artifact_id=f"{state.candidate_id}:candidate",
            artifact_type="build.environment_candidate",
            value=candidate,
            dependencies=(
                state.design_ref,
                state.implementation_contract_ref,
                source_snapshot_ref,
                build_artifact_ref,
                candidate_manifest_ref,
                implementation_lineage_ref,
                *plan_dependencies,
            ),
        )
        committed_state = replace(
            state,
            prior_snapshot_refs=(*state.prior_snapshot_refs, source_snapshot_ref),
        )
        return BuildBundle(
            implementation_contract=state.implementation_contract,
            implementation_contract_ref=state.implementation_contract_ref,
            source_snapshot_ref=source_snapshot_ref,
            implementation_lineage=implementation_lineage,
            implementation_lineage_ref=implementation_lineage_ref,
            candidate_manifest=candidate_manifest,
            candidate_manifest_ref=candidate_manifest_ref,
            build_record=build_record,
            build_artifact_ref=build_artifact_ref,
            candidate=candidate,
            candidate_ref=candidate_ref,
            project_root=state.workspace / "candidate",
            session=state.invocation_session,
            state=committed_state,
            invocation=invocation,
        )

    def materialize_implementation_inputs(
        self,
        *,
        workspace: Path,
        design: EnvironmentDesign,
        contract: ImplementationContract,
        implementation_plan: ImplementationPlan | None = None,
    ) -> tuple[tuple[str, str], ...]:
        """Stage only the frozen bytes an Engineer needs for one implementation.

        The full ``EnvironmentDesign`` is a control-plane container.  It
        duplicates WorldSpec and adds release/evidence/metadata that the
        Builder neither owns nor should inspect.  The implementation boundary
        instead receives the executable world, the curriculum it materializes,
        the framework-owned ABI contract, and the output schema.  An already
        committed plan is optional, explicitly advisory text.
        """

        values = {
            "inputs/world-spec.json": design.world_spec.stable_json_bytes(),
            "inputs/curriculum.json": design.curriculum.stable_json_bytes(),
            "inputs/implementation-contract.json": contract.stable_json_bytes(),
            "inputs/task-materializer-output.schema.json": canonical_json_bytes(
                self._task_materialization_schema(design)
            ),
        }
        if implementation_plan is not None:
            values["inputs/implementation-plan.md"] = (
                implementation_plan.implementation_strategy.encode("utf-8")
            )
        hashes: list[tuple[str, str]] = []
        for relative, content in values.items():
            self._write_immutable(workspace / relative, content)
            hashes.append((relative, sha256_digest(content)))
        return tuple(sorted(hashes))

    @staticmethod
    def _write_immutable(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
                raise BuilderError(
                    "workspace.inputs",
                    f"framework input path was replaced or changed: {path.name}",
                )
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o400)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _verify_framework_inputs(state: BuilderSessionState) -> None:
        for relative, expected_hash in state.input_hashes:
            path = state.workspace / relative
            if path.is_symlink() or not path.is_file():
                raise BuilderError(
                    "workspace.inputs",
                    f"framework input disappeared or became unsafe: {relative}",
                    state=state,
                )
            if sha256_digest(path.read_bytes()) != expected_hash:
                raise BuilderError(
                    "workspace.inputs",
                    f"Engineer modified immutable framework input: {relative}",
                    state=state,
                )

    @staticmethod
    def _assert_no_secret_values(content: bytes, secret_values: tuple[str, ...]) -> None:
        for value in secret_values:
            encoded = value.encode("utf-8")
            if len(encoded) >= 8 and encoded in content:
                raise BuilderError(
                    "repair.disclosure",
                    "repair disclosure contains a materialized credential value",
                )

    @staticmethod
    def _repair_disclosures(findings: Sequence[Finding]) -> tuple[RepairDisclosure, ...]:
        if not findings:
            raise BuilderError("repair", "repair requires at least one disclosed Finding")
        disclosures: list[RepairDisclosure] = []
        for index, finding in enumerate(findings, start=1):
            if finding.owner != "build":
                raise BuilderError(
                    "repair",
                    f"Builder cannot repair a Finding owned by {finding.owner}",
                )
            disclosures.append(
                RepairDisclosure(
                    disclosure_id=f"repair-item:{index}",
                    category=(
                        "implementation_behavior"
                        if finding.disclosure == "sealed_summary"
                        else finding.category
                    ),
                    severity=finding.severity,
                    disclosure=finding.disclosure,
                    summary=finding.summary,
                    suggested_repair=(
                        None if finding.disclosure == "sealed_summary" else finding.suggested_repair
                    ),
                )
            )
        return tuple(disclosures)

    @staticmethod
    def _validate_budget(budget: Budget, *, repair: bool) -> None:
        if budget.agent_turns < 1:
            raise BuilderError("budget", "Builder requires at least one real Agent turn")
        if budget.build_seconds <= 0 or budget.wall_seconds <= 0:
            raise BuilderError("budget", "Builder requires positive build_seconds and wall_seconds")
        if repair and budget.repair_attempts < 1:
            raise BuilderError("budget", "repair requires a positive repair_attempts budget")
        if repair and budget.agent_turns != 1:
            raise BuilderError("budget", "repair authorizes exactly one real Agent turn")

    @staticmethod
    def _validate_repair_session_binding(state: BuilderSessionState) -> None:
        session = state.invocation_session
        if session is None:
            raise BuilderError("repair", "same-session repair requires a resumable session")
        profile = state.profile
        if (
            session.lineage_id != profile.lineage_id
            or session.workspace.resolve() != profile.workspace.resolve()
            or session.profile_hash != profile.profile_hash
            or session.codex_config_sha256 != profile.codex_config_sha256
        ):
            raise BuilderError(
                "repair",
                "resumable session identity differs from its immutable Engineer profile",
                state=state,
            )

    def repair_turn_requirements(self, state: BuilderSessionState) -> tuple[int, float]:
        """Return the physical token/time envelope for one same-session turn."""

        self._validate_repair_session_binding(state)
        return state.physical_turn_token_limit, state.physical_turn_timeout_seconds

    def _initial_turn_envelope(self, budget: Budget, *, turn_limit: int) -> tuple[int, float]:
        """Split one multi-turn Builder lease into immutable per-turn SDK limits."""

        if turn_limit <= 0:
            raise BuilderError("budget", "Builder turn limit must be positive")
        per_turn_token_limit = min(
            self.turn_token_limit,
            budget.llm_tokens // turn_limit,
        )
        default_limits = InvocationLimits()
        supervisor_overhead = (
            default_limits.supervisor_wall_ceiling_seconds - default_limits.timeout_seconds
        )
        per_turn_wall_ceiling = min(
            self.turn_timeout_seconds + supervisor_overhead,
            budget.build_seconds / turn_limit,
            budget.wall_seconds / turn_limit,
        )
        per_turn_timeout_seconds = per_turn_wall_ceiling - supervisor_overhead
        if per_turn_token_limit <= 0 or per_turn_timeout_seconds <= 0:
            raise BuilderError(
                "budget",
                "Builder cannot derive one positive per-turn token/time envelope",
            )
        return per_turn_token_limit, per_turn_timeout_seconds

    @staticmethod
    def _logical_session_envelope(
        *,
        session_token_limit: int | None,
        session_wall_seconds: float | None,
        physical_turn_token_limit: int,
        physical_turn_timeout_seconds: float,
    ) -> tuple[int, float]:
        """Validate one optional logical session envelope above a physical turn.

        The resolved profile binds the logical rollout budget and the physical
        lifecycle timeout.  Scheduler leases use the same physical bounds,
        while the WorkDefinition retains the larger logical session envelope.
        """

        if (session_token_limit is None) != (session_wall_seconds is None):
            raise BuilderError(
                "budget",
                "Builder logical session token and wall limits must be declared together",
            )
        if session_token_limit is None:
            return physical_turn_token_limit, physical_turn_timeout_seconds
        if (
            session_token_limit < physical_turn_token_limit
            or session_wall_seconds is None
            or session_wall_seconds < physical_turn_timeout_seconds
        ):
            raise BuilderError(
                "budget",
                "Builder logical session envelope is smaller than one physical turn",
            )
        return session_token_limit, session_wall_seconds

    @staticmethod
    def _validate_profile_budget(
        profile: ResolvedAgentProfile,
        budget: Budget,
        *,
        authorized_turns: int,
        physical_turn_token_limit: int,
        physical_turn_timeout_seconds: float,
    ) -> None:
        if authorized_turns <= 0:
            raise BuilderError("budget", "authorized Builder turns must be positive")
        if profile.rollout_token_limit is None:
            raise BuilderError("budget", "resolved Engineer profile has no hard token limit")
        if profile.rollout_token_limit < physical_turn_token_limit:
            raise BuilderError(
                "budget",
                "resolved Engineer rollout limit is smaller than one physical Builder turn",
            )
        if profile.limits.timeout_seconds < physical_turn_timeout_seconds:
            raise BuilderError(
                "budget",
                "resolved Engineer lifecycle timeout is smaller than one physical Builder turn",
            )
        if physical_turn_token_limit * authorized_turns > budget.llm_tokens:
            raise BuilderError(
                "budget",
                "resolved Engineer physical token envelope exceeds the Builder budget",
            )
        timeout_ceiling = min(budget.build_seconds, budget.wall_seconds)
        if physical_turn_timeout_seconds * authorized_turns > timeout_ceiling:
            raise BuilderError(
                "budget",
                "resolved Engineer physical timeout exceeds the total build/wall budget",
            )

    def _put_component_file(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        file: ValidatedCandidateFile,
        dependencies: Sequence[ArtifactRef],
    ) -> ArtifactRef:
        return self.artifacts.put_blob(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content=file.data,
            media_type="text/x-python;charset=utf-8",
            dependencies=dependencies,
        )

    @staticmethod
    def _task_materialization_schema(design: EnvironmentDesign) -> dict[str, JsonValue]:
        return compile_task_materializer_output_schema(design.curriculum)

    @staticmethod
    def _runtime_wire_contract() -> RuntimeWireContract:
        return RuntimeWireContract(
            operations=(
                RuntimeOperationContract(
                    operation="handshake",
                    request_payload={},
                    result_requirements=(
                        "Return exactly runtime_id, operations, tools, and optional metadata.",
                        "operations contains handshake/reset/invoke/snapshot/close exactly once.",
                        (
                            "Each tools entry contains exactly tool_id, namespace, name, "
                            "input_schema, output_schema, observation_schema, and optional "
                            "description."
                        ),
                    ),
                ),
                RuntimeOperationContract(
                    operation="reset",
                    request_payload={
                        "seed": "integer-or-string",
                        "actor": "framework-selected-actor-id",
                        "config": "object",
                    },
                    result_requirements=(
                        "Create a deterministic fresh episode for the seed, actor, and config.",
                        (
                            "Bind actor for the whole episode; invoke never accepts an actor. "
                            "Return only ActorBoundary.visibility fields in observation."
                        ),
                        (
                            "Return exactly observation, sha256 state_digest, terminated, and "
                            "an empty info object."
                        ),
                        "Do not accept private goal, expected value, task id, or case metadata.",
                    ),
                ),
                RuntimeOperationContract(
                    operation="invoke",
                    request_payload={
                        "tool": "string",
                        "args": "object",
                        "idempotency_key": "non-empty-string",
                    },
                    result_requirements=(
                        "Execute the WorldSpec transition in program code.",
                        (
                            "Return exactly tool_result, observation, events, sha256 "
                            "state_digest, reward, terminated, truncated, and info."
                        ),
                        (
                            "Return only ObservationSemantics.visible_fields_by_actor for the "
                            "episode actor; events and info are empty. Error details are empty."
                        ),
                        (
                            "Reject disallowed actors or false permission conditions with "
                            "permission_denied, PermissionRule.denied_observation, no state "
                            "change, retryable=false, and no alternative error."
                        ),
                        (
                            "Both successful and failed invoke responses include that exact result "
                            "envelope; failed invokes additionally include the ABI error object."
                        ),
                        (
                            "Treat reward and terminated as diagnostic-only Runtime fields; the "
                            "framework trusted evaluator recomputes authoritative task reward and "
                            "termination from evaluator_goal plus the WorldSpec Rule IR."
                        ),
                    ),
                ),
                RuntimeOperationContract(
                    operation="snapshot",
                    request_payload={},
                    result_requirements=("Return exactly observation and sha256 state_digest.",),
                ),
                RuntimeOperationContract(
                    operation="close",
                    request_payload={},
                    result_requirements=("Close resources and return an empty JSON object.",),
                ),
            ),
            forbidden_runtime_key_names=_FORBIDDEN_RUNTIME_KEYS,
        )

    @staticmethod
    def _initial_prompt(
        design: EnvironmentDesign,
        *,
        has_implementation_plan: bool,
    ) -> str:
        plan_instruction = (
            "Also read `inputs/implementation-plan.md`. It is advisory implementation guidance "
            "only: the frozen JSON inputs above remain authoritative."
            if has_implementation_plan
            else (
                "No implementation plan is staged for this direct build; derive the implementation "
                "order from the frozen JSON inputs."
            )
        )
        return f"""You are the isolated Environment Engineer for the Agent World Foundry.

Project purpose: turn a human need into a real executable programmatic environment whose state
transitions are owned by code and can later be independently evaluated or used for Agent training.
Your Builder role is narrower: compile the frozen EnvironmentDesign/WorldSpec into a candidate.
Do not change semantics, decide release, or search for sealed/private evaluation material.

Read these immutable framework inputs before editing:
- inputs/world-spec.json
- inputs/curriculum.json
- inputs/implementation-contract.json
- inputs/task-materializer-output.schema.json

{plan_instruction}

These inputs exist only while generating. The restored candidate must install, import, start,
reset, invoke, self-check, and run public tests when only the `candidate/` project tree exists.
Compile required public schemas/constants into declared candidate source or package data. Runtime,
materializer, self-check, and tests must never read `../inputs`, the generation workspace, Codex
state, or any undeclared external file.

Create the complete project only under `candidate/`. It must be a real Python 3.12 uv project with
`candidate/pyproject.toml`, a resolved `candidate/uv.lock`, and a non-empty `candidate/LICENSE`
declared with file role `license`. The `[project]` table must contain an explicit non-unknown
license expression or a license-file declaration bound to that file. Implement stdio JSONL
agent-world.runtime.v2 exactly as the implementation contract states. Runtime state must use the
writable `AGENT_WORLD_STATE_DIR`; the installed source tree is read-only under Judge isolation.
The root project is a virtual, non-installed uv root executed directly from that read-only source
tree: set `[tool.uv] package = false`, do not declare a build-system, and ensure `uv.lock` records
exactly one root package named exactly `[project].name` with `{{ virtual = "." }}`. Dependencies
may only be ordinary named requirements resolved to hash-pinned wheels from the fixed HTTPS PyPI
registry. Do not use editable/workspace, path, Git,
direct URL, custom index, find-links, build-setting, source-build, or sdist-only install paths.
Judge installs dependencies with network disabled and no source builds from a framework-prefilled
read-only uv cache. If an approved wheel is unavailable, return a real blocker; never weaken the
supply-chain contract.

Implement unseen seeded episodes, every WorldSpec tool and transition, the Task Materializer v3
callable, a runnable public self-check, and real standalone public-test scripts. Declare the
self-check as a `.venv/bin/python -m package.module` command. Every declared public test must run
directly as `.venv/bin/python relative/test_path.py` without network or a writable source tree; it
may diagnose the candidate but cannot claim release authority. Use uv to lock and run the tests.
Remove `.venv`, caches, build output, bytecode, links, and undeclared files before completion.

The Task Materializer contract is fixed: expose exactly
`materialize(seed: int, task_type: str, actor: str, difficulty: object) ->
task-materialization-v3` at a `package.module:materialize` entrypoint. It must be deterministic for
identical inputs, support unseen uint64 seeds, accept every declared task type and
framework-selected actor, echo seed/task_type/actor/difficulty exactly, and return only these
closed fields:
`schema_version`, `task_schema_version`, `seed`, `task_type`, `actor`, `difficulty`, `public_goal`,
and `initial_config`. Both objects must satisfy the task-specific schemas supplied by the framework.
Every CandidateCompletion path is relative to the physical project root `candidate/`; do not
repeat that outer workspace directory in declarations. For example, the physical file
`candidate/candidate/materializer.py` is declared as `candidate/materializer.py`, and the physical
file `candidate/LICENSE` is declared as `LICENSE`. The entrypoint module must exactly match its
declared entry_path: remove the `.py` suffix, replace `/` with `.`, ignore one leading `src/`, and
ignore a trailing `__main__`. Thus declared `candidate/materializer.py` binds to
`candidate.materializer:materialize`; never put a path or filename before the colon.
Do not confuse a source path with its launch module: `entry_path` must always be a
candidate-relative `.py` path, whereas runtime and self-check `argv` must use the derived
dot-separated module after `-m`. For example, `candidate/runtime.py` pairs with
`[.venv/bin/python, -m, candidate.runtime]`. Before returning, inspect the final regular-file
inventory and declare every final path exactly once with its fixed role.
If the materializer file is directly at the project root as `candidate/task_materializer.py`,
declare `entry_path=task_materializer.py` and `entrypoint=task_materializer:materialize`; only
use a `candidate.` module prefix when `candidate/` is an actual package directory inside the
project root.
Never author `public_instruction`, evaluator goal, answer, expected output, solution trace, or
evaluation witness. Framework code renders the instruction from the frozen objective and public
goal, projects the evaluator goal through typed identity bindings, and independently proves task
reachability. For every difficulty dimension, changing only that dimension at the same seed and
actor must change `public_goal` or `initial_config`, not merely echo another label.

Runtime reset receives only `seed`, `actor`, and `initial_config`, and binds actor for the episode;
invoke has no actor field and must not infer one from tool arguments. Runtime cannot truthfully
compute evaluator-owned task reward or success, so its reward/termination fields are diagnostic
only; do not smuggle evaluator goals or solver traces into Runtime state or inputs.
Project reset
observation to ActorBoundary.visibility and each invoke observation to
ObservationSemantics.visible_fields_by_actor for the bound actor. Snapshot remains full-state and
Judge-only. Keep reset/invoke info, invoke events, and error details empty because those channels
have no typed WorldSpec semantics.

Never implement fixed task replay, fixture registries, environment-id branches, generated verify()
release authority, mocks/fakes/stubs, or template fallback. Runtime inputs must never contain task
ids, case labels, expected values, oracle data, verifier IR, sealed data, or release metadata.
Do not write an envpkg, candidate, Judge, or release manifest: framework code creates those after
it independently inspects every declared project file. Do not generate or claim an SBOM,
supply-chain verdict, license-completeness verdict, Judge result, or Gate result; those are derived
from the physical lock, clean installation, metadata, and isolated executions by framework code.

Return only the requested CandidateCompletion JSON. A completed declaration must explicitly echo
`root_project_mode=virtual-read-only-source-tree` and
`dependency_install_mode=offline-wheel-only`, plus relative paths, file roles, executable bits,
entrypoints and launch argv. It must not invent hashes, ArtifactRefs, Judge results, or release
claims. If a real dependency/tool/permission prevents completion, return status=blocked with the
honest blocker and no claimed files.

Frozen design id: {design.design_id}, revision: {design.revision}.
"""

    @staticmethod
    def _output_limit_continuation_prompt() -> str:
        """Resume one Provider-truncated turn without exposing terminal prose.

        This is intentionally operational rather than a semantic repair brief:
        no CandidateCompletion was returned for framework validation, so there
        is no field-level rejection to feed back.  The same thread and
        workspace already contain the implementation work from the prior
        physical turn.
        """

        return """Continue the existing Environment Engineer task in the same workspace.

The previous physical turn ended before it returned a complete structured result. Its workspace
changes remain available. Inspect `candidate/` and the immutable `inputs/` files, continue the
remaining implementation and validation work, and preserve every correct file already present.
Do not restart from a template, do not weaken the frozen contracts, and do not describe the
interruption. When the candidate is complete, return the full requested CandidateCompletion JSON
only; it must declare the final complete workspace rather than a patch or partial file list."""

    @staticmethod
    def _repair_prompt(attempt: int, disclosure_filename: str) -> str:
        return f"""Continue the same Environment Engineer thread and modify the existing
`candidate/` project in the same workspace.

Project purpose remains: produce a real programmatic Agent environment with code-owned state
transitions for later independent evaluation/training. Builder repair only fixes the implementation
against the frozen design; it must not weaken WorldSpec, infer hidden cases, or decide release.

Read `inputs/{disclosure_filename}`. It is the complete authorized disclosure for repair attempt
{attempt}. Do not search for evidence refs, expected outputs, evaluator goals, sealed cases, or
Judge internals. Framework inputs are build-time only: the candidate must run when restored alone,
and no candidate component or test may read `../inputs` or another workspace file. Treat existing
candidate behavior and public-test assertions unrelated to the disclosed Finding as regression
obligations: do not delete, relax, invert, or replace them merely to make the current repair pass.
Add or strengthen a focused regression test for the root cause, inspect the final diff for
unrelated changes, rerun real uv/public checks from an isolated candidate-only copy, clean build
debris, and return only the requested CandidateCompletion relative-path/launch declaration. If a
pre-existing assertion truly conflicts with the frozen design, report the blocker instead of
silently weakening it. If blocked, report it honestly.
"""

    @staticmethod
    def _scheduler_repair_prompt(attempt: int, disclosure_filename: str) -> str:
        """Render one data-only correction turn authorized by the Work Scheduler."""

        return f"""Continue the same Environment Engineer thread and modify the existing
`candidate/` project in the same workspace.

This is one focused correction of a candidate that already completed an Agent turn but was
rejected by deterministic framework validation. Read only
`inputs/{disclosure_filename}` for the safe rejected conditions. It contains no hidden evaluator
data, no release decision, and no instruction to change the frozen design. Preserve working files
and unrelated public-test behavior.

Before returning, remove only derived debris, inspect the final regular-file inventory under
`candidate/`, and reconcile it with the full CandidateCompletion you return: every final regular
file is declared exactly once with the correct role and executable flag, and nothing absent from
the final tree remains declared. If the correction touches implementation behavior, strengthen a
focused public regression without weakening unrelated assertions. Do not read or copy `inputs/`
into the candidate, do not change WorldSpec/Curriculum semantics, and do not claim Judge, Gate, or
release results.

Return one complete corrected CandidateCompletion JSON only, never a patch or an explanation.
This is correction attempt {attempt}."""

    @staticmethod
    def _unique_refs(refs: Sequence[ArtifactRef]) -> tuple[ArtifactRef, ...]:
        unique = {item.revision_id: item for item in refs}
        return tuple(sorted(unique.values(), key=lambda item: (item.artifact_id, item.revision_id)))

    @staticmethod
    def _redact_runtime_paths(message: str, profile: ResolvedAgentProfile) -> str:
        redacted = message
        replacements = (
            (profile.workspace, "<engineer-workspace>"),
            (profile.codex_home, "<isolated-codex-home>"),
            (profile.home, "<isolated-home>"),
            (profile.materialization_root, "<agent-runtime>"),
        )
        for path, label in replacements:
            redacted = redacted.replace(str(path), label)
        return redacted

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
        return f"{prefix}:{digest}"


__all__ = [
    "AgentProfileProvider",
    "BuildBundle",
    "BuildInvocationSummary",
    "BuilderError",
    "BuilderSessionState",
    "EnvironmentBuilder",
]
