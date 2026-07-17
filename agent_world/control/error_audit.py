"""Deterministic periodic error audits for the Foundry control plane."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from .models import RepairLedgerEntry

AuditTrigger = Literal[
    "error_interval",
    "time_interval",
    "no_progress",
    "generic_diagnostic",
    "issue_churn",
]

_HASH_ONLY = re.compile(r"(?:^|:)[0-9a-f]{12,64}$")


@dataclass(frozen=True, slots=True)
class ErrorAuditDecision:
    trigger_codes: tuple[AuditTrigger, ...]
    repair_entry_count: int
    terminal_entry_count: int
    open_authorization_count: int
    no_progress_count: int
    issue_counts: tuple[tuple[str, int], ...]
    outcome_counts: tuple[tuple[str, int], ...]
    recommended_actions: tuple[str, ...]

    @property
    def triggered(self) -> bool:
        return bool(self.trigger_codes)

    def persistence_projection(self) -> dict[str, object]:
        return {
            "trigger_codes": list(self.trigger_codes),
            "repair_entry_count": self.repair_entry_count,
            "terminal_entry_count": self.terminal_entry_count,
            "open_authorization_count": self.open_authorization_count,
            "no_progress_count": self.no_progress_count,
            "issue_counts": [
                {"issue_code": code, "count": count} for code, count in self.issue_counts
            ],
            "outcome_counts": [
                {"outcome": outcome, "count": count}
                for outcome, count in self.outcome_counts
            ],
            "recommended_actions": list(self.recommended_actions),
        }


@dataclass(frozen=True, slots=True)
class ErrorAuditPolicy:
    """Trigger global diagnosis without adding another Agent to the hot path."""

    error_interval: int = 3
    time_interval_seconds: float = 30 * 60

    def __post_init__(self) -> None:
        if self.error_interval < 1 or self.time_interval_seconds <= 0:
            raise ValueError("error audit intervals must be positive")

    def evaluate(
        self,
        entries: tuple[RepairLedgerEntry, ...],
        *,
        last_audited_entry_count: int,
        seconds_since_last_audit: float,
    ) -> ErrorAuditDecision:
        if last_audited_entry_count < 0 or seconds_since_last_audit < 0:
            raise ValueError("error audit cursors cannot be negative")
        issue_counts = Counter(
            code for entry in entries for code in entry.blocking_claim_ids_before
        )
        outcome_counts = Counter(entry.outcome for entry in entries)
        new_entries = entries[last_audited_entry_count:]
        triggers: list[AuditTrigger] = []
        if len(entries) - last_audited_entry_count >= self.error_interval:
            triggers.append("error_interval")
        if new_entries and seconds_since_last_audit >= self.time_interval_seconds:
            triggers.append("time_interval")
        if any(entry.outcome == "no_progress" for entry in new_entries):
            triggers.append("no_progress")
        if any(
            code == "semantic_contract_violation" or _HASH_ONLY.search(code) is not None
            for entry in new_entries
            for code in entry.blocking_claim_ids_before
        ):
            triggers.append("generic_diagnostic")
        if self._has_issue_churn(new_entries):
            triggers.append("issue_churn")

        recommendations: list[str] = []
        if "generic_diagnostic" in triggers:
            recommendations.append("replace_generic_diagnostic_with_typed_issue")
        if "no_progress" in triggers or "issue_churn" in triggers:
            recommendations.append("stop_or_escalate_repair_lineage")
        if outcome_counts["authorized"]:
            recommendations.append("close_or_recover_open_repair_authorizations")
        if len(entries) > 0 and len(entries) / max(1, outcome_counts["resolved"]) > 2:
            recommendations.append("inspect_rework_amplification_and_gate_placement")
        return ErrorAuditDecision(
            trigger_codes=tuple(dict.fromkeys(triggers)),
            repair_entry_count=len(entries),
            terminal_entry_count=sum(entry.outcome != "authorized" for entry in entries),
            open_authorization_count=outcome_counts["authorized"],
            no_progress_count=outcome_counts["no_progress"],
            issue_counts=tuple(sorted(issue_counts.items())),
            outcome_counts=tuple(sorted(outcome_counts.items())),
            recommended_actions=tuple(dict.fromkeys(recommendations)),
        )

    @staticmethod
    def _has_issue_churn(entries: tuple[RepairLedgerEntry, ...]) -> bool:
        for previous, current in zip(entries, entries[1:], strict=False):
            if (
                previous.finding_fingerprint == current.finding_fingerprint
                and previous.target_node == current.target_node
                and set(previous.blocking_claim_ids_before).isdisjoint(
                    current.blocking_claim_ids_before
                )
                and previous.progress_evidence != "validation_stage_advanced"
            ):
                return True
        return False


__all__ = ["AuditTrigger", "ErrorAuditDecision", "ErrorAuditPolicy"]
