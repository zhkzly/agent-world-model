"""Independent evidence review for Need-to-environment semantic alignment."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from openai import OpenAI

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import (
    JSONObject,
    JSONValue,
    ToolSpec,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object, json_leaf_changes
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.research import BuilderProjection

SEMANTIC_QUALIFICATION_FORMAT = "environment-semantic-qualification/1"
QUALIFIED_CONFORMANCE_EVIDENCE_FORMAT = "environment-conformance-evidence/4"
_PROVIDER_TURN_TIMEOUT_SECONDS = 180.0
_PROMPT = """You are the independent semantic reviewer for one generated Agent environment.

Judge whether the supplied Host-executed evidence demonstrates every frozen Requirement. The
Builder's source, tests, declared expectations, and release verdict are deliberately unavailable.
Use only the frozen requirement text, public ToolSpecs, actual public observations, and protected
before/after state captured by the Host.

Rules:
- Return exactly one finding for every Requirement, in the supplied order.
- Cite only supplied evidence_ref values. A ToolSpec description or ok=true alone is not proof.
- Check concrete identities, quantities, ordering, preconditions, postconditions, invariants,
  refusal conditions, and prohibited mutation whenever the Requirement states them.
- Missing, ambiguous, contradictory, or insufficient evidence is not_satisfied. Never infer an
  unobserved behavior from likely implementation intent.
- Do not propose Tasks, answers, rewards, source edits, new requirements, or a release verdict.
  The Host derives the aggregate verdict from your individual findings.
"""

SemanticVerdict = Literal["satisfied", "not_satisfied"]
SemanticFailureKind = Literal["InfrastructureFailure", "QualifierDefect"]


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


class ClientFactory(Protocol):
    def __call__(self, *, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient: ...


class SemanticQualificationFailure(RuntimeError):
    def __init__(
        self,
        kind: SemanticFailureKind,
        code: str,
        message: str,
        **details: JSONValue,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.details: JSONObject = {"kind": kind, **details}


@dataclass(frozen=True, slots=True)
class SemanticFinding:
    requirement_id: str
    verdict: SemanticVerdict
    evidence_refs: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.requirement_id.strip():
            raise ValueError("semantic finding requirement_id must be non-empty")
        if self.verdict not in {"satisfied", "not_satisfied"}:
            raise ValueError("semantic finding verdict is invalid")
        if any(not item or not item.strip() for item in self.evidence_refs) or len(
            set(self.evidence_refs)
        ) != len(self.evidence_refs):
            raise ValueError("semantic finding evidence_refs must be unique non-empty strings")
        if self.verdict == "satisfied" and not self.evidence_refs:
            raise ValueError("satisfied semantic finding requires physical evidence")
        if not self.reason or not self.reason.strip():
            raise ValueError("semantic finding reason must be non-empty")

    def to_document(self) -> JSONObject:
        return {
            "requirement_id": self.requirement_id,
            "verdict": self.verdict,
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SemanticQualification:
    format: str
    actor_project_digest: str
    builder_projection_digest: str
    review_input_digest: str
    diagnostic_evidence_digest: str
    reviewer_model: str
    reviewer_prompt_digest: str
    provider_turns: int
    usage: tuple[JSONObject | None, ...]
    findings: tuple[SemanticFinding, ...]

    def __post_init__(self) -> None:
        if self.format != SEMANTIC_QUALIFICATION_FORMAT:
            raise ValueError(
                f"semantic qualification format must be {SEMANTIC_QUALIFICATION_FORMAT!r}"
            )
        for value, role in (
            (self.actor_project_digest, "actor_project_digest"),
            (self.builder_projection_digest, "builder_projection_digest"),
            (self.review_input_digest, "review_input_digest"),
            (self.diagnostic_evidence_digest, "diagnostic_evidence_digest"),
            (self.reviewer_prompt_digest, "reviewer_prompt_digest"),
        ):
            _digest(value, role)
        if not self.reviewer_model.strip():
            raise ValueError("semantic qualification reviewer_model must be non-empty")
        if self.provider_turns <= 0 or len(self.usage) != self.provider_turns:
            raise ValueError("semantic qualification usage must match positive provider_turns")
        ids = tuple(item.requirement_id for item in self.findings)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("semantic qualification findings must cover unique requirements")

    @property
    def passed(self) -> bool:
        return all(item.verdict == "satisfied" for item in self.findings)

    @property
    def qualification_id(self) -> str:
        return sha256_hex(canonical_bytes(self._preimage()))

    def _preimage(self) -> JSONObject:
        return {
            "format": self.format,
            "verdict": "passed" if self.passed else "failed",
            "actor_project_digest": self.actor_project_digest,
            "builder_projection_digest": self.builder_projection_digest,
            "review_input_digest": self.review_input_digest,
            "diagnostic_evidence_digest": self.diagnostic_evidence_digest,
            "reviewer_model": self.reviewer_model,
            "reviewer_prompt_digest": self.reviewer_prompt_digest,
            "provider_turns": self.provider_turns,
            "usage": cast(JSONValue, list(self.usage)),
            "findings": [item.to_document() for item in self.findings],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "qualification_id": self.qualification_id}


@dataclass(frozen=True, slots=True)
class QualifiedSemanticEvidence:
    projection: BuilderProjection
    tool_specs: tuple[ToolSpec, ...]
    diagnostic_evidence: tuple[JSONObject, ...]
    qualification: SemanticQualification


def review_environment_semantics(
    projection: BuilderProjection,
    *,
    actor_project_digest: str,
    tool_specs: tuple[ToolSpec, ...],
    diagnostic_evidence: tuple[JSONObject, ...],
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
) -> SemanticQualification:
    """Review one frozen candidate without exposing Builder self-claims or source."""

    requirement_ids = _requirement_ids(projection)
    evidence_refs = _evidence_refs(diagnostic_evidence)
    normalized_tools = _normalized_tools(tool_specs)
    groups = _requirement_groups(projection)
    review_inputs = tuple(
        _review_input(
            projection,
            normalized_tools,
            diagnostic_evidence,
            requirement_ids=group,
        )
        for group in groups
    )
    selected_route = route or AgentRoute()
    factory = client_factory or _default_client_factory
    credential = os.environ.get("OPENAI_API_KEY")
    if not credential and client_factory is None:
        raise SemanticQualificationFailure(
            "InfrastructureFailure",
            "semantic_review_credential_missing",
            "OPENAI_API_KEY must be supplied at invocation time",
        )
    try:
        client = factory(
            api_key=credential or "injected-test-client",
            base_url=selected_route.base_url,
            max_retries=0,
        )
    except Exception as exc:
        raise SemanticQualificationFailure(
            "InfrastructureFailure",
            "semantic_review_client_init_failed",
            "cannot initialize the semantic review client",
            original_code=type(exc).__name__,
            original_message=_safe_message(exc, credential),
        ) from exc

    usage: list[JSONObject | None] = []
    findings_by_id: dict[str, SemanticFinding] = {}
    try:
        for group, review_input in zip(groups, review_inputs, strict=True):
            history: list[Any] = [
                {
                    "role": "user",
                    "content": json.dumps(
                        review_input,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            ]
            last_error = ""
            group_findings: tuple[SemanticFinding, ...] | None = None
            for correction in (0, 1):
                response = _provider_turn(
                    client,
                    route=selected_route,
                    history=history,
                    output_schema=_output_schema(group, evidence_refs),
                    credential=credential,
                )
                usage.append(_usage(response))
                output_text = _output_text(response)
                try:
                    group_findings = _parse_findings(
                        output_text,
                        requirement_ids=group,
                        evidence_refs=evidence_refs,
                    )
                except ValueError as exc:
                    last_error = str(exc)
                    if correction:
                        break
                    history.extend(
                        (
                            {"role": "assistant", "content": output_text},
                            {
                                "role": "user",
                                "content": (
                                    "The Host rejected only the review output shape. Preserve "
                                    "your semantic judgments and return the complete corrected "
                                    f"findings. Rejected condition: {last_error}. Expected "
                                    f"requirement order: {list(group)}. Valid evidence_refs: "
                                    f"{list(evidence_refs)}."
                                ),
                            },
                        )
                    )
                    continue
                break
            if group_findings is None:
                raise SemanticQualificationFailure(
                    "QualifierDefect",
                    "semantic_review_output_invalid",
                    "semantic reviewer failed the closed output contract after one correction",
                    rejected_condition=last_error,
                    expected_requirement_ids=cast(JSONValue, list(group)),
                    valid_evidence_refs=cast(JSONValue, list(evidence_refs)),
                )
            findings_by_id.update((finding.requirement_id, finding) for finding in group_findings)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    findings = tuple(findings_by_id[item] for item in requirement_ids)
    return SemanticQualification(
        SEMANTIC_QUALIFICATION_FORMAT,
        actor_project_digest,
        sha256_hex(canonical_bytes(projection.to_document())),
        sha256_hex(canonical_bytes(list(review_inputs))),
        sha256_hex(canonical_bytes(list(diagnostic_evidence))),
        selected_route.model,
        sha256_hex(_PROMPT.encode("utf-8")),
        len(usage),
        tuple(usage),
        findings,
    )


def semantic_qualification_from_document(document: Any) -> SemanticQualification:
    keys = {
        "format",
        "verdict",
        "actor_project_digest",
        "builder_projection_digest",
        "review_input_digest",
        "diagnostic_evidence_digest",
        "reviewer_model",
        "reviewer_prompt_digest",
        "provider_turns",
        "usage",
        "findings",
        "qualification_id",
    }
    if not is_json_object(document) or set(document) != keys:
        raise ValueError("semantic qualification document has invalid fields")
    raw_findings = document["findings"]
    raw_usage = document["usage"]
    if not isinstance(raw_findings, list) or not isinstance(raw_usage, list):
        raise ValueError("semantic qualification findings and usage must be arrays")
    findings = tuple(_finding_from_document(item) for item in raw_findings)
    usage: list[JSONObject | None] = []
    for item in raw_usage:
        if item is not None and not is_json_object(item):
            raise ValueError("semantic qualification usage item must be an object or null")
        usage.append(cast(JSONObject | None, item))
    result = SemanticQualification(
        cast(str, document["format"]),
        cast(str, document["actor_project_digest"]),
        cast(str, document["builder_projection_digest"]),
        cast(str, document["review_input_digest"]),
        cast(str, document["diagnostic_evidence_digest"]),
        cast(str, document["reviewer_model"]),
        cast(str, document["reviewer_prompt_digest"]),
        cast(int, document["provider_turns"]),
        tuple(usage),
        findings,
    )
    expected_verdict = "passed" if result.passed else "failed"
    if document["verdict"] != expected_verdict:
        raise ValueError("semantic qualification verdict differs from its findings")
    if document["qualification_id"] != result.qualification_id:
        raise ValueError("semantic qualification identity mismatch")
    return result


def make_qualified_conformance_evidence(
    physical_evidence: JSONObject,
    *,
    projection: BuilderProjection,
    tool_specs: tuple[ToolSpec, ...],
    diagnostic_evidence: tuple[JSONObject, ...],
    qualification: SemanticQualification,
) -> JSONObject:
    """Bind an accepted semantic review to exact physical conformance evidence."""

    if physical_evidence.get("format") != "environment-conformance-evidence/3":
        raise ValueError("semantic qualification requires physical conformance evidence/3")
    actor_digest = physical_evidence.get("actor_project_digest")
    if not isinstance(actor_digest, str):
        raise ValueError("physical conformance evidence lacks actor_project_digest")
    validate_semantic_qualification_binding(
        projection,
        actor_project_digest=actor_digest,
        tool_specs=tool_specs,
        diagnostic_evidence=diagnostic_evidence,
        qualification=qualification,
    )
    document = _json_object_copy(physical_evidence)
    document["format"] = QUALIFIED_CONFORMANCE_EVIDENCE_FORMAT
    document["builder_projection"] = cast(JSONValue, projection.to_document())
    document["semantic_qualification"] = qualification.to_document()
    qualified_semantic_evidence_from_document(document)
    return document


def qualified_semantic_evidence_from_document(document: Any) -> QualifiedSemanticEvidence:
    keys = {
        "format",
        "actor_project_digest",
        "builder_checks",
        "host_checks",
        "builder_projection",
        "semantic_qualification",
    }
    if not is_json_object(document) or set(document) != keys:
        raise ValueError("qualified conformance evidence has invalid fields")
    if document["format"] != QUALIFIED_CONFORMANCE_EVIDENCE_FORMAT:
        raise ValueError(
            f"qualified conformance evidence format must be "
            f"{QUALIFIED_CONFORMANCE_EVIDENCE_FORMAT!r}"
        )
    actor_digest = document["actor_project_digest"]
    if not isinstance(actor_digest, str):
        raise ValueError("qualified conformance actor_project_digest is invalid")
    projection = _projection_from_document(document["builder_projection"])
    host_checks = document["host_checks"]
    if not is_json_object(host_checks):
        raise ValueError("qualified conformance host_checks must be an object")
    raw_tools = host_checks.get("public_tool_specs")
    raw_evidence = host_checks.get("diagnostic_evidence")
    if not isinstance(raw_tools, list) or not isinstance(raw_evidence, list):
        raise ValueError("qualified conformance lacks public tools or diagnostic evidence")
    if any(not is_json_object(item) for item in raw_tools):
        raise ValueError("qualified conformance public tools are invalid")
    if any(not is_json_object(item) for item in raw_evidence):
        raise ValueError("qualified conformance diagnostic evidence is invalid")
    try:
        catalog = validate_tool_catalog(
            tuple(cast(ToolSpec, item) for item in raw_tools),
            role="qualified conformance tools",
        )
    except Exception as exc:
        raise ValueError(f"qualified conformance public tools are invalid: {exc}") from exc
    tool_specs = tuple(catalog.values())
    diagnostic_evidence = tuple(cast(JSONObject, item) for item in raw_evidence)
    qualification = semantic_qualification_from_document(document["semantic_qualification"])
    validate_semantic_qualification_binding(
        projection,
        actor_project_digest=actor_digest,
        tool_specs=tool_specs,
        diagnostic_evidence=diagnostic_evidence,
        qualification=qualification,
    )
    return QualifiedSemanticEvidence(
        projection,
        tool_specs,
        diagnostic_evidence,
        qualification,
    )


def validate_semantic_qualification_binding(
    projection: BuilderProjection,
    *,
    actor_project_digest: str,
    tool_specs: tuple[ToolSpec, ...],
    diagnostic_evidence: tuple[JSONObject, ...],
    qualification: SemanticQualification,
) -> None:
    if not qualification.passed:
        raise ValueError("semantic qualification did not satisfy every Requirement")
    normalized_tools = _normalized_tools(tool_specs)
    review_inputs = tuple(
        _review_input(
            projection,
            normalized_tools,
            diagnostic_evidence,
            requirement_ids=group,
        )
        for group in _requirement_groups(projection)
    )
    expected = {
        "actor_project_digest": actor_project_digest,
        "builder_projection_digest": sha256_hex(canonical_bytes(projection.to_document())),
        "review_input_digest": sha256_hex(canonical_bytes(list(review_inputs))),
        "diagnostic_evidence_digest": sha256_hex(canonical_bytes(list(diagnostic_evidence))),
        "reviewer_prompt_digest": sha256_hex(_PROMPT.encode("utf-8")),
    }
    for field, value in expected.items():
        if getattr(qualification, field) != value:
            raise ValueError(f"semantic qualification {field} binding mismatch")
    requirement_ids = _requirement_ids(projection)
    actual_ids = tuple(item.requirement_id for item in qualification.findings)
    if actual_ids != requirement_ids:
        raise ValueError("semantic qualification Requirement coverage mismatch")
    valid_refs = set(_evidence_refs(diagnostic_evidence))
    unknown = sorted(
        {reference for finding in qualification.findings for reference in finding.evidence_refs}
        - valid_refs
    )
    if unknown:
        raise ValueError(f"semantic qualification cites unknown evidence_refs {unknown}")


def _normalized_tools(tool_specs: tuple[ToolSpec, ...]) -> tuple[ToolSpec, ...]:
    try:
        return tuple(validate_tool_catalog(tool_specs, role="semantic review tools").values())
    except Exception as exc:
        raise ValueError(f"semantic review ToolSpecs are invalid: {exc}") from exc


def _review_input(
    projection: BuilderProjection,
    tool_specs: tuple[ToolSpec, ...],
    diagnostic_evidence: tuple[JSONObject, ...],
    *,
    requirement_ids: tuple[str, ...] | None = None,
) -> JSONObject:
    document = projection.to_document()
    selected = set(requirement_ids or _requirement_ids(projection))
    return {
        "frozen_need": cast(JSONValue, document["frozen_need"]),
        "selected_world": cast(JSONValue, document["selected_world"]),
        "requirements": cast(
            JSONValue,
            [item for item in document["requirements"] if item.get("id") in selected],
        ),
        "initial_world_relations": cast(
            JSONValue,
            [item for item in document["initial_world_relations"] if item.get("id") in selected],
        ),
        "public_tool_specs": cast(JSONValue, [dict(item) for item in tool_specs]),
        "evidence_contract": {
            "state_changes": "complete Host-derived JSON leaf differences",
            "reopen_matches_after": "exact canonical state equality after process reopen",
            "changed_from_pre_reset": "the reset replaced the immediately preceding state",
            "reset_restored_initial": "exact canonical equality with the scenario initial state",
        },
        "host_executed_evidence": _review_evidence_projection(diagnostic_evidence),
    }


def _review_evidence_projection(evidence: tuple[JSONObject, ...]) -> JSONObject:
    snapshots: dict[str, JSONValue] = {}
    scenarios: list[JSONValue] = []
    for scenario in evidence:
        scenario_id = scenario.get("scenario_id")
        reset = scenario.get("reset")
        steps = scenario.get("steps")
        lifecycle = scenario.get("lifecycle", [])
        if (
            not isinstance(scenario_id, str)
            or not is_json_object(reset)
            or not isinstance(steps, list)
            or not isinstance(lifecycle, list)
        ):
            raise ValueError("diagnostic evidence cannot be projected for semantic review")
        reset_document = cast(JSONObject, reset)
        initial_state = reset_document.get("initial_state")
        initial_digest = sha256_hex(canonical_bytes(initial_state))
        snapshots.setdefault(initial_digest, initial_state)
        projected_steps: list[JSONValue] = []
        for raw_step in steps:
            if not is_json_object(raw_step):
                raise ValueError("diagnostic step evidence must be an object")
            step = cast(JSONObject, raw_step)
            before = step.get("before_state")
            after = step.get("after_state")
            step_projection: JSONObject = {
                "evidence_ref": step.get("evidence_ref"),
                "tool": step.get("tool"),
                "arguments": step.get("arguments"),
                "observation": step.get("observation"),
                "before_digest": sha256_hex(canonical_bytes(before)),
                "after_digest": sha256_hex(canonical_bytes(after)),
                "state_changed": canonical_bytes(before) != canonical_bytes(after),
                "state_changes": cast(JSONValue, json_leaf_changes(before, after)),
            }
            if "state_after_reopen" in step:
                reopened = step["state_after_reopen"]
                step_projection["reopen_matches_after"] = canonical_bytes(
                    reopened
                ) == canonical_bytes(after)
                step_projection["reopened_state_digest"] = sha256_hex(canonical_bytes(reopened))
            projected_steps.append(step_projection)
        projected_lifecycle: list[JSONValue] = []
        for raw_item in lifecycle:
            if not is_json_object(raw_item):
                raise ValueError("diagnostic lifecycle evidence must be an object")
            item = cast(JSONObject, raw_item)
            before = item.get("before_state")
            after = item.get("after_state")
            lifecycle_projection: JSONObject = {
                "evidence_ref": item.get("evidence_ref"),
                "operation": item.get("operation"),
                "before_digest": sha256_hex(canonical_bytes(before)),
                "after_digest": sha256_hex(canonical_bytes(after)),
                "state_changes": cast(JSONValue, json_leaf_changes(before, after)),
            }
            if item.get("operation") == "reset_after_actions":
                lifecycle_projection["changed_from_pre_reset"] = canonical_bytes(
                    before
                ) != canonical_bytes(after)
                lifecycle_projection["reset_observation"] = item.get("reset_observation")
                lifecycle_projection["reset_restored_initial"] = canonical_bytes(
                    after
                ) == canonical_bytes(initial_state)
            else:
                lifecycle_projection["state_equal"] = canonical_bytes(before) == canonical_bytes(
                    after
                )
            projected_lifecycle.append(lifecycle_projection)
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "reset": {
                    "evidence_ref": reset_document.get("evidence_ref"),
                    "reset_observation": reset_document.get("reset_observation"),
                    "initial_state_digest": initial_digest,
                },
                "steps": projected_steps,
                "lifecycle": projected_lifecycle,
            }
        )
    return {
        "initial_state_snapshots": [
            {"digest": digest, "state": state} for digest, state in snapshots.items()
        ],
        "scenarios": scenarios,
    }


def _projection_from_document(document: Any) -> BuilderProjection:
    keys = {
        "frozen_need",
        "selected_world",
        "requirements",
        "initial_world_relations",
        "cited_evidence",
    }
    if not is_json_object(document) or set(document) != keys:
        raise ValueError("qualified BuilderProjection has invalid fields")
    frozen_need = document["frozen_need"]
    selected_world = document["selected_world"]
    requirements = document["requirements"]
    initial_world = document["initial_world_relations"]
    cited = document["cited_evidence"]
    if not is_json_object(frozen_need) or not is_json_object(selected_world):
        raise ValueError("qualified BuilderProjection roots must be objects")
    for value, role in (
        (requirements, "requirements"),
        (initial_world, "initial_world_relations"),
        (cited, "cited_evidence"),
    ):
        if not isinstance(value, list) or any(not is_json_object(item) for item in value):
            raise ValueError(f"qualified BuilderProjection {role} must be an object array")
    return BuilderProjection(
        cast(JSONObject, frozen_need),
        cast(JSONObject, selected_world),
        tuple(cast(list[Mapping[str, Any]], requirements)),
        tuple(cast(list[Mapping[str, Any]], initial_world)),
        tuple(cast(list[Mapping[str, Any]], cited)),
    )


def _json_object_copy(value: JSONObject) -> JSONObject:
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _requirement_ids(projection: BuilderProjection) -> tuple[str, ...]:
    document = projection.to_document()
    raw = [*document["requirements"], *document["initial_world_relations"]]
    ids = tuple(item.get("id") for item in raw if isinstance(item, dict))
    if (
        not ids
        or len(ids) != len(raw)
        or any(not isinstance(item, str) or not item for item in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("BuilderProjection must contain unique non-empty Requirement IDs")
    return cast(tuple[str, ...], ids)


def _requirement_groups(projection: BuilderProjection) -> tuple[tuple[str, ...], ...]:
    document = projection.to_document()
    buckets: dict[str, list[str]] = {}
    for item in document["requirements"]:
        requirement_id = item.get("id")
        kind = item.get("kind")
        if isinstance(requirement_id, str) and isinstance(kind, str):
            buckets.setdefault(kind, []).append(requirement_id)
    for item in document["initial_world_relations"]:
        requirement_id = item.get("id")
        if isinstance(requirement_id, str):
            buckets.setdefault("initial_world", []).append(requirement_id)
    groups = tuple(
        tuple(ids[offset : offset + 3])
        for ids in buckets.values()
        for offset in range(0, len(ids), 3)
    )
    flattened = tuple(item for group in groups for item in group)
    if set(flattened) != set(_requirement_ids(projection)) or len(flattened) != len(set(flattened)):
        raise ValueError("BuilderProjection Requirement grouping is incomplete")
    return groups


def _evidence_refs(evidence: tuple[JSONObject, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for scenario in evidence:
        reset = scenario.get("reset")
        steps = scenario.get("steps")
        lifecycle = scenario.get("lifecycle", [])
        if (
            not is_json_object(reset)
            or not isinstance(steps, list)
            or not isinstance(lifecycle, list)
        ):
            raise ValueError("diagnostic evidence scenario has invalid reset/steps/lifecycle")
        candidates = [reset, *steps, *lifecycle]
        for item in candidates:
            if not is_json_object(item):
                raise ValueError("diagnostic evidence item lacks a Host evidence_ref")
            item_document = cast(JSONObject, item)
            if not isinstance(item_document.get("evidence_ref"), str):
                raise ValueError("diagnostic evidence item lacks a Host evidence_ref")
            refs.append(cast(str, item_document["evidence_ref"]))
    if not refs or len(refs) != len(set(refs)):
        raise ValueError("diagnostic evidence refs must be non-empty and unique")
    return tuple(refs)


def _output_schema(
    requirement_ids: tuple[str, ...],
    evidence_refs: tuple[str, ...],
) -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "minItems": len(requirement_ids),
                "maxItems": len(requirement_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string", "enum": list(requirement_ids)},
                        "verdict": {
                            "type": "string",
                            "enum": ["satisfied", "not_satisfied"],
                        },
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(evidence_refs)},
                        },
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["requirement_id", "verdict", "evidence_refs", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def _parse_findings(
    output_text: str,
    *,
    requirement_ids: tuple[str, ...],
    evidence_refs: tuple[str, ...],
) -> tuple[SemanticFinding, ...]:
    try:
        document = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"semantic review output is not JSON: {exc}") from exc
    if not is_json_object(document) or set(document) != {"findings"}:
        raise ValueError("semantic review output must contain exactly findings")
    raw = document["findings"]
    if not isinstance(raw, list):
        raise ValueError("semantic review findings must be an array")
    findings = tuple(_finding_from_document(item) for item in raw)
    actual_ids = tuple(item.requirement_id for item in findings)
    if actual_ids != requirement_ids:
        raise ValueError(
            f"semantic review Requirement coverage mismatch: expected {list(requirement_ids)}, "
            f"got {list(actual_ids)}"
        )
    valid_refs = set(evidence_refs)
    unknown = sorted(
        {reference for finding in findings for reference in finding.evidence_refs} - valid_refs
    )
    if unknown:
        raise ValueError(f"semantic review cites unknown evidence_refs {unknown}")
    return findings


def _finding_from_document(document: Any) -> SemanticFinding:
    keys = {"requirement_id", "verdict", "evidence_refs", "reason"}
    if not is_json_object(document) or set(document) != keys:
        raise ValueError("semantic finding has invalid fields")
    refs = document["evidence_refs"]
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise ValueError("semantic finding evidence_refs must be a string array")
    return SemanticFinding(
        cast(str, document["requirement_id"]),
        cast(SemanticVerdict, document["verdict"]),
        tuple(refs),
        cast(str, document["reason"]),
    )


def _default_client_factory(*, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient:
    return cast(
        _ResponsesClient,
        OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=_PROVIDER_TURN_TIMEOUT_SECONDS,
        ),
    )


def _provider_turn(
    client: _ResponsesClient,
    *,
    route: AgentRoute,
    history: list[Any],
    output_schema: JSONObject,
    credential: str | None,
) -> Any:
    try:
        return client.responses.create(
            model=route.model,
            instructions=_PROMPT,
            input=list(history),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "environment_semantic_review",
                    "schema": output_schema,
                    "strict": True,
                }
            },
            store=False,
        )
    except Exception as exc:
        raise SemanticQualificationFailure(
            "InfrastructureFailure",
            "semantic_review_provider_failed",
            "semantic review Responses request failed",
            original_code=type(exc).__name__,
            original_message=_safe_message(exc, credential),
        ) from exc


def _output_text(response: Any) -> str:
    value = _item(response, "output_text")
    if not isinstance(value, str) or not value.strip():
        raise SemanticQualificationFailure(
            "QualifierDefect",
            "semantic_review_output_missing",
            "semantic reviewer returned no structured output",
        )
    return value


def _usage(response: Any) -> JSONObject | None:
    value = _item(response, "usage")
    if value is None:
        return None
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        value = dump()
    if not is_json_object(value):
        raise SemanticQualificationFailure(
            "QualifierDefect",
            "semantic_review_usage_invalid",
            "semantic reviewer usage must be an object",
        )
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _item(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _safe_message(exc: Exception, credential: str | None) -> str:
    message = str(exc)
    return message.replace(credential, "<redacted>") if credential else message


def _digest(value: str, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"semantic qualification {role} must be a sha256 digest")


__all__ = [
    "QUALIFIED_CONFORMANCE_EVIDENCE_FORMAT",
    "SEMANTIC_QUALIFICATION_FORMAT",
    "QualifiedSemanticEvidence",
    "SemanticFinding",
    "SemanticQualification",
    "SemanticQualificationFailure",
    "make_qualified_conformance_evidence",
    "qualified_semantic_evidence_from_document",
    "review_environment_semantics",
    "semantic_qualification_from_document",
    "validate_semantic_qualification_binding",
]
