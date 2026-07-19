"""Executable policy for bounded feedback and exact repair ownership.

The catalog is static framework policy.  A :class:`FeedbackResult` is the
runtime fact produced by one validator or execution probe.  Keeping those two
objects separate prevents a validator from smuggling workflow jumps, concrete
Artifact revisions, or release authority into its declaration.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import (
    ArtifactRef,
    BudgetUsage,
    ContentHash,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

type FeedbackExecutor = Literal["code", "real_execution", "llm_advisory", "hybrid"]
type FeedbackCostClass = Literal["L0", "L1", "L2", "L3"]
type FeedbackEffect = Literal[
    "evidence_only",
    "reject_revision",
    "block_compile",
    "block_integration",
    "block_release",
    "quarantine",
]
type FeedbackTiming = Literal[
    "precommit",
    "postcommit",
    "post_build",
    "pre_release",
    "post_release",
]
type FeedbackStatus = Literal["passed", "failed", "inconclusive", "error", "not_run"]
type FeedbackComponent = Literal[
    "research",
    "design",
    "verifier",
    "build",
    "integration",
    "judge",
    "release",
    "controller",
    "registry",
]


class FeedbackContract(V2Contract):
    """Static framework policy for one production feedback boundary."""

    contract_id: Identifier
    claim_id: Identifier
    claim: NonEmptyStr
    timing: FeedbackTiming
    timing_reason: NonEmptyStr
    executor: FeedbackExecutor
    cost_class: FeedbackCostClass
    producer_component: FeedbackComponent
    repair_owner_component: FeedbackComponent | None
    repair_slot: Identifier | None
    maximum_attempts: Annotated[int, Field(ge=0, le=2)]
    maximum_automatic_backjump: Annotated[int, Field(ge=0, le=1)]
    effect: FeedbackEffect

    @model_validator(mode="after")
    def validate_authority(self) -> FeedbackContract:
        if self.executor == "code" and self.cost_class not in {"L0", "L1"}:
            raise ValueError("code feedback must use deterministic cost class L0/L1")
        if self.executor == "real_execution" and self.cost_class not in {"L1", "L3"}:
            raise ValueError("real execution feedback must use cost class L1/L3")
        if self.executor in {"llm_advisory", "hybrid"} and self.cost_class not in {"L2", "L3"}:
            raise ValueError("Agent feedback must use explicit cost class L2/L3")
        if self.maximum_automatic_backjump and self.maximum_attempts == 0:
            raise ValueError("feedback without repair attempts cannot authorize a backjump")
        if self.timing == "precommit" and self.maximum_automatic_backjump:
            raise ValueError("precommit feedback repairs its current transaction, not a backjump")
        repairable = self.repair_owner_component is not None
        if repairable != (self.repair_slot is not None):
            raise ValueError("repair owner and repair slot must either both exist or both be null")
        if not repairable and (self.maximum_attempts or self.maximum_automatic_backjump):
            raise ValueError("observation-only feedback cannot authorize repair")
        return self


class RepairTargetRef(V2Contract):
    """Exact semantic/workspace slot repaired inside one top-level component.

    ``immutable_input_refs`` define the transaction identity.  Rejected raw
    model output is never persisted; ``attempt_commitment`` can bind it without
    leaking a prompt, response, credential, or sealed value.
    """

    target_id: Identifier
    component: FeedbackComponent
    artifact_slot: Identifier
    lineage_id: Identifier
    batch_id: Identifier | None = None
    immutable_input_refs: tuple[ArtifactRef, ...] = ()
    committed_subject_ref: ArtifactRef | None = None
    allowed_mutation_paths: tuple[str, ...] = ()
    attempt_commitment: ContentHash | None = None

    @model_validator(mode="after")
    def validate_target(self) -> RepairTargetRef:
        if len(set(self.immutable_input_refs)) != len(self.immutable_input_refs):
            raise ValueError("repair target immutable inputs must be unique")
        if len(set(self.allowed_mutation_paths)) != len(self.allowed_mutation_paths):
            raise ValueError("repair target mutation paths must be unique")
        return self

    @property
    def target_key(self) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "component": self.component,
                    "artifact_slot": self.artifact_slot,
                    "lineage_id": self.lineage_id,
                    "batch_id": self.batch_id,
                    "immutable_input_revisions": [
                        item.revision_id for item in self.immutable_input_refs
                    ],
                }
            )
        )


class FeedbackResult(V2Contract):
    """One dynamic feedback fact with no routing or release authority."""

    result_id: Identifier
    contract_id: Identifier
    claim_id: Identifier
    target: RepairTargetRef | None = None
    status: FeedbackStatus
    subject_ref: ArtifactRef | None = None
    evidence_refs: tuple[ArtifactRef, ...] = ()
    diagnostic_ref: ArtifactRef | None = None
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    usage_unknown_dimensions: tuple[Identifier, ...] = ()
    evaluated_at: AwareDatetime
    summary: NonEmptyStr

    @model_validator(mode="after")
    def validate_result(self) -> FeedbackResult:
        if len(set(self.usage_unknown_dimensions)) != len(self.usage_unknown_dimensions):
            raise ValueError("feedback usage unknown dimensions must be unique")
        if self.status in {"passed", "failed", "inconclusive", "error"} and not (
            self.evidence_refs or self.diagnostic_ref
        ):
            raise ValueError("evaluated FeedbackResult requires evidence or a diagnostic")
        if self.status == "passed" and self.subject_ref is None:
            raise ValueError("passed FeedbackResult must bind the exact validated subject")
        return self


class FeedbackCatalog:
    """Closed process-local catalog; duplicate or unknown policy fails closed."""

    def __init__(self, contracts: tuple[FeedbackContract, ...]) -> None:
        by_id = {item.contract_id: item for item in contracts}
        if len(by_id) != len(contracts):
            raise ValueError("FeedbackCatalog contains duplicate contract ids")
        self._contracts = by_id

    def require(self, contract_id: str) -> FeedbackContract:
        try:
            return self._contracts[contract_id]
        except KeyError as exc:
            raise ValueError(f"unregistered production feedback contract: {contract_id}") from exc

    def require_for_target(
        self,
        contract_id: str,
        target: RepairTargetRef,
    ) -> FeedbackContract:
        contract = self.require(contract_id)
        if contract.repair_owner_component is None:
            raise ValueError("observation-only feedback contract has no repair target")
        if contract.repair_owner_component != target.component:
            raise ValueError("feedback repair owner does not match repair target component")
        if contract.repair_slot != target.artifact_slot:
            raise ValueError("feedback contract slot does not match repair target slot")
        return contract

    def validate_result(self, result: FeedbackResult) -> FeedbackContract:
        contract = self.require(result.contract_id)
        if result.claim_id != contract.claim_id:
            raise ValueError("feedback result claim does not match its registered contract")
        if result.target is None:
            if contract.repair_owner_component is not None:
                raise ValueError("repairable feedback must bind an exact target")
        else:
            self.require_for_target(contract.contract_id, result.target)
            if result.status == "passed":
                if result.target.committed_subject_ref is None:
                    raise ValueError(
                        "passed repairable feedback requires a committed repair target"
                    )
                if result.subject_ref != result.target.committed_subject_ref:
                    raise ValueError("feedback subject does not match committed repair target")
        return contract

    @property
    def contracts(self) -> tuple[FeedbackContract, ...]:
        return tuple(self._contracts.values())


def _contract(
    contract_id: str,
    claim_id: str,
    claim_text: str,
    timing: FeedbackTiming,
    timing_reason: str,
    executor: FeedbackExecutor,
    cost: FeedbackCostClass,
    producer: FeedbackComponent,
    repair_slot: str | None,
    attempts: int,
    backjump: int,
    effect: FeedbackEffect,
    repair_owner: FeedbackComponent | None = None,
) -> FeedbackContract:
    return FeedbackContract(
        contract_id=contract_id,
        claim_id=claim_id,
        claim=claim_text,
        timing=timing,
        timing_reason=timing_reason,
        executor=executor,
        cost_class=cost,
        producer_component=producer,
        repair_owner_component=(
            (repair_owner or producer) if repair_slot is not None else None
        ),
        repair_slot=repair_slot,
        maximum_attempts=attempts,
        maximum_automatic_backjump=backjump,
        effect=effect,
    )


PRODUCTION_FEEDBACK = FeedbackCatalog(
    (
        _contract(
            "feedback.research.plan",
            "research.plan.valid",
            "The query plan covers workflow, tool, state, authority, error and risk questions.",
            "precommit",
            "Real search cannot begin from an invalid or unbounded query plan.",
            "hybrid",
            "L2",
            "research",
            "research_plan",
            1,
            0,
            "reject_revision",
            "design",
        ),
        _contract(
            "feedback.research.evidence",
            "research.evidence.grounded",
            "Observed claims bind fetched passages and preserve conflicts and unknowns.",
            "precommit",
            "World semantics must not be authored from snippets or model memory.",
            "hybrid",
            "L2",
            "research",
            "evidence_synthesis",
            1,
            0,
            "block_compile",
            "design",
        ),
        _contract(
            "feedback.design.world_architecture",
            "design.architecture.compiles",
            "World identity, state fields, tool surfaces and invariant intents form one closure.",
            "precommit",
            "Tool behavior requires one frozen architecture and state vocabulary.",
            "hybrid",
            "L2",
            "design",
            "world_architecture",
            2,
            0,
            "block_compile",
        ),
        _contract(
            "feedback.design.shared_tool_semantics",
            "design.shared_tool_semantics.compiles",
            "A multi-batch tool group has one closed atomicity, concurrency, "
            "idempotency, ordering, compensation and error policy.",
            "precommit",
            "Every physical tool batch in a coupled group must compile against the "
            "same frozen shared behavior policy.",
            "hybrid",
            "L2",
            "design",
            "shared_tool_semantics",
            2,
            0,
            "block_compile",
        ),
        _contract(
            "feedback.design.tool_semantics",
            "design.tool_semantics.compiles",
            "A coupled tool batch has typed transition, error, authority and reliability meaning.",
            "precommit",
            "Only compiled tool behavior can enter WorldModel closure.",
            "hybrid",
            "L2",
            "design",
            "tool_semantics_batch",
            2,
            0,
            "block_compile",
        ),
        _contract(
            "feedback.design.world_rules",
            "design.world_rules.compiles",
            "Reset and global invariant rules close over the frozen state and tool semantics.",
            "precommit",
            "Task generation requires one executable world rule closure.",
            "hybrid",
            "L2",
            "design",
            "world_rules",
            2,
            0,
            "block_compile",
        ),
        _contract(
            "feedback.design.task_curriculum",
            "design.task_curriculum.compiles",
            "Task families are diverse, reachable and bound to the frozen executable world.",
            "precommit",
            "Builder requires final TaskRequirement and materializer protocols in its Design.",
            "hybrid",
            "L2",
            "design",
            "task_curriculum",
            2,
            0,
            "block_compile",
        ),
        _contract(
            "feedback.design.modeling_gate",
            "design.valid",
            "The exact EnvironmentDesign passes deterministic evidence and modeling closure.",
            "postcommit",
            "Builder and Verifier must consume one valid semantic revision.",
            "code",
            "L0",
            "design",
            "environment_design",
            1,
            0,
            "block_integration",
        ),
        _contract(
            "feedback.build.candidate",
            "build.valid",
            "Generated source is a closed reproducible implementation of the exact Design.",
            "precommit",
            "Invalid source cannot enter clean installation or Runtime supervision.",
            "hybrid",
            "L2",
            "build",
            "candidate_workspace",
            2,
            0,
            "block_integration",
        ),
        _contract(
            "feedback.verifier.intent",
            "verifier.valid",
            "Adversarial intent compiles into closed framework-owned Verifier IR.",
            "precommit",
            "Release Judge cannot execute incomplete or self-authored checks.",
            "hybrid",
            "L3",
            "verifier",
            "verifier_intent_batch",
            1,
            0,
            "block_release",
        ),
        _contract(
            "feedback.integration.runtime",
            "integration.ready",
            "The final candidate installs and executes its protocol and task materializer.",
            "post_build",
            "Execution feedback should begin immediately after the final Build commits.",
            "real_execution",
            "L1",
            "judge",
            None,
            0,
            0,
            "block_release",
        ),
        _contract(
            "feedback.judge.release",
            "release_judge.valid",
            "Reachability, property, sealed and clean deployment gates pass for final bytes.",
            "pre_release",
            "This is the final independent execution evidence before publication.",
            "real_execution",
            "L3",
            "judge",
            None,
            0,
            0,
            "block_release",
        ),
        _contract(
            "feedback.controller.observability",
            "observability.release_ready",
            "Sanitized telemetry covers every required release operation with unknowns preserved.",
            "pre_release",
            "A published environment must remain auditable and experimentally reproducible.",
            "code",
            "L0",
            "controller",
            None,
            0,
            0,
            "block_release",
        ),
        _contract(
            "feedback.registry.publish",
            "registry.released",
            "Registry atomically committed and re-read the exact verified package bytes.",
            "post_release",
            "Released maturity exists only after physical Registry verification.",
            "code",
            "L1",
            "registry",
            None,
            0,
            0,
            "evidence_only",
        ),
    )
)


__all__ = [
    "FeedbackCatalog",
    "FeedbackComponent",
    "FeedbackContract",
    "FeedbackCostClass",
    "FeedbackEffect",
    "FeedbackExecutor",
    "FeedbackResult",
    "FeedbackStatus",
    "FeedbackTiming",
    "PRODUCTION_FEEDBACK",
    "RepairTargetRef",
]
