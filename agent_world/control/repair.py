"""Framework-owned root-cause routing, bounded backjump and repair history."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, BudgetUsage, Finding

from .decision import StructuredRepairMode
from .feedback import RepairTargetRef
from .models import NodeKind, RepairDirective, RepairLedgerEntry
from .validation import ValidationDiagnostic

_DOWNSTREAM: dict[NodeKind, tuple[NodeKind, ...]] = {
    "request": ("design", "verifier", "build", "integration", "judge", "release"),
    "discovery": (),
    "design": ("verifier", "build", "integration", "judge", "release"),
    "verifier": ("judge", "release"),
    "build": ("integration", "judge", "release"),
    "integration": ("judge", "release"),
    "judge": ("release",),
    "release": (),
}

type RepairOwner = Literal["design", "verifier", "build", "judge", "release", "human"]
type RepairAction = Literal[
    "continue_session",
    "new_revision",
    "retry_infrastructure",
    "request_permission",
    "reject",
]


class StructuredRepairDenied(RuntimeError):
    """The framework-owned global RepairLedger rejected a component retry."""


class StructuredRepairAuthority(Protocol):
    """Async Controller authority shared by every component-local correction."""

    async def authorize(
        self,
        *,
        owner_node: Literal["design", "verifier", "build", "judge"],
        lineage_id: str,
        role: str,
        repair_mode: StructuredRepairMode,
        issue_codes: tuple[str, ...],
        continued_session: bool,
        diagnostic: ValidationDiagnostic | None = None,
        feedback_contract_id: str | None = None,
        repair_target: RepairTargetRef | None = None,
    ) -> str: ...

    async def complete(
        self,
        entry_id: str,
        *,
        remaining_issue_codes: tuple[str, ...],
        continued_session: bool,
        remaining_diagnostic: ValidationDiagnostic | None = None,
    ) -> None: ...


def invalidated_nodes(owner: NodeKind) -> tuple[NodeKind, ...]:
    return _DOWNSTREAM[owner]


class RepairLedger:
    """One in-memory projection of durable RepairLedgerEntry artifacts per run.

    The Controller persists every returned entry before executing the directive.
    This object owns authorization/no-progress policy; component-local retry loops
    do not receive an independent repair allowance.
    """

    def __init__(self, entries: tuple[RepairLedgerEntry, ...] = ()) -> None:
        if len({item.entry_id for item in entries}) != len(entries):
            raise ValueError("RepairLedger restore contains duplicate entry ids")
        self._entries: list[RepairLedgerEntry] = list(entries)

    @property
    def entries(self) -> tuple[RepairLedgerEntry, ...]:
        return tuple(self._entries)

    def attempts_for(self, fingerprint: str, target_node: RepairOwner) -> int:
        return sum(
            item.finding_fingerprint == fingerprint and item.target_node == target_node
            for item in self._entries
        )

    def authorize(
        self,
        *,
        finding: Finding,
        finding_ref: ArtifactRef,
        related_finding_refs: tuple[ArtifactRef, ...] = (),
        repair_fingerprint: str | None = None,
        current_node: NodeKind,
        target_node: RepairOwner,
        owner_ref: ArtifactRef | None,
        action: RepairAction,
        jump_distance: int,
        causal_evidence_refs: tuple[ArtifactRef, ...],
        blocking_claim_ids_before: tuple[str, ...],
        validation_phase_before: str | None = None,
        validation_frontier_before: int | None = None,
        maximum_attempts: int | None = None,
    ) -> RepairLedgerEntry:
        if maximum_attempts is not None and maximum_attempts < 0:
            raise ValueError("maximum_attempts cannot be negative")
        effective_fingerprint = repair_fingerprint or finding.fingerprint
        attempt = self.attempts_for(effective_fingerprint, target_node) + 1
        local_limit = 2 if jump_distance == 0 else 1
        allowed = local_limit if maximum_attempts is None else min(local_limit, maximum_attempts)
        outcome: Literal["authorized", "exhausted", "rejected"] = "authorized"
        repeated_no_progress = any(
            item.finding_fingerprint == effective_fingerprint
            and item.target_node == target_node
            and item.outcome == "no_progress"
            for item in self._entries
        )
        forbidden_automatic_jump = jump_distance >= 2 and action != "request_permission"
        if forbidden_automatic_jump or repeated_no_progress or attempt > allowed:
            outcome = "rejected" if forbidden_automatic_jump else "exhausted"
            action = "reject"
            jump_distance = 0
        if jump_distance == 1 and not causal_evidence_refs:
            outcome = "rejected"
            action = "reject"
            jump_distance = 0
        digest = hashlib.sha256(
            (
                f"{finding_ref.revision_id}\0{current_node}\0{target_node}\0{attempt}\0{action}"
            ).encode()
        ).hexdigest()[:24]
        entry = RepairLedgerEntry(
            entry_id=f"repair-entry:{digest}",
            finding_ref=finding_ref,
            related_finding_refs=related_finding_refs,
            finding_fingerprint=effective_fingerprint,
            observed_subject_ref=finding.subject_ref,
            resolved_owner_ref=owner_ref,
            current_node=current_node,
            target_node=target_node,
            action=action,
            jump_distance=jump_distance,
            causal_evidence_refs=causal_evidence_refs,
            blocking_claim_ids_before=blocking_claim_ids_before,
            validation_phase_before=validation_phase_before,
            validation_frontier_before=validation_frontier_before,
            outcome=outcome,
            attempt_ordinal=attempt,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC) if outcome != "authorized" else None,
        )
        self._entries.append(entry)
        return entry

    def complete(
        self,
        entry_id: str,
        *,
        blocking_claim_ids_after: tuple[str, ...],
        invalidated_refs: tuple[ArtifactRef, ...] = (),
        retained_refs: tuple[ArtifactRef, ...] = (),
        session_strategy: Literal["continued", "fresh", "none"] = "none",
        progress_evidence: Literal[
            "none", "issue_set_changed", "validation_stage_advanced"
        ] = "none",
        validation_phase_after: str | None = None,
        validation_frontier_after: int | None = None,
        usage: BudgetUsage | None = None,
    ) -> RepairLedgerEntry:
        index = next(
            (index for index, item in enumerate(self._entries) if item.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown RepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise ValueError("RepairLedger entry is already terminal")
        before = set(current.blocking_claim_ids_before)
        after = set(blocking_claim_ids_after)
        seen_blocker_sets = {
            frozenset(blockers)
            for item in self._entries
            if item.entry_id != current.entry_id
            and item.finding_fingerprint == current.finding_fingerprint
            and item.target_node == current.target_node
            for blockers in (
                item.blocking_claim_ids_before,
                item.blocking_claim_ids_after,
            )
            if blockers
        }
        oscillated = bool(after) and frozenset(after) in seen_blocker_sets
        if not after:
            outcome = "resolved"
        elif oscillated:
            outcome = "no_progress"
        elif after < before:
            outcome = "progressed"
        elif progress_evidence in {"issue_set_changed", "validation_stage_advanced"}:
            outcome = "progressed"
        else:
            outcome = "no_progress"
        updated = RepairLedgerEntry.model_validate(
            {
                **current.model_dump(mode="python"),
                "blocking_claim_ids_after": blocking_claim_ids_after,
                "invalidated_refs": invalidated_refs,
                "retained_refs": retained_refs,
                "session_strategy": session_strategy,
                "progress_evidence": progress_evidence,
                "validation_phase_after": validation_phase_after,
                "validation_frontier_after": validation_frontier_after,
                "outcome": outcome,
                "finished_at": datetime.now(UTC),
                "usage": usage or BudgetUsage(),
            }
        )
        self._entries[index] = updated
        return updated

    def terminate(
        self,
        entry_id: str,
        *,
        outcome: Literal["escalated", "exhausted", "rejected"],
        retained_refs: tuple[ArtifactRef, ...] = (),
        usage: BudgetUsage | None = None,
    ) -> RepairLedgerEntry:
        """Close an authorization that policy decided not to execute.

        A report may authorize more than one owner/action group, while the
        Controller can execute only one causally coherent transition.  Every
        non-selected authorization is made terminal before control leaves the
        node, so release recovery never observes an abandoned open action.
        """

        index = next(
            (index for index, item in enumerate(self._entries) if item.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown RepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise ValueError("RepairLedger entry is already terminal")
        updated = RepairLedgerEntry.model_validate(
            {
                **current.model_dump(mode="python"),
                "blocking_claim_ids_after": current.blocking_claim_ids_before,
                "retained_refs": retained_refs,
                "session_strategy": "none",
                "progress_evidence": "none",
                "outcome": outcome,
                "finished_at": datetime.now(UTC),
                "usage": usage or BudgetUsage(),
            }
        )
        self._entries[index] = updated
        return updated


class RepairRouter:
    """Resolve owner from failure taxonomy and Artifact types, then authorize repair."""

    def __init__(self, *, maximum_attempts: int, artifact_store: ArtifactWriter) -> None:
        if maximum_attempts < 0:
            raise ValueError("maximum_attempts cannot be negative")
        self.maximum_attempts = maximum_attempts
        self.artifacts = artifact_store

    def route(
        self,
        finding: Finding,
        finding_ref: ArtifactRef,
        *,
        current_node: NodeKind = "judge",
        ledger: RepairLedger | None = None,
        blocking_claim_ids_before: tuple[str, ...] = (),
    ) -> RepairDirective:
        return self.route_group(
            ((finding, finding_ref),),
            current_node=current_node,
            ledger=ledger,
            blocking_claim_ids_before=blocking_claim_ids_before,
        )

    def route_many(
        self,
        findings: Sequence[tuple[Finding, ArtifactRef]],
        *,
        current_node: NodeKind = "judge",
        ledger: RepairLedger | None = None,
        blocking_claim_ids_before: tuple[str, ...] = (),
    ) -> tuple[RepairDirective, ...]:
        """Group one Judge report into executable repair actions.

        Findings remain individually persisted evidence.  Only Findings with the
        same resolved owner and action share authorization and budget history.
        """

        groups: dict[tuple[RepairOwner, RepairAction], list[tuple[Finding, ArtifactRef]]] = {}
        for finding, finding_ref in findings:
            self._validate_framework_finding(finding, finding_ref)
            owner = self._resolve_owner(finding)
            key = (owner, self._action(owner))
            groups.setdefault(key, []).append((finding, finding_ref))
        return tuple(
            self.route_group(
                tuple(group),
                current_node=current_node,
                ledger=ledger,
                blocking_claim_ids_before=blocking_claim_ids_before,
            )
            for group in groups.values()
        )

    def route_group(
        self,
        findings: Sequence[tuple[Finding, ArtifactRef]],
        *,
        current_node: NodeKind = "judge",
        ledger: RepairLedger | None = None,
        blocking_claim_ids_before: tuple[str, ...] = (),
    ) -> RepairDirective:
        if not findings:
            raise ValueError("repair action requires at least one Finding")
        for item, ref in findings:
            self._validate_framework_finding(item, ref)
        finding, finding_ref = findings[0]
        owner = self._resolve_owner(finding)
        action = self._action(owner)
        if any(
            self._resolve_owner(item) != owner or self._action(self._resolve_owner(item)) != action
            for item, _ref in findings[1:]
        ):
            raise ValueError("RepairAction group must have one resolved owner and action")
        related_finding_refs = tuple(ref for _item, ref in findings[1:])
        owner_ref = next(
            (
                resolved
                for item, _ref in findings
                if (resolved := self._resolve_owner_ref(owner, item)) is not None
            ),
            None,
        )
        jump_distance = self._jump_distance(current_node, owner)
        causal = tuple(
            dict.fromkeys(ref for item, _finding_ref in findings for ref in item.evidence_refs)
        )
        if action != "reject" and owner_ref is None:
            action = "reject"
            jump_distance = 0
        action_fingerprint = (
            "repair-action:"
            + hashlib.sha256(
                (
                    f"{current_node}\0{owner}\0{action}\0"
                    f"{owner_ref.artifact_type if owner_ref is not None else 'unresolved'}"
                ).encode()
            ).hexdigest()
        )
        active_ledger = ledger or RepairLedger()
        entry = active_ledger.authorize(
            finding=finding,
            finding_ref=finding_ref,
            related_finding_refs=related_finding_refs,
            repair_fingerprint=action_fingerprint,
            current_node=current_node,
            target_node=owner,
            owner_ref=owner_ref,
            action=action,
            jump_distance=jump_distance,
            causal_evidence_refs=causal,
            blocking_claim_ids_before=blocking_claim_ids_before,
            maximum_attempts=self.maximum_attempts,
        )
        action = entry.action
        if action == "reject":
            invalidates: tuple[NodeKind, ...] = ()
        else:
            invalidates = invalidated_nodes(cast(NodeKind, owner)) if owner in _DOWNSTREAM else ()
        digest = hashlib.sha256(
            (
                "\0".join(ref.revision_id for _item, ref in findings)
                + f"\0{owner}\0{action}\0{entry.entry_id}"
            ).encode()
        ).hexdigest()[:24]
        summary = "\n".join(
            dict.fromkeys(item.suggested_repair or item.summary for item, _ref in findings)
        )
        disclosures = {item.disclosure for item, _ref in findings}
        disclosure = (
            "sealed_summary"
            if "sealed_summary" in disclosures
            else "repair"
            if "repair" in disclosures
            else "public"
        )
        reason = (
            "automatic backjump rejected by distance/attempt policy"
            if action == "reject" and owner != "release"
            else "framework failure taxonomy and Artifact ownership"
        )
        return RepairDirective(
            directive_id=f"repair:{digest}",
            finding_ref=finding_ref,
            related_finding_refs=related_finding_refs,
            owner_node=owner,
            action=action,
            invalidates=invalidates,
            disclosure=cast(Literal["public", "repair", "sealed_summary"], disclosure),
            repair_summary=summary,
            maximum_attempts=self.maximum_attempts,
            current_node=current_node,
            owner_ref=owner_ref,
            jump_distance=entry.jump_distance,
            causal_evidence_refs=entry.causal_evidence_refs,
            blocking_claim_ids_before=blocking_claim_ids_before,
            ledger_entry_id=entry.entry_id,
            decision_reason=reason,
        )

    def _validate_framework_finding(
        self,
        finding: Finding,
        finding_ref: ArtifactRef,
    ) -> None:
        """Bind routing to the exact framework-authored durable Finding."""

        self.artifacts.require_exact_json(
            finding_ref,
            finding,
            artifact_types=("control.finding",),
        )
        revision = self.artifacts.get_revision(finding_ref)
        if revision.producer != "framework":
            raise ValueError("RepairRouter accepts only framework-authored Findings")

    @staticmethod
    def _resolve_owner(finding: Finding) -> RepairOwner:
        """Resolve only the framework-owned closed owner enum.

        ``Finding.category`` is descriptive telemetry.  It is deliberately not
        interpreted as routing input, because free semantic text must never gain
        workflow authority through a prefix convention.
        """

        return cast(
            RepairOwner,
            {
                "design": "design",
                "verifier": "verifier",
                "build": "build",
                "judge_infrastructure": "judge",
                "permissions": "human",
                "release_policy": "release",
            }[finding.owner],
        )

    @staticmethod
    def _action(owner: RepairOwner) -> RepairAction:
        return cast(
            RepairAction,
            {
                "design": "new_revision",
                "verifier": "new_revision",
                "build": "continue_session",
                "judge": "retry_infrastructure",
                "human": "request_permission",
                "release": "reject",
            }[owner],
        )

    @staticmethod
    def _resolve_owner_ref(owner: RepairOwner, finding: Finding) -> ArtifactRef | None:
        candidates = (finding.subject_ref, *finding.evidence_refs)
        prefixes = {
            "design": ("design.", "expansion.environment_design", "expansion.world_spec"),
            "verifier": ("judge.verifier",),
            "build": ("build.",),
            "judge": ("judge.", "judge_report"),
            "release": ("release.", "environment_package_manifest"),
            "human": ("control.environment_request",),
        }[owner]
        return next(
            (ref for ref in candidates if ref.artifact_type.startswith(prefixes)),
            None,
        )

    @staticmethod
    def _jump_distance(current: NodeKind, owner: RepairOwner) -> int:
        if current == owner:
            return 0
        direct_inputs: dict[NodeKind, frozenset[RepairOwner]] = {
            "request": frozenset({"human"}),
            "discovery": frozenset({"design", "human"}),
            "design": frozenset({"human"}),
            "verifier": frozenset({"design"}),
            "build": frozenset({"design"}),
            "integration": frozenset({"design", "build", "judge"}),
            "judge": frozenset({"design", "verifier", "build"}),
            "release": frozenset({"design", "verifier", "build", "judge"}),
        }
        return 1 if owner in direct_inputs[current] else 2


__all__ = ["RepairLedger", "RepairRouter", "invalidated_nodes"]
