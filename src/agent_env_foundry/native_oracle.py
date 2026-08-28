"""Host-sealed calls to an independently authored, release-local native oracle."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry._qualification_runner import _tree_manifest
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.qualification import (
    QualificationConfig,
    QualificationFailure,
    _clean_env,
    _run,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.schema import SchemaError, validate_instance
from agent_env_foundry.semantics import (
    AtomCheckResult,
    CapabilitySpec,
    StartCase,
    TraceEvent,
    atom_result_from_document,
)

_REQUEST_FORMAT = "native-semantic-request/1"
_RESULT_FORMAT = "native-semantic-result/1"
_ROLES = frozenset(
    {
        "primary",
        "fresh-replay",
        "no-op",
        "wrong-target",
        "wrong-answer",
        "process-violation",
        "collateral",
        "boundary",
        "mutant",
    }
)


class NativeOracleFailure(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = {"phase": "native_oracle", **details}


@dataclass(frozen=True, slots=True)
class NativeAtomEvidence:
    materialization_id: str
    request_digest: str
    result_digest: str
    public_binding: JSONObject
    atom_result: AtomCheckResult
    native_observations: tuple[JSONValue, ...]
    source_use: JSONObject

    def to_document(self) -> JSONObject:
        return {
            "materialization_id": self.materialization_id,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "public_binding": self.public_binding,
            "atom_result": self.atom_result.to_document(),
            "native_observations": list(self.native_observations),
            "source_use": self.source_use,
        }


class NativeOracleSession:
    """Bind many checks to one exact Candidate/Semantics/oracle lineage."""

    def __init__(
        self,
        *,
        probe_path: Path,
        runtime_root: Path,
        candidate_digest: str,
        expected_task_semantics_digest: str,
        semantics_digest: str,
        oracle_bundle_digest: str,
        config: QualificationConfig,
    ) -> None:
        self._probe_path = probe_path
        self._runtime_root = runtime_root
        self._candidate_digest = candidate_digest
        self._expected_task_semantics_digest = expected_task_semantics_digest
        self._semantics_digest = semantics_digest
        self._oracle_bundle_digest = oracle_bundle_digest
        self._config = config
        self._evidence: list[NativeAtomEvidence] = []

    def check_atom(
        self,
        *,
        role: str,
        capability: CapabilitySpec,
        start_case: StartCase,
        before_instance: Path,
        after_instance: Path,
        public_binding: JSONObject,
        trace: tuple[TraceEvent, ...],
        final_answer: JSONValue | None,
    ) -> NativeAtomEvidence:
        ordinal = len(self._evidence) + 1
        identity = hashlib.sha256(
            canonical_bytes(
                {
                    "ordinal": ordinal,
                    "role": role,
                    "capability_id": capability.capability_id,
                    "start_case": start_case.to_document(),
                    "public_binding": public_binding,
                    "trace": [event.to_document() for event in trace],
                    "final_answer": final_answer,
                }
            )
        ).hexdigest()[:16]
        evidence = run_native_oracle_atom(
            probe_path=self._probe_path,
            runtime_root=self._runtime_root,
            materialization_id=f"{ordinal:04d}-{identity}",
            role=role,
            candidate_digest=self._candidate_digest,
            expected_task_semantics_digest=self._expected_task_semantics_digest,
            semantics_digest=self._semantics_digest,
            oracle_bundle_digest=self._oracle_bundle_digest,
            capability=capability,
            start_case=start_case,
            before_instance=before_instance,
            after_instance=after_instance,
            public_binding=public_binding,
            trace=trace,
            final_answer=final_answer,
            config=self._config,
        )
        self._evidence.append(evidence)
        return evidence

    @property
    def evidence_digest(self) -> str:
        if not self._evidence:
            raise NativeOracleFailure(
                "native_oracle_evidence_missing",
                "No independent native-oracle checks were completed",
            )
        return hashlib.sha256(
            canonical_bytes([item.to_document() for item in self._evidence])
        ).hexdigest()


def run_native_oracle_atom(
    *,
    probe_path: Path,
    runtime_root: Path,
    materialization_id: str,
    role: str,
    candidate_digest: str,
    expected_task_semantics_digest: str,
    semantics_digest: str,
    oracle_bundle_digest: str,
    capability: CapabilitySpec,
    start_case: StartCase,
    before_instance: Path,
    after_instance: Path,
    public_binding: JSONObject,
    trace: tuple[TraceEvent, ...],
    final_answer: JSONValue | None,
    config: QualificationConfig,
) -> NativeAtomEvidence:
    """Run one oracle check against Host-copied exact before/after instances."""
    if role not in _ROLES:
        raise NativeOracleFailure("native_oracle_role_invalid", "Native oracle role is invalid")
    if not materialization_id or any(character.isspace() for character in materialization_id):
        raise NativeOracleFailure(
            "native_oracle_materialization_invalid",
            "Native oracle materialization ID must be non-empty and whitespace-free",
        )
    probe = Path(probe_path)
    if probe.is_symlink() or not probe.is_file():
        raise NativeOracleFailure(
            "native_oracle_missing",
            "Independent native oracle is unavailable",
            path=str(probe),
        )
    _verify_oracle_bundle(probe, oracle_bundle_digest)
    root = Path(runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    materialization = root / materialization_id
    if materialization.is_symlink() or (
        materialization.exists() and any(materialization.iterdir())
    ):
        raise NativeOracleFailure(
            "native_oracle_materialization_not_fresh",
            "Native oracle materialization directory must be fresh and empty",
            path=str(materialization),
        )
    materialization.mkdir()
    before_copy = materialization / "before"
    after_copy = materialization / "after"
    _copy_instance(Path(before_instance), before_copy)
    _copy_instance(Path(after_instance), after_copy)
    before_manifest = _tree_manifest(before_copy)
    after_manifest = _tree_manifest(after_copy)
    trace_document: JSONValue = [event.to_document() for event in trace]
    journal_digest = hashlib.sha256(canonical_bytes(trace_document)).hexdigest()
    request: JSONObject = {
        "format": _REQUEST_FORMAT,
        "materialization_id": materialization_id,
        "role": role,
        "candidate_digest": candidate_digest,
        "expected_task_semantics_digest": expected_task_semantics_digest,
        "semantics_digest": semantics_digest,
        "oracle_bundle_digest": oracle_bundle_digest,
        "capability": {
            "capability_id": capability.capability_id,
            "requirement_ids": list(capability.requirement_ids),
            "task_kind": capability.task_kind,
            "intent_label": capability.intent_label,
            "answer_fields": [
                {
                    "field_id": field.field_id,
                    "public_label": field.public_label,
                    "schema": field.schema,
                }
                for field in capability.answer_fields
            ],
        },
        "start_case": start_case.to_document(),
        "before_path": "before",
        "after_path": "after",
        "before_manifest_digest": before_manifest.digest,
        "after_manifest_digest": after_manifest.digest,
        "journal_digest": journal_digest,
        "public_binding": public_binding,
        "trace_projection": trace_document,
        "final_answer": final_answer,
    }
    request_path = materialization / "request.json"
    request_bytes = canonical_bytes(request)
    request_digest = hashlib.sha256(request_bytes).hexdigest()
    request_path.write_bytes(request_bytes)
    request_path.chmod(0o444)
    result_path = materialization / "result.json"
    env = _clean_env(config)
    for name in tuple(env):
        if name in {"OPENAI_API_KEY", "OPENAI_BASE_URL"} or any(
            marker in name.upper() for marker in ("SECRET", "TOKEN")
        ):
            env.pop(name, None)
    try:
        _run(
            (
                sys.executable,
                "-I",
                str(probe.resolve()),
                "semantic-check",
                str(request_path),
                str(result_path),
            ),
            probe.parent,
            env,
            config,
            f"native_oracle:{materialization_id}",
        )
    except QualificationFailure as exc:
        raise NativeOracleFailure(
            exc.code,
            str(exc),
            **{key: value for key, value in exc.details.items() if key != "phase"},
        ) from exc
    if (
        request_path.read_bytes() != request_bytes
        or stat.S_IMODE(request_path.stat().st_mode) != 0o444
    ):
        raise NativeOracleFailure(
            "native_oracle_request_mutated",
            "Independent native oracle changed its Host request",
        )
    if before_manifest.digest != _tree_manifest(before_copy).digest or (
        after_manifest.digest != _tree_manifest(after_copy).digest
    ):
        raise NativeOracleFailure(
            "native_oracle_mutated_state",
            "Independent native oracle changed a controlled actor instance",
        )
    extras = {path.name for path in materialization.iterdir()} - {
        "before",
        "after",
        "request.json",
        "result.json",
    }
    if extras:
        raise NativeOracleFailure(
            "native_oracle_unexpected_output",
            "Independent native oracle wrote files outside the bounded result",
            paths=sorted(extras),
        )
    result_bytes = _read_result_bytes(result_path)
    result = _decode_result(result_bytes)
    _exact_result_binding(
        result,
        request_digest=request_digest,
        materialization_id=materialization_id,
        capability=capability,
        public_binding=public_binding,
    )
    try:
        atom_result = atom_result_from_document(result["atom_result"])
    except Exception as exc:
        raise NativeOracleFailure(
            "native_oracle_result_invalid",
            "Native oracle atom_result is invalid",
            original_message=str(exc),
        ) from exc
    _validate_answer_reports(capability, atom_result)
    observations = result["native_observations"]
    source_use = result["source_use"]
    if not isinstance(observations, list) or not observations or not isinstance(source_use, dict):
        raise NativeOracleFailure(
            "native_oracle_result_invalid",
            "Native oracle requires non-empty observations and structured source_use",
        )
    return NativeAtomEvidence(
        materialization_id,
        request_digest,
        hashlib.sha256(result_bytes).hexdigest(),
        cast(JSONObject, json.loads(canonical_bytes(public_binding))),
        atom_result,
        tuple(cast(list[JSONValue], observations)),
        cast(JSONObject, source_use),
    )


def _copy_instance(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise NativeOracleFailure(
            "native_oracle_instance_invalid",
            "Native oracle source instance must be a real directory",
            path=str(source),
        )
    shutil.copytree(source, destination, symlinks=True)
    if _tree_manifest(source).digest != _tree_manifest(destination).digest:
        raise NativeOracleFailure(
            "native_oracle_instance_copy_mismatch",
            "Native oracle copy differs from the executed actor instance",
            path=str(source),
        )


def _verify_oracle_bundle(probe: Path, expected_digest: str) -> None:
    manifest = probe.with_name("probe_manifest.json")
    if manifest.is_symlink() or not manifest.is_file():
        raise NativeOracleFailure(
            "native_oracle_bundle_missing",
            "Native oracle bundle manifest is unavailable",
        )
    payload = manifest.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise NativeOracleFailure(
            "native_oracle_bundle_mismatch",
            "Native oracle bundle digest differs from admitted Qualification evidence",
        )
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeOracleFailure(
            "native_oracle_bundle_invalid",
            "Native oracle bundle manifest is invalid JSON",
        ) from exc
    files = document.get("files") if isinstance(document, dict) else None
    record = (
        next(
            (item for item in files if isinstance(item, dict) and item.get("path") == probe.name),
            None,
        )
        if isinstance(files, list)
        else None
    )
    if (
        not isinstance(record, dict)
        or record.get("digest") != hashlib.sha256(probe.read_bytes()).hexdigest()
    ):
        raise NativeOracleFailure(
            "native_oracle_bundle_mismatch",
            "Native oracle source bytes differ from the admitted bundle",
        )


def _read_result_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise NativeOracleFailure(
            "native_oracle_result_missing",
            "Native oracle did not write one regular result file",
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise NativeOracleFailure(
            "native_oracle_result_invalid",
            "Native oracle result cannot be read",
            original_message=str(exc),
        ) from exc


def _decode_result(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeOracleFailure(
            "native_oracle_result_invalid",
            "Native oracle result is not JSON",
            original_message=str(exc),
        ) from exc
    required = {
        "format",
        "request_digest",
        "materialization_id",
        "capability_id",
        "public_binding",
        "atom_result",
        "native_observations",
        "source_use",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("format") != _RESULT_FORMAT
    ):
        raise NativeOracleFailure(
            "native_oracle_result_invalid",
            "Native oracle result has invalid fields or format",
        )
    return value


def _exact_result_binding(
    result: dict[str, Any],
    *,
    request_digest: str,
    materialization_id: str,
    capability: CapabilitySpec,
    public_binding: JSONObject,
) -> None:
    if result["request_digest"] != request_digest:
        raise NativeOracleFailure(
            "native_oracle_request_mismatch",
            "Native oracle result request digest does not bind the exact request",
            expected=request_digest,
            actual=result["request_digest"],
        )
    if result["materialization_id"] != materialization_id or (
        result["capability_id"] != capability.capability_id
    ):
        raise NativeOracleFailure(
            "native_oracle_identity_mismatch",
            "Native oracle result identifies a different materialization or capability",
        )
    if canonical_bytes(result["public_binding"]) != canonical_bytes(public_binding):
        raise NativeOracleFailure(
            "native_oracle_binding_mismatch",
            "Native oracle identified a different public binding",
        )


def _validate_answer_reports(capability: CapabilitySpec, result: AtomCheckResult) -> None:
    expected = {field.field_id for field in capability.answer_fields}
    if set(result.report_values) != expected:
        raise NativeOracleFailure(
            "native_oracle_answer_fields_mismatch",
            "Native oracle report fields differ from the frozen answer contract",
            expected=sorted(expected),
            actual=sorted(result.report_values),
        )
    for field in capability.answer_fields:
        try:
            validate_instance(
                result.report_values[field.field_id],
                field.schema,
                role=f"native oracle answer {field.field_id!r}",
            )
        except SchemaError as exc:
            raise NativeOracleFailure(
                "native_oracle_answer_invalid",
                "Native oracle answer value violates the generated wire schema",
                field_id=field.field_id,
                original_message=str(exc),
            ) from exc
