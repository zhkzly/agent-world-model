"""Small, framework-owned contracts for the Direct-only Foundry path.

These contracts deliberately model only facts the framework may persist.  Raw
prompts, provider payloads, credentials, sealed cases, and candidate claims do
not belong here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

TerminalStatus = Literal[
    "running",
    "released",
    "rejected",
    "needs_human",
    "budget_exhausted",
    "error",
]
GateStatus = Literal["passed", "failed", "not_run"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def digest_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def json_value(value: Any) -> Any:
    """Turn known framework dataclasses into JSON-ready values."""

    if is_dataclass(value) and not isinstance(value, type):
        return {key: json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    digest: str
    path: str
    media_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class RegistryReceipt:
    """Framework-issued publication facts, never a candidate declaration."""

    package_id: str
    version: str
    package_digest: str
    receipt_digest: str
    artifact: ArtifactRef


@dataclass(frozen=True, slots=True)
class SafeFailure:
    code: str
    status: TerminalStatus
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class EnvironmentRequest:
    request_id: str
    need: str
    need_digest: str

    @classmethod
    def create(cls, need: str) -> EnvironmentRequest:
        normalized = need.strip()
        if not normalized:
            raise ValueError("request_need_required")
        return cls(
            request_id=new_id("request"), need=normalized, need_digest=digest_text(normalized)
        )


@dataclass(frozen=True, slots=True)
class RunEvent:
    stage: str
    status: str
    at: str
    code: str | None = None
    artifact_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class DirectRun:
    run_id: str
    request_id: str
    request_digest: str
    status: TerminalStatus = "running"
    started_at: str = field(default_factory=utc_now)
    ended_at: str | None = None
    events: list[RunEvent] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    release: RegistryReceipt | None = None

    @classmethod
    def create(cls, request: EnvironmentRequest) -> DirectRun:
        return cls(
            run_id=new_id("run"),
            request_id=request.request_id,
            request_digest=request.need_digest,
        )

    def add_event(
        self,
        stage: str,
        status: str,
        *,
        code: str | None = None,
        artifacts: tuple[ArtifactRef, ...] = (),
    ) -> None:
        self.events.append(
            RunEvent(
                stage=stage,
                status=status,
                at=utc_now(),
                code=code,
                artifact_ids=tuple(ref.artifact_id for ref in artifacts),
            )
        )
        for ref in artifacts:
            if ref not in self.artifacts:
                self.artifacts.append(ref)

    def finish(
        self,
        status: TerminalStatus,
        *,
        code: str | None = None,
        receipt: RegistryReceipt | None = None,
    ) -> None:
        if status == "released":
            if receipt is not None:
                self.release = receipt
            if self.release is None:
                raise ValueError("released_receipt_required")
        elif receipt is not None:
            raise ValueError("non_release_receipt_forbidden")
        self.status = status
        self.ended_at = utc_now()
        self.add_event("run", status, code=code)

    def to_dict(self) -> dict[str, Any]:
        return json_value(self)


@dataclass(frozen=True, slots=True)
class ToolDraft:
    name: str
    description: str
    arguments: tuple[str, ...]
    result_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicStep:
    tool: str
    arguments: dict[str, Any]
    expected_result: dict[str, None | bool | int | float | str]


@dataclass(frozen=True, slots=True)
class DesignContract:
    environment_name: str
    summary: str
    tools: tuple[ToolDraft, ...]
    public_steps: tuple[PublicStep, ...]
    invariants: tuple[str, ...]
    artifact: ArtifactRef


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    entrypoint: str
    source_digest: str
    files: tuple[dict[str, Any], ...]
    artifact: ArtifactRef


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    status: GateStatus
    code: str | None
    evidence: ArtifactRef | None


@dataclass(frozen=True, slots=True)
class JudgeReport:
    candidate_digest: str
    gates: tuple[GateResult, ...]
    artifact: ArtifactRef

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(gate.status == "passed" for gate in self.gates)
