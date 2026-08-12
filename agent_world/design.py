"""Typed, bounded producer transactions for the Direct DesignGraph."""

from __future__ import annotations

import json
import math
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from agent_world.artifacts import ArtifactStore, safe_url
from agent_world.config import ConfigurationError, FoundrySettings, credential_from_environment
from agent_world.contracts import (
    ArtifactRef,
    AssuranceRecipe,
    CitationCatalog,
    CitationCatalogItem,
    CorrectionPacket,
    CurriculumFamily,
    CurriculumPlan,
    DesignContract,
    DifficultyDimension,
    DifficultyLevel,
    EffectDraft,
    EntityDeclaration,
    EnvironmentRequest,
    EvaluatorGoalBinding,
    EvidenceClaim,
    EvidenceGraph,
    ExecutableTaskContract,
    ExpectedOutputCategory,
    FieldDeclaration,
    OperationEvidence,
    PredicateDraft,
    ResearchPlan,
    RewardSpec,
    RuleDraft,
    SemanticBinding,
    SemanticCatalog,
    SharedToolContract,
    TaskRequirement,
    TerminalStatus,
    TerminationSpec,
    ToolCouplingPlan,
    ToolDraft,
    ToolSurface,
    VerificationRequirements,
    WorldArchitecture,
    WorldBoundary,
    WorldRuleSet,
    compile_difficulty_schema,
    digest_value,
    json_value,
)
from agent_world.graph import GraphRunner, NodeExecutionError
from agent_world.invocation import (
    CodexAgentBackend,
    DirectChatBackend,
    InvocationError,
    InvocationResult,
    _DirectFormatFailure,
)

_URL = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PENDING = ArtifactRef("pending", "pending", "sha256:" + "0" * 64, "artifacts/pending.json")


class DesignError(NodeExecutionError):
    def __init__(
        self,
        code: str,
        status: TerminalStatus = "rejected",
        retryable: bool = False,
        *,
        correctable: bool = True,
        path: str = "$",
        violated_condition: str = "output must satisfy the closed node contract",
        expected_category: ExpectedOutputCategory = "object",
    ) -> None:
        super().__init__(
            code,
            status,
            retryable,
            correction=(
                CorrectionPacket(code, path, violated_condition, expected_category)
                if correctable and status == "rejected" and not retryable
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DesignResult:
    design: DesignContract
    work_refs: tuple[ArtifactRef, ...]
    artifact_refs: tuple[ArtifactRef, ...]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _direct_feedback(correction: CorrectionPacket) -> str:
    context = (
        "Continue the same task with the original frozen input and complete output contract. "
        "The immediately preceding complete proposal was rejected for one safe framework-observed "
        f"issue: code {correction.code}; path {correction.path}; "
        f"condition {correction.violated_condition}; expected category "
        f"{correction.expected_category}. "
    )
    if correction.code == "direct_response_not_json":
        repair = (
            "Replace the entire immediately preceding answer with one parseable JSON object. "
            "Delete all prose, labels, Markdown fences, and second JSON values. "
            "Its first and last non-whitespace characters must be { and }. "
        )
    else:
        repair = (
            "The path identifies exactly one framework-observed occurrence. "
            "Change the response at that path to correct that occurrence, then inspect "
            "the complete immediately preceding proposal and correct every occurrence "
            "governed by the same condition and expected category. "
            "Do not treat this as evidence that the framework observed any other occurrence. "
        )
    return (
        context + repair + "Return one complete replacement as exactly one JSON "
        "object, not a patch, explanation, or Markdown. Before answering, self-check the whole "
        "replacement object against the complete output contract."
    )


def _text(value: object, code: str, limit: int = 500, *, path: str = "$") -> str:
    if not isinstance(value, str):
        raise DesignError(
            code,
            path=path,
            violated_condition="value must be a string",
            expected_category="string",
        )
    stripped = value.strip()
    if not stripped:
        raise DesignError(
            code,
            path=path,
            violated_condition="value must be nonempty after stripping",
            expected_category="string",
        )
    if len(stripped) > limit:
        raise DesignError(
            code,
            path=path,
            violated_condition=f"value must use at most {limit} code points",
            expected_category="string",
        )
    return stripped


def _object(value: object, keys: set[str], code: str, *, path: str = "$") -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DesignError(
            code,
            path=path,
            violated_condition=(
                "object must contain exactly these fields and no others: " + ", ".join(sorted(keys))
            ),
            expected_category="object",
        )
    return value


def _array(value: object, minimum: int, maximum: int, code: str, *, path: str = "$") -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise DesignError(
            code,
            path=path,
            violated_condition="array must use the declared cardinality",
            expected_category="array",
        )
    return value


def _json_scalar(value: object) -> bool:
    return value is None or (
        type(value) in {bool, int, float, str}
        and not (type(value) is float and not math.isfinite(value))
    )


def _model_value(value: Any) -> Any:
    """Project only compiled semantics, never framework artifact identities."""

    raw = json_value(value)
    if isinstance(raw, dict):
        return {
            key: _model_value(item)
            for key, item in raw.items()
            if key not in {"artifact", "work_refs"}
        }
    if isinstance(raw, list):
        return [_model_value(item) for item in raw]
    return raw


def _design_artifact_value(value: DesignContract) -> dict[str, Any]:
    """Persist the complete safe Design projection without evaluator-private labels."""

    def project(raw: Any) -> Any:
        if isinstance(raw, dict):
            return {
                {
                    "evaluator_goal_bindings": "goal_bindings",
                    "evaluator_goal_path": "goal_path",
                }.get(key, key): project(item)
                for key, item in raw.items()
            }
        if isinstance(raw, list):
            return [project(item) for item in raw]
        return raw

    return cast(dict[str, Any], project(json_value(replace(value, artifact=_PENDING))))


def _json_value(value: object) -> bool:
    return _json_scalar(value) or (
        isinstance(value, list) and len(value) <= 32 and all(_json_scalar(item) for item in value)
    )


def _source_urls(body: str) -> tuple[str, ...]:
    urls: list[str] = []
    for found in _URL.finditer(body):
        value = found.group(0).rstrip(".,;:)")
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
            or host == "localhost"
            or host.endswith(".local")
            or host.endswith("jina.ai")
        ):
            continue
        if value not in urls:
            urls.append(value)
        if len(urls) == 6:
            break
    return tuple(urls)


def _field(value: object, code: str, *, path: str) -> FieldDeclaration:
    raw = value if isinstance(value, dict) else {}
    if (
        not {"name", "category", "required"}
        <= set(raw)
        <= {"name", "category", "required", "values", "entity_ref"}
    ):
        raise DesignError(
            code,
            path=path,
            violated_condition="field must use the sparse declared keys",
            expected_category="object",
        )
    name = _text(raw["name"], code, 64, path=f"{path}.name")
    if (
        not _NAME.fullmatch(name)
        or raw["category"]
        not in {"text", "integer", "number", "boolean", "timestamp", "identifier", "enum", "list"}
        or type(raw["required"]) is not bool
    ):
        raise DesignError(
            code,
            path=path,
            violated_condition="field name, category, and required flag must be valid",
            expected_category="object",
        )
    finite = raw["category"] in {"enum", "list"}
    if ("values" in raw) != finite:
        raise DesignError(
            code,
            path=f"{path}.values",
            violated_condition="enum/list fields require nonempty values; scalars must omit them",
            expected_category="array",
        )
    values = _array(raw.get("values", []), 1, 16, code, path=f"{path}.values") if finite else []
    if any(not isinstance(item, str) or not item.strip() for item in values) or len(
        set(values)
    ) != len(values):
        raise DesignError(
            code,
            path=f"{path}.values",
            violated_condition="finite field domains must be unique text",
            expected_category="array",
        )
    entity_ref = raw.get("entity_ref")
    if "entity_ref" in raw and (not isinstance(entity_ref, str) or not _NAME.fullmatch(entity_ref)):
        raise DesignError(
            code,
            path=f"{path}.entity_ref",
            violated_condition="entity reference must name a declared entity",
            expected_category="string",
        )
    return FieldDeclaration(name, raw["category"], raw["required"], tuple(values), entity_ref)


def _rule_id(tool_index: int, section: str, ordinal: int) -> str:
    return f"tool:{tool_index}:{section}:{ordinal}"


def _local_rules_digest(
    tool_index: int,
    bindings: tuple[SemanticBinding, ...],
    preconditions: tuple[RuleDraft, ...],
    transitions: tuple[RuleDraft, ...],
    postconditions: tuple[RuleDraft, ...],
    errors: tuple[RuleDraft, ...],
    shared_contract_digest: str | None = None,
) -> str:
    return (
        "sha256:"
        + sha256(
            _canonical(
                {
                    "tool_index": tool_index,
                    "bindings": json_value(bindings),
                    "preconditions": json_value(preconditions),
                    "transitions": json_value(transitions),
                    "postconditions": json_value(postconditions),
                    "errors": json_value(errors),
                    "shared_contract_digest": shared_contract_digest,
                }
            )
        ).hexdigest()
    )


_RULE_DRAFT_SHAPE = 'RuleDraft={when[0..6] PredicateDraft={left_semantic_index:frozen SemanticCatalog index,operator:"eq"|"ne"|"lt"|"le"|"gt"|"ge"|"contains"|"not_contains"|"exists"|"not_exists",right:{kind:"literal",value:finite JSON scalar or finite JSON scalar list[0..32]}|{kind:"semantic_ref",semantic_index:frozen SemanticCatalog index};exists|not_exists=>literal null},effects[1..6] EffectDraft={target_semantic_index:frozen SemanticCatalog index,operation:"set"|"increment"|"decrement"|"add"|"remove"|"preserve"|"reject",value:finite JSON scalar or finite JSON scalar list[0..32]|{kind:"semantic_ref",semantic_index:frozen SemanticCatalog index};preserve|reject=>null},error_kind:null in non-error sections|[a-z][a-z0-9_]{0,63} in errors only (1..64 code points),rationale:stripped nonempty text<=300 code points,citation_indexes:0..8 unique frozen CitationCatalog indexes;[] when no CitationCatalog is supplied}'  # noqa: E501
_TASK_RULE_DRAFT_SHAPE = 'TaskRequirementRuleDraft={when[0..6] PredicateDraft={left_semantic_index:frozen SemanticCatalog index,operator:"eq"|"ne"|"lt"|"le"|"gt"|"ge"|"contains"|"not_contains"|"exists"|"not_exists",right:{kind:"literal",value:finite JSON scalar or finite JSON scalar list[0..32]}|{kind:"semantic_ref",semantic_index:frozen SemanticCatalog index};exists|not_exists=>literal null},effects[1..6] EffectDraft={target_semantic_index:frozen SemanticCatalog index,operation:"set"|"increment"|"decrement"|"add"|"remove"|"preserve"|"reject",value:finite JSON scalar or finite JSON scalar list[0..32]|{kind:"semantic_ref",semantic_index:frozen SemanticCatalog index};preserve|reject=>null},rationale:stripped nonempty text<=300 code points,citation_indexes:0..8 unique frozen CitationCatalog indexes}'  # noqa: E501
_TASK_RULE_SOURCE_FIELDS = {"when", "effects", "rationale", "citation_indexes"}


def _compile_rules(
    value: object,
    bindings: tuple[SemanticBinding, ...],
    citations: set[int],
    code: str,
    *,
    path: str,
    minimum: int,
    maximum: int,
    errors_only: bool | None = None,
) -> tuple[RuleDraft, ...]:
    result: list[RuleDraft] = []
    for number, raw_rule in enumerate(_array(value, minimum, maximum, code, path=path)):
        item_path = f"{path}[{number}]"
        raw = _object(
            raw_rule,
            {"when", "effects", "error_kind", "rationale", "citation_indexes"},
            code,
            path=item_path,
        )
        predicates: list[PredicateDraft] = []
        for predicate_number, raw_predicate in enumerate(
            _array(raw["when"], 0, 6, code, path=f"{item_path}.when")
        ):
            predicate_path = f"{item_path}.when[{predicate_number}]"
            predicate = _object(
                raw_predicate,
                {"left_semantic_index", "operator", "right"},
                code,
                path=predicate_path,
            )
            index = predicate["left_semantic_index"]
            if (
                type(index) is not int
                or not 1 <= index <= len(bindings)
                or predicate["operator"]
                not in {
                    "eq",
                    "ne",
                    "lt",
                    "le",
                    "gt",
                    "ge",
                    "contains",
                    "not_contains",
                    "exists",
                    "not_exists",
                }
            ):
                raise DesignError(
                    code,
                    path=predicate_path,
                    violated_condition="predicate must select a frozen binding and closed operator",
                    expected_category="object",
                )
            right = predicate["right"]
            valid_right = isinstance(right, dict) and (
                set(right) == {"kind", "value"}
                and right.get("kind") == "literal"
                and _json_value(right["value"])
                or (
                    set(right) == {"kind", "semantic_index"}
                    and right.get("kind") == "semantic_ref"
                    and type(right["semantic_index"]) is int
                    and 1 <= right["semantic_index"] <= len(bindings)
                )
            )
            if not valid_right:
                raise DesignError(
                    code,
                    path=f"{predicate_path}.right",
                    violated_condition=(
                        "right side must be a finite literal or frozen binding reference"
                    ),
                    expected_category="object",
                )
            if predicate["operator"] in {"exists", "not_exists"} and right != {
                "kind": "literal",
                "value": None,
            }:
                raise DesignError(
                    code,
                    path=f"{predicate_path}.right",
                    violated_condition="existence predicates require literal null",
                    expected_category="object",
                )
            predicates.append(PredicateDraft(index, cast(Any, predicate["operator"]), dict(right)))
        effects: list[EffectDraft] = []
        for effect_number, raw_effect in enumerate(
            _array(raw["effects"], 1, 6, code, path=f"{item_path}.effects")
        ):
            effect_path = f"{item_path}.effects[{effect_number}]"
            effect = _object(
                raw_effect, {"target_semantic_index", "operation", "value"}, code, path=effect_path
            )
            index, operation, effect_value = (
                effect["target_semantic_index"],
                effect["operation"],
                effect["value"],
            )
            if (
                type(index) is not int
                or not 1 <= index <= len(bindings)
                or operation
                not in {"set", "increment", "decrement", "add", "remove", "preserve", "reject"}
            ):
                raise DesignError(
                    code,
                    path=effect_path,
                    violated_condition="effect must select a frozen binding and closed operation",
                    expected_category="object",
                )
            if (
                isinstance(effect_value, dict)
                and set(effect_value) == {"kind", "semantic_index"}
                and effect_value.get("kind") == "semantic_ref"
            ):
                if type(effect_value["semantic_index"]) is not int or not 1 <= effect_value[
                    "semantic_index"
                ] <= len(bindings):
                    raise DesignError(
                        code,
                        path=f"{effect_path}.value",
                        violated_condition="semantic effect reference must be frozen",
                        expected_category="object",
                    )
            elif not _json_value(effect_value):
                raise DesignError(
                    code,
                    path=f"{effect_path}.value",
                    violated_condition=(
                        "effect value must be a direct JSON scalar (null, boolean, integer, finite "
                        "float, or string) or a scalar-list of at most 32 such scalars, not a "
                        '{kind:"literal",value:...} '
                        "wrapper; or exactly "
                        '{kind:"semantic_ref",semantic_index:<frozen one-based index>} object'
                    ),
                    expected_category="semantic_draft",
                )
            if operation in {"preserve", "reject"} and effect_value is not None:
                raise DesignError(
                    code,
                    path=f"{effect_path}.value",
                    violated_condition="preserve and reject require null values",
                    expected_category="semantic_draft",
                )
            effects.append(EffectDraft(index, cast(Any, operation), effect_value))
        error_kind = raw["error_kind"]
        if errors_only is True and (
            not isinstance(error_kind, str) or not _NAME.fullmatch(error_kind)
        ):
            raise DesignError(
                code,
                path=f"{item_path}.error_kind",
                violated_condition="error rules require a bounded error kind",
                expected_category="string",
            )
        if errors_only is False and error_kind is not None:
            raise DesignError(
                code,
                path=f"{item_path}.error_kind",
                violated_condition="non-error rules require null error_kind",
                expected_category="string",
            )
        cited = _array(raw["citation_indexes"], 0, 8, code, path=f"{item_path}.citation_indexes")
        if any(type(item) is not int or item not in citations for item in cited) or len(
            set(cited)
        ) != len(cited):
            raise DesignError(
                code,
                path=f"{item_path}.citation_indexes",
                violated_condition="citations must be unique frozen citation indexes",
                expected_category="array",
            )
        result.append(
            RuleDraft(
                tuple(predicates),
                tuple(effects),
                cast(Any, error_kind),
                _text(raw["rationale"], code, 300, path=f"{item_path}.rationale"),
                tuple(cited),
            )
        )
    return tuple(result)


def _compile_task_rules(
    value: object,
    bindings: tuple[SemanticBinding, ...],
    citations: set[int],
    *,
    path: str,
    minimum: int,
    maximum: int,
) -> tuple[RuleDraft, ...]:
    """Compile the TaskRequirement-only non-error source shape.

    The model cannot supply the framework-owned non-error value.  Source
    validation remains closed before an internal copy restores the generic
    compiler input expected by the committed RuleDraft contract.
    """

    internal_rules: list[dict[str, Any]] = []
    for number, source_rule in enumerate(
        _array(value, minimum, maximum, "task_requirement_invalid", path=path)
    ):
        source = _object(
            source_rule,
            _TASK_RULE_SOURCE_FIELDS,
            "task_requirement_invalid",
            path=f"{path}[{number}]",
        )
        internal_rules.append({**source, "error_kind": None})
    return _compile_rules(
        internal_rules,
        bindings,
        citations,
        "task_requirement_invalid",
        path=path,
        minimum=minimum,
        maximum=maximum,
        errors_only=False,
    )


def _catalog(architecture: WorldArchitecture) -> tuple[SemanticBinding, ...]:
    bindings: list[SemanticBinding] = []
    for tool in architecture.tools:
        for source, fields in (
            ("argument", tool.argument_fields),
            ("tool_result", tool.result_fields),
            ("pre_state", tool.result_fields),
            ("post_state", tool.result_fields),
        ):
            for field in fields:
                bindings.append(
                    SemanticBinding(
                        len(bindings) + 1,
                        cast(Any, source),
                        field.name,
                        (source, str(tool.tool_index), field.name),
                    )
                )
    return tuple(bindings)


def _catalog_categories(architecture: WorldArchitecture) -> tuple[str, ...]:
    return tuple(
        field.category
        for tool in architecture.tools
        for fields in (
            tool.argument_fields,
            tool.result_fields,
            tool.result_fields,
            tool.result_fields,
        )
        for field in fields
    )


class DesignExecutor:
    def __init__(
        self, settings: FoundrySettings, direct: DirectChatBackend, agent: CodexAgentBackend
    ) -> None:
        self.settings, self.direct, self.agent = settings, direct, agent

    def _agent_json(
        self,
        work: str,
        skill: str,
        workspace: Path,
        instruction: str,
        correction: CorrectionPacket | None = None,
    ) -> InvocationResult:
        if correction is not None:
            instruction += (
                "\nAuthorized correction packet: " + _canonical(json_value(correction)).decode()
            )
        try:
            return self.agent.invoke_json(
                work=work, skill_name=skill, workspace=workspace, instruction=instruction
            )
        except InvocationError as exc:
            raise DesignError(
                exc.failure.code, exc.failure.status, exc.failure.retryable, correctable=False
            ) from exc

    def _direct_json(
        self,
        node: str,
        projection: dict[str, Any],
        shape: str,
        correction: CorrectionPacket | None = None,
        *,
        previous_output: str | None = None,
    ) -> InvocationResult | _DirectFormatFailure:
        system = (
            f"You are Direct semantic node {node}. You have no tools, Skills, workspace, "
            "or release authority. Return exactly one JSON object matching the disclosed shape."
        )
        if correction is not None and previous_output is None:
            raise DesignError("direct_feedback_unavailable", correctable=False)
        user = _canonical(
            {
                "node": node,
                "input": projection,
                "output_shape": shape,
                "correction": None,
            }
        ).decode()
        try:
            return self.direct.invoke_json(
                system=system,
                user=user,
                previous_assistant=previous_output if correction is not None else None,
                feedback=_direct_feedback(correction) if correction is not None else None,
            )
        except InvocationError as exc:
            raise DesignError(
                exc.failure.code, exc.failure.status, exc.failure.retryable, correctable=False
            ) from exc

    @staticmethod
    def _model_evidence(
        category: Literal["direct_llm", "agent"],
        node: str,
        result: InvocationResult | _DirectFormatFailure,
    ) -> tuple[OperationEvidence, ...]:
        return (
            OperationEvidence(
                category,
                node,
                result.route_model,
                result.usage,
                result.skill_digest if isinstance(result, InvocationResult) else None,
            ),
        )

    def _direct_commit(
        self,
        node: str,
        projection: dict[str, Any],
        shape: str,
        kind: str,
        compiler: Callable[[dict[str, Any]], Any],
        inputs: dict[str, tuple[ArtifactRef, ...]],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        *,
        shard_key: str | None = None,
    ) -> tuple[Any, ArtifactRef, ArtifactRef]:
        visible_projection = _model_value(projection)
        previous_output: str | None = None

        def operation(
            correction: CorrectionPacket | None,
        ) -> InvocationResult | _DirectFormatFailure:
            nonlocal previous_output
            result = self._direct_json(
                node,
                visible_projection,
                shape,
                correction,
                previous_output=previous_output,
            )
            if isinstance(result, _DirectFormatFailure):
                previous_output = result.raw_content
            else:
                previous_output = _canonical(result.value).decode()
            return result

        def compile(result: InvocationResult | _DirectFormatFailure) -> Any:
            if isinstance(result, _DirectFormatFailure):
                raise DesignError(
                    "direct_response_not_json",
                    path="$",
                    violated_condition=result.condition.violated_condition(),
                    expected_category="object",
                )
            if not isinstance(result.value, dict):
                raise DesignError(
                    f"{node}_invalid",
                    path="$",
                    violated_condition="proposal must be a JSON object",
                    expected_category="object",
                )
            return compiler(result.value)

        node_result = graph.execute(
            store,
            run_id,
            node,
            inputs,
            kind,
            operation,
            compile,
            {
                "effective_projection": visible_projection,
                "output_shape": shape,
                "prompt_identity": graph.node(node).prompt_id,
            },
            artifact_projection=json_value,
            operation_evidence=lambda result: self._model_evidence("direct_llm", node, result),
            shard_key=shard_key,
        )
        return node_result.value, node_result.artifact, node_result.work

    def _research_plan(
        self,
        request: EnvironmentRequest,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        request_ref: ArtifactRef,
    ) -> tuple[ResearchPlan, ArtifactRef, ArtifactRef]:
        def operation(correction: CorrectionPacket | None) -> InvocationResult:
            with tempfile.TemporaryDirectory(prefix="foundry-research-plan-") as temporary:
                workspace = Path(temporary)
                (workspace / "request.json").write_bytes(_canonical({"need": request.need}))
                return self._agent_json(
                    "research_plan",
                    "research-world-evidence",
                    workspace,
                    "Read request.json. Return ResearchPlanDraft exactly: "
                    "{queries:[text] (1..6),questions_to_resolve:[text] (1..12)}.",
                    correction,
                )

        def compile(result: InvocationResult) -> ResearchPlan:
            value = _object(
                result.value,
                {"queries", "questions_to_resolve"},
                "research_plan_invalid",
            )
            queries = tuple(
                _text(item, "research_plan_invalid", 240, path=f"$.queries[{index}]")
                for index, item in enumerate(
                    _array(value["queries"], 1, 6, "research_plan_invalid", path="$.queries")
                )
            )
            questions = tuple(
                _text(item, "research_plan_invalid", 240, path=f"$.questions_to_resolve[{index}]")
                for index, item in enumerate(
                    _array(
                        value["questions_to_resolve"],
                        1,
                        12,
                        "research_plan_invalid",
                        path="$.questions_to_resolve",
                    )
                )
            )
            return ResearchPlan(queries, questions, _PENDING)

        node = graph.execute(
            store,
            run_id,
            "research_plan",
            {"request": (request_ref,)},
            "design.research_plan",
            operation,
            compile,
            {"request_digest": request.need_digest, "output_shape": "ResearchPlanDraft@1"},
            artifact_projection=lambda value: json_value(replace(value, artifact=_PENDING)),
            operation_evidence=lambda result: self._model_evidence(
                "agent", "research_plan", result
            ),
        )
        return replace(node.value, artifact=node.artifact), node.artifact, node.work

    def _http_text(self, url: str, *, key: str | None, stage: str) -> str:
        headers = {
            "Accept": "text/plain,text/markdown,text/html",
            "User-Agent": "agent-world-foundry/0.3",
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            with urlopen(Request(url, headers=headers), timeout=120) as response:  # noqa: S310
                body = response.read()
        except HTTPError as exc:
            raise DesignError(
                f"{stage}_http_failure", "error", exc.code in {408, 429, 500, 502, 503, 504}
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DesignError(f"{stage}_network_failure", "error", True) from exc
        if not (text := body.decode("utf-8", errors="replace").strip()):
            raise DesignError(f"{stage}_empty")
        return text

    def _research_acquire(
        self,
        plan: ResearchPlan,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        plan_ref: ArtifactRef,
    ) -> tuple[tuple[dict[str, Any], ...], ArtifactRef, ArtifactRef]:
        try:
            key = credential_from_environment(self.settings.research.api_key_env)
        except ConfigurationError as exc:
            raise DesignError(str(exc), "needs_human") from exc

        def operation(
            _: CorrectionPacket | None,
        ) -> tuple[list[dict[str, Any]], list[str], tuple[OperationEvidence, ...]]:
            commitments: list[dict[str, Any]] = []
            texts: list[str] = []
            operations: list[OperationEvidence] = []
            for query in plan.queries:
                search = self._http_text(
                    f"{self.settings.research.search_url}/{quote(query, safe='')}",
                    key=key,
                    stage="research_search",
                )
                operations.append(OperationEvidence("search", "research_acquire", None, None))
                for url in _source_urls(search):
                    text = self._http_text(
                        f"{self.settings.research.reader_url}/{url}",
                        key=key,
                        stage="research_fetch",
                    )
                    encoded = text.encode()
                    commitments.append(
                        {
                            "url": safe_url(url),
                            "content_digest": "sha256:" + sha256(encoded).hexdigest(),
                            "content_length": len(encoded),
                        }
                    )
                    texts.append(text[:10000])
                    operations.extend(
                        (
                            OperationEvidence("fetch", "research_acquire", None, None),
                            OperationEvidence("extract", "research_acquire", None, None),
                        )
                    )
                    if len(commitments) == 6:
                        break
                if len(commitments) == 6:
                    break
            if not commitments:
                raise DesignError("research_no_provenance_sources")
            return commitments, texts, tuple(operations)

        node = graph.execute(
            store,
            run_id,
            "research_acquire",
            {"research_plan": (plan_ref,)},
            "design.research_acquire",
            operation,
            lambda value: value,
            {"research_plan": plan_ref.digest, "output_shape": "ResearchAcquisition@1"},
            artifact_projection=lambda value: {
                "sources": value[0],
                "citation_catalog": [
                    {"index": index, "url": item["url"]} for index, item in enumerate(value[0], 1)
                ],
            },
            operation_evidence=lambda value: value[2],
        )
        return (
            tuple(
                {**commitment, "text": node.value[1][index]}
                for index, commitment in enumerate(node.value[0])
            ),
            node.artifact,
            node.work,
        )

    def _research_synthesis(
        self,
        request: EnvironmentRequest,
        plan: ResearchPlan,
        sources: tuple[dict[str, Any], ...],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        request_ref: ArtifactRef,
        plan_ref: ArtifactRef,
        acquire_ref: ArtifactRef,
    ) -> tuple[EvidenceGraph, ArtifactRef, ArtifactRef]:
        def operation(correction: CorrectionPacket | None) -> InvocationResult:
            with tempfile.TemporaryDirectory(prefix="foundry-research-synthesis-") as temporary:
                workspace = Path(temporary)
                (workspace / "evidence.json").write_bytes(
                    _canonical(
                        {
                            "request": request.need,
                            "questions": plan.questions_to_resolve,
                            "citations": [
                                {"index": index, "url": source["url"], "text": source["text"]}
                                for index, source in enumerate(sources, 1)
                            ],
                        }
                    )
                )
                return self._agent_json(
                    "research_synthesis",
                    "research-world-evidence",
                    workspace,
                    "Read evidence.json. Return ResearchSynthesisDraft exactly: claims/conflicts "
                    "arrays of {statement,kind:observed|bounded_inference,citation_indexes}, "
                    "and gaps:[text]. Claims 1..32 and every claim citation is one-based "
                    "from the staged catalog.",
                    correction,
                )

        def claim(raw: object, path: str) -> EvidenceClaim:
            value = _object(
                raw,
                {"statement", "kind", "citation_indexes"},
                "research_synthesis_invalid",
                path=path,
            )
            indexes = _array(
                value["citation_indexes"],
                1,
                6,
                "research_synthesis_invalid",
                path=f"{path}.citation_indexes",
            )
            if (
                value["kind"] not in {"observed", "bounded_inference"}
                or len(set(indexes)) != len(indexes)
                or any(type(item) is not int or not 1 <= item <= len(sources) for item in indexes)
            ):
                raise DesignError(
                    "research_synthesis_invalid",
                    path=path,
                    violated_condition="claim kind and citations must be from the frozen catalog",
                    expected_category="object",
                )
            return EvidenceClaim(
                _text(
                    value["statement"], "research_synthesis_invalid", 500, path=f"{path}.statement"
                ),
                cast(Any, value["kind"]),
                tuple(indexes),
            )

        def compile(result: InvocationResult) -> EvidenceGraph:
            value = _object(
                result.value, {"claims", "conflicts", "gaps"}, "research_synthesis_invalid"
            )
            claims = tuple(
                claim(item, f"$.claims[{index}]")
                for index, item in enumerate(
                    _array(value["claims"], 1, 32, "research_synthesis_invalid", path="$.claims")
                )
            )
            conflicts = tuple(
                claim(item, f"$.conflicts[{index}]")
                for index, item in enumerate(
                    _array(
                        value["conflicts"], 0, 16, "research_synthesis_invalid", path="$.conflicts"
                    )
                )
            )
            gaps = tuple(
                _text(item, "research_synthesis_invalid", 300, path=f"$.gaps[{index}]")
                for index, item in enumerate(
                    _array(value["gaps"], 0, 16, "research_synthesis_invalid", path="$.gaps")
                )
            )
            catalog = CitationCatalog(
                tuple(
                    CitationCatalogItem(
                        index, f"source-{index}", source["url"], source["text"][:500]
                    )
                    for index, source in enumerate(sources, 1)
                )
            )
            return EvidenceGraph(claims, conflicts, gaps, catalog, _PENDING)

        node = graph.execute(
            store,
            run_id,
            "research_synthesis",
            {
                "request": (request_ref,),
                "research_plan": (plan_ref,),
                "sources": (acquire_ref,),
                "citations": (acquire_ref,),
            },
            "design.evidence_graph",
            operation,
            compile,
            {
                "request_digest": request.need_digest,
                "questions_to_resolve": plan.questions_to_resolve,
                "citation_catalog": [
                    {
                        "index": index,
                        "url": source["url"],
                        "content_digest": source["content_digest"],
                    }
                    for index, source in enumerate(sources, 1)
                ],
                "output_shape": "ResearchSynthesisDraft@1",
            },
            artifact_projection=lambda value: json_value(replace(value, artifact=_PENDING)),
            operation_evidence=lambda result: self._model_evidence(
                "agent", "research_synthesis", result
            ),
        )
        return replace(node.value, artifact=node.artifact), node.artifact, node.work

    def _direct_architecture(
        self,
        request: EnvironmentRequest,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        request_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[WorldArchitecture, ArtifactRef, ArtifactRef]:
        citations = {item.index for item in evidence.catalog.items}

        def compile(value: dict[str, Any]) -> WorldArchitecture:
            raw = _object(
                value,
                {"boundary", "entities", "tools", "known_divergences"},
                "world_architecture_invalid",
            )

            def field_array(
                value: object, minimum: int, *, path: str
            ) -> tuple[FieldDeclaration, ...]:
                fields = tuple(
                    _field(
                        field,
                        "world_architecture_invalid",
                        path=f"{path}[{field_index}]",
                    )
                    for field_index, field in enumerate(
                        _array(value, minimum, 24, "world_architecture_invalid", path=path)
                    )
                )
                if len({field.name for field in fields}) != len(fields):
                    raise DesignError(
                        "world_architecture_invalid",
                        path=path,
                        violated_condition="field names must be unique within their owner",
                        expected_category="array",
                    )
                return fields

            boundary_value = _object(
                raw["boundary"],
                {"name", "purpose", "system_of_record", "authority", "actors"},
                "world_architecture_invalid",
                path="$.boundary",
            )
            actors = tuple(
                _text(item, "world_architecture_invalid", 80, path=f"$.boundary.actors[{index}]")
                for index, item in enumerate(
                    _array(
                        boundary_value["actors"],
                        1,
                        8,
                        "world_architecture_invalid",
                        path="$.boundary.actors",
                    )
                )
            )
            if len(set(actors)) != len(actors):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.boundary.actors",
                    violated_condition="actors must be unique",
                    expected_category="array",
                )
            boundary_name = _text(
                boundary_value["name"],
                "world_architecture_invalid",
                160,
                path="$.boundary.name",
            )
            purpose = boundary_value["purpose"]
            boundary_purpose = purpose.strip() if isinstance(purpose, str) else ""
            if not boundary_purpose or len(boundary_purpose) > 4096:
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.boundary.purpose",
                    violated_condition=(
                        "value must be text with nonempty content after stripping"
                        if not boundary_purpose
                        else "stripped value must contain at most 4096 Unicode code points"
                    ),
                    expected_category="string",
                )
            system_of_record = _text(
                boundary_value["system_of_record"],
                "world_architecture_invalid",
                160,
                path="$.boundary.system_of_record",
            )
            authority = _text(
                boundary_value["authority"],
                "world_architecture_invalid",
                160,
                path="$.boundary.authority",
            )
            boundary = WorldBoundary(
                boundary_name, boundary_purpose, system_of_record, authority, actors
            )
            entities: list[EntityDeclaration] = []
            for index, item in enumerate(
                _array(raw["entities"], 1, 16, "world_architecture_invalid", path="$.entities")
            ):
                entity = _object(
                    item,
                    {"name", "purpose", "fields"},
                    "world_architecture_invalid",
                    path=f"$.entities[{index}]",
                )
                fields = field_array(entity["fields"], 1, path=f"$.entities[{index}].fields")
                entities.append(
                    EntityDeclaration(
                        _text(
                            entity["name"],
                            "world_architecture_invalid",
                            64,
                            path=f"$.entities[{index}].name",
                        ),
                        _text(
                            entity["purpose"],
                            "world_architecture_invalid",
                            300,
                            path=f"$.entities[{index}].purpose",
                        ),
                        fields,
                    )
                )
            entity_names = {entity.name for entity in entities}
            if len(entity_names) != len(entities) or any(
                field.entity_ref and field.entity_ref not in entity_names
                for entity in entities
                for field in entity.fields
            ):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.entities",
                    violated_condition="entity names and references must be closed",
                    expected_category="array",
                )
            tools: list[ToolSurface] = []
            for index, item in enumerate(
                _array(raw["tools"], 1, 8, "world_architecture_invalid", path="$.tools")
            ):
                tool = _object(
                    item,
                    {"name", "purpose", "actor_names", "argument_fields", "result_fields"},
                    "world_architecture_invalid",
                    path=f"$.tools[{index}]",
                )
                actor_names = tuple(
                    _array(
                        tool["actor_names"],
                        1,
                        len(actors),
                        "world_architecture_invalid",
                        path=f"$.tools[{index}].actor_names",
                    )
                )
                if any(
                    not isinstance(actor, str) or actor not in actors for actor in actor_names
                ) or len(set(actor_names)) != len(actor_names):
                    raise DesignError(
                        "world_architecture_invalid",
                        path=f"$.tools[{index}].actor_names",
                        violated_condition="tool actors must be unique declared names",
                        expected_category="array",
                    )
                actor_indexes = tuple(actors.index(actor) + 1 for actor in actor_names)
                tools.append(
                    ToolSurface(
                        index + 1,
                        _text(
                            tool["name"],
                            "world_architecture_invalid",
                            64,
                            path=f"$.tools[{index}].name",
                        ),
                        _text(
                            tool["purpose"],
                            "world_architecture_invalid",
                            300,
                            path=f"$.tools[{index}].purpose",
                        ),
                        actor_indexes,
                        field_array(
                            tool["argument_fields"],
                            0,
                            path=f"$.tools[{index}].argument_fields",
                        ),
                        field_array(
                            tool["result_fields"],
                            1,
                            path=f"$.tools[{index}].result_fields",
                        ),
                    )
                )
            if len({tool.name for tool in tools}) != len(tools):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.tools",
                    violated_condition="tool names must be unique",
                    expected_category="array",
                )
            divergences = tuple(
                EvidenceClaim(
                    _text(
                        _object(
                            item,
                            {"statement", "kind", "citation_indexes"},
                            "world_architecture_invalid",
                            path=f"$.known_divergences[{index}]",
                        )["statement"],
                        "world_architecture_invalid",
                        500,
                        path=f"$.known_divergences[{index}].statement",
                    ),
                    cast(
                        Any,
                        _object(
                            item,
                            {"statement", "kind", "citation_indexes"},
                            "world_architecture_invalid",
                            path=f"$.known_divergences[{index}]",
                        )["kind"],
                    ),
                    tuple(
                        _array(
                            _object(
                                item,
                                {"statement", "kind", "citation_indexes"},
                                "world_architecture_invalid",
                                path=f"$.known_divergences[{index}]",
                            )["citation_indexes"],
                            1,
                            6,
                            "world_architecture_invalid",
                            path=f"$.known_divergences[{index}].citation_indexes",
                        )
                    ),
                )
                for index, item in enumerate(
                    _array(
                        raw["known_divergences"],
                        0,
                        16,
                        "world_architecture_invalid",
                        path="$.known_divergences",
                    )
                )
            )
            if any(
                claim.kind not in {"observed", "bounded_inference"}
                or not set(claim.citation_indexes).issubset(citations)
                for claim in divergences
            ):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.known_divergences",
                    violated_condition="divergences must cite frozen evidence",
                    expected_category="array",
                )
            provisional = WorldArchitecture(
                boundary,
                tuple(entities),
                tuple(tools),
                divergences,
                SemanticCatalog(()),
                ToolCouplingPlan(() if len(tools) == 1 else (tuple(range(1, len(tools) + 1)),)),
                _PENDING,
            )
            return replace(provisional, catalog=SemanticCatalog(_catalog(provisional)))

        field_shape = "Field={name:stripped_snake[1..64],category:text|integer|number|boolean|timestamp|identifier|enum|list,required:boolean,values:enum|list=>unique_nonempty_text[1..16];otherwise=>omit,values_char_limit:none,entity_ref:actual_relation=>untrimmed_snake[1..64];otherwise=>omit}"  # noqa: E501
        shape = (
            f"{field_shape};objective: return one coherent minimal JSON object; tools must be one coherent minimal JSON array[1..8]; combine related workflow actions when needed; before returning and after any correction, recheck the complete object against every disclosed field, cardinality, uniqueness, reference, actor, and citation rule; output={{boundary:{{name|system_of_record|authority:stripped_text[1..160],purpose:stripped_text[1..4096_unicode_code_points],actors[1..8]:stripped_text[1..80]:unique_after_stripping}}}},"  # noqa: E501
            "entities[1..16]{name:stripped_text[1..64]:unique_in_entities,purpose:stripped_text[1..300],fields[1..24]:unique_names<Field;entity_ref=emitted_entity_name_in_this_object_when_present>},"
            "tools[1..8]{name:stripped_text[1..64]:unique_in_tools,purpose:stripped_text[1..300],actor_names[1..frozen_actor_count]:unique_exact_declared_names,argument_fields[0..24]:unique_names<Field;entity_ref=optional_actual_relation_snake_name;external_relation_label_allowed>,result_fields[1..24]:unique_names<Field;entity_ref=optional_actual_relation_snake_name;external_relation_label_allowed>},"  # noqa: E501
            "known_divergences[0..16]{statement:stripped_text[1..500],kind:observed|bounded_inference,citation_indexes:frozen_one_based[1..6]}}"
        )
        value, ref, work = self._direct_commit(
            "world_architecture",
            {
                "need": request.need,
                "claims": json_value(evidence.claims),
                "conflicts": json_value(evidence.conflicts),
                "gaps": evidence.gaps,
                "citation_catalog": json_value(evidence.catalog),
            },
            shape,
            "design.world_architecture",
            compile,
            {"request": (request_ref,), "evidence": (evidence_ref,), "coverage": (evidence_ref,)},
            store,
            graph,
            run_id,
        )
        return replace(value, artifact=ref), ref, work

    def _shared_tool_shards(
        self,
        architecture: WorldArchitecture,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[tuple[SharedToolContract, ...], tuple[ArtifactRef, ...], tuple[ArtifactRef, ...]]:
        contracts: list[SharedToolContract] = []
        refs: list[ArtifactRef] = []
        works: list[ArtifactRef] = []
        for group in architecture.coupling_plan.groups:

            def compile(
                value: dict[str, Any], members: tuple[int, ...] = group
            ) -> SharedToolContract:
                raw = _object(
                    value,
                    {
                        "atomicity",
                        "concurrency",
                        "idempotency",
                        "ordering",
                        "compensation",
                        "error_policy",
                    },
                    "shared_tool_semantics_invalid",
                )

                def partition(value: object, name: str) -> tuple[tuple[int, ...], ...]:
                    result = tuple(
                        tuple(
                            _array(
                                item,
                                1,
                                len(members),
                                "shared_tool_semantics_invalid",
                                path=f"$.{name}",
                            )
                        )
                        for item in _array(
                            value,
                            1,
                            len(members),
                            "shared_tool_semantics_invalid",
                            path=f"$.{name}",
                        )
                    )
                    flattened = tuple(number for item in result for number in item)
                    if (
                        any(
                            type(number) is not int or number not in members for number in flattened
                        )
                        or len(flattened) != len(members)
                        or len(set(flattened)) != len(flattened)
                    ):
                        raise DesignError(
                            "shared_tool_semantics_invalid",
                            path=f"$.{name}",
                            violated_condition=(
                                "use every input tool_indexes member exactly once; unless evidence "
                                "requires a finer split, one domain containing the complete "
                                "ordered group is valid"
                            ),
                            expected_category="array",
                        )
                    return result

                policy_text = _text(
                    raw["error_policy"],
                    "shared_tool_semantics_invalid",
                    500,
                    path="$.error_policy",
                )
                policy = tuple((member, policy_text) for member in members)
                atomicity = partition(raw["atomicity"], "atomicity")
                concurrency = partition(raw["concurrency"], "concurrency")
                idempotency = partition(raw["idempotency"], "idempotency")
                ordering = tuple(
                    _text(item, "shared_tool_semantics_invalid", 500, path="$.ordering")
                    for item in _array(
                        raw["ordering"], 0, 8, "shared_tool_semantics_invalid", path="$.ordering"
                    )
                )
                compensation = tuple(
                    _text(item, "shared_tool_semantics_invalid", 160, path="$.compensation")
                    for item in _array(
                        raw["compensation"],
                        0,
                        8,
                        "shared_tool_semantics_invalid",
                        path="$.compensation",
                    )
                )
                payload = {
                    "tool_indexes": members,
                    "atomicity": atomicity,
                    "concurrency": concurrency,
                    "idempotency": idempotency,
                    "ordering": ordering,
                    "compensation": compensation,
                    "error_policy": [
                        {"tool_index": index, "policy": text} for index, text in policy
                    ],
                }
                return SharedToolContract(
                    members,
                    atomicity,
                    concurrency,
                    idempotency,
                    ordering,
                    compensation,
                    policy,
                    digest_value(payload),
                    _PENDING,
                )

            projection = {
                "tool_indexes": group,
                "tools": [json_value(architecture.tools[index - 1]) for index in group],
                "citations": json_value(evidence.catalog),
            }
            value, ref, work = self._direct_commit(
                "shared_tool_semantics",
                projection,
                "output={atomicity|concurrency|idempotency:1..group_size arrays of nonempty frozen-index arrays partitioning input.tool_indexes exactly once;unless evidence requires a finer split,use one domain containing the complete ordered input.tool_indexes (example input [1,2,3] -> [[1,2,3]]);ordering:0..8 stripped nonempty text items<=500 code points;compensation:0..8 stripped nonempty text items<=160 code points;error_policy:one stripped nonempty shared-policy string<=500 code points applying to the complete group}. Objective:return compact complete semantics for the frozen group,cover every member exactly once in each shared dimension,and recheck the whole object after correction. Do not return IDs,indexes outside the disclosed group,digests,Artifact refs,schemas,gates,Judge,or release facts.",  # noqa: E501
                "design.shared_tool_semantics",
                compile,
                {"architecture": (architecture_ref,), "evidence": (evidence_ref,)},
                store,
                graph,
                run_id,
                shard_key="-".join(map(str, group)),
            )
            contracts.append(replace(value, artifact=ref))
            refs.append(ref)
            works.append(work)
        return tuple(contracts), tuple(refs), tuple(works)

    def _direct_tools(
        self,
        architecture: WorldArchitecture,
        shared: tuple[SharedToolContract, ...],
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        shared_refs: tuple[ArtifactRef, ...],
        evidence_ref: ArtifactRef,
    ) -> tuple[tuple[ToolDraft, ...], tuple[ArtifactRef, ...], tuple[ArtifactRef, ...]]:
        contracts = {index: contract for contract in shared for index in contract.tool_indexes}
        tools: list[ToolDraft] = []
        refs: list[ArtifactRef] = []
        works: list[ArtifactRef] = []
        citations = {item.index for item in evidence.catalog.items}
        for surface in architecture.tools:
            selected = contracts.get(surface.tool_index)
            bindings = architecture.catalog.bindings

            def compile(
                value: dict[str, Any],
                tool: ToolSurface = surface,
                shared_contract: SharedToolContract | None = selected,
                frozen_bindings: tuple[SemanticBinding, ...] = bindings,
            ) -> ToolDraft:
                raw = _object(
                    value,
                    {
                        "preconditions",
                        "transitions",
                        "postconditions",
                        "errors",
                    },
                    "tool_semantics_invalid",
                )
                pre = _compile_rules(
                    raw["preconditions"],
                    frozen_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.preconditions",
                    minimum=1,
                    maximum=6,
                    errors_only=False,
                )
                trans = _compile_rules(
                    raw["transitions"],
                    frozen_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.transitions",
                    minimum=1,
                    maximum=6,
                    errors_only=False,
                )
                post = _compile_rules(
                    raw["postconditions"],
                    frozen_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.postconditions",
                    minimum=0,
                    maximum=6,
                    errors_only=False,
                )
                errors = _compile_rules(
                    raw["errors"],
                    frozen_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.errors",
                    minimum=0,
                    maximum=6,
                    errors_only=True,
                )
                if not any(
                    effect.operation not in {"preserve", "reject"}
                    for rule in trans
                    for effect in rule.effects
                ):
                    raise DesignError(
                        "tool_semantics_invalid",
                        path="$.transitions",
                        violated_condition="transitions require a state-changing effect",
                        expected_category="array",
                    )
                digest = _local_rules_digest(
                    tool.tool_index,
                    frozen_bindings,
                    pre,
                    trans,
                    post,
                    errors,
                    shared_contract.digest if shared_contract else None,
                )
                return ToolDraft(
                    tool.tool_index,
                    tool,
                    frozen_bindings,
                    pre,
                    trans,
                    post,
                    errors,
                    shared_contract.digest if shared_contract else None,
                    digest,
                )

            projection = {
                "tool": json_value(surface),
                "bindings": json_value(bindings),
                "shared_contract": json_value(selected) if selected else None,
                "citation_catalog": json_value(evidence.catalog),
            }
            value, ref, work = self._direct_commit(
                "tool_semantics",
                projection,
                f"{{preconditions[1..6] {_RULE_DRAFT_SHAPE} (non-error),transitions[1..6] {_RULE_DRAFT_SHAPE} (non-error;at least one state-changing effect),postconditions[0..6] {_RULE_DRAFT_SHAPE} (non-error),errors[0..6] {_RULE_DRAFT_SHAPE} (errors-only)}}. Objective:return compact complete semantics for the frozen tool and recheck every section after correction. Do not return tool indexes,shared contracts,IDs,digests,schemas,gates,Judge,or release facts.",  # noqa: E501
                "design.tool_semantics",
                compile,
                {
                    "architecture": (architecture_ref,),
                    "shared_tools": shared_refs,
                    "evidence": (evidence_ref,),
                },
                store,
                graph,
                run_id,
                shard_key=surface.name,
            )
            tools.append(value)
            refs.append(ref)
            works.append(work)
        return tuple(tools), tuple(refs), tuple(works)

    def _direct_rules(
        self,
        architecture: WorldArchitecture,
        tools: tuple[ToolDraft, ...],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        tool_refs: tuple[ArtifactRef, ...],
    ) -> tuple[WorldRuleSet, ArtifactRef, ArtifactRef]:
        def compile(value: dict[str, Any]) -> WorldRuleSet:
            raw = _object(value, {"initial_rules", "invariants"}, "world_rules_invalid")
            initial = _compile_rules(
                raw["initial_rules"],
                architecture.catalog.bindings,
                set(),
                "world_rules_invalid",
                path="$.initial_rules",
                minimum=0,
                maximum=8,
                errors_only=False,
            )
            invariants = _compile_rules(
                raw["invariants"],
                architecture.catalog.bindings,
                set(),
                "world_rules_invalid",
                path="$.invariants",
                minimum=0,
                maximum=16,
                errors_only=False,
            )
            local = {
                json.dumps(json_value(rule), sort_keys=True)
                for tool in tools
                for section in (
                    tool.preconditions,
                    tool.transitions,
                    tool.postconditions,
                    tool.errors,
                )
                for rule in section
            }
            if any(
                json.dumps(json_value(rule), sort_keys=True) in local
                for rule in (*initial, *invariants)
            ):
                raise DesignError(
                    "world_rules_duplicate_local_rule",
                    path="$",
                    violated_condition="world rules may not duplicate local tool rules",
                    expected_category="semantic_draft",
                )
            return WorldRuleSet(
                initial,
                invariants,
                digest_value({"initial_rules": initial, "invariants": invariants}),
                _PENDING,
            )

        value, ref, work = self._direct_commit(
            "world_rules",
            {"architecture": json_value(architecture), "tools": json_value(tools)},
            f"{{initial_rules[0..8] {_RULE_DRAFT_SHAPE} (non-error;citation_indexes=[]),invariants[0..16] {_RULE_DRAFT_SHAPE} (non-error;citation_indexes=[])}}. Objective:return only necessary initial and cross-tool rules not duplicated by local tool rules;empty invariants are valid. Recheck the complete object after correction and do not return IDs,digests,schemas,gates,Judge,or release facts.",  # noqa: E501
            "design.world_rules",
            compile,
            {"architecture": (architecture_ref,), "tool_semantics": tool_refs},
            store,
            graph,
            run_id,
        )
        return replace(value, artifact=ref), ref, work

    def _direct_curriculum(
        self,
        architecture: WorldArchitecture,
        rules: WorldRuleSet,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        rules_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[CurriculumPlan, ArtifactRef, ArtifactRef]:
        citations = {item.index for item in evidence.catalog.items}

        def compile(value: dict[str, Any]) -> CurriculumPlan:
            raw = _object(value, {"families"}, "curriculum_plan_invalid")
            families: list[CurriculumFamily] = []
            for index, item in enumerate(
                _array(raw["families"], 1, 8, "curriculum_plan_invalid", path="$.families")
            ):
                family = _object(
                    item,
                    {
                        "task_family_id",
                        "objective",
                        "actor_index",
                        "tool_indexes",
                        "dimensions",
                        "sampling_intent",
                        "citation_indexes",
                    },
                    "curriculum_plan_invalid",
                    path=f"$.families[{index}]",
                )
                task_id = _text(
                    family["task_family_id"],
                    "curriculum_plan_invalid",
                    64,
                    path=f"$.families[{index}].task_family_id",
                )
                if not _NAME.fullmatch(task_id):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].task_family_id",
                        violated_condition="task family id must use the declared grammar",
                        expected_category="string",
                    )
                if type(family["actor_index"]) is not int or not 1 <= family["actor_index"] <= len(
                    architecture.boundary.actors
                ):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].actor_index",
                        violated_condition="actor index must be one frozen actor index",
                        expected_category="number",
                    )
                tool_indexes = tuple(
                    _array(
                        family["tool_indexes"],
                        1,
                        len(architecture.tools),
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].tool_indexes",
                    )
                )
                cited = tuple(
                    _array(
                        family["citation_indexes"],
                        1,
                        6,
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].citation_indexes",
                    )
                )
                if any(
                    type(tool) is not int or not 1 <= tool <= len(architecture.tools)
                    for tool in tool_indexes
                ) or len(set(tool_indexes)) != len(tool_indexes):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].tool_indexes",
                        violated_condition="family tools must be unique frozen indexes",
                        expected_category="array",
                    )
                if any(
                    type(citation) is not int or citation not in citations for citation in cited
                ) or len(set(cited)) != len(cited):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].citation_indexes",
                        violated_condition="family citations must be unique frozen indexes",
                        expected_category="array",
                    )
                dimensions: list[DifficultyDimension] = []
                for dimension_index, dimension in enumerate(
                    _array(
                        family["dimensions"],
                        1,
                        6,
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions",
                    )
                ):
                    raw_dimension = _object(
                        dimension,
                        {"name", "meaning", "levels"},
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions[{dimension_index}]",
                    )
                    levels: list[DifficultyLevel] = []
                    for level_index, level in enumerate(
                        _array(
                            raw_dimension["levels"],
                            2,
                            5,
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].dimensions[{dimension_index}].levels",
                        )
                    ):
                        raw_level = _object(
                            level,
                            {"name", "meaning"},
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}]",
                        )
                        try:
                            levels.append(
                                DifficultyLevel(
                                    _text(
                                        raw_level["name"],
                                        "curriculum_plan_invalid",
                                        40,
                                        path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}].name",
                                    ),
                                    _text(
                                        raw_level["meaning"],
                                        "curriculum_plan_invalid",
                                        300,
                                        path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}].meaning",
                                    ),
                                )
                            )
                        except ValueError as exc:
                            raise DesignError(
                                "curriculum_plan_invalid",
                                path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}]",
                                violated_condition="difficulty level must use the declared grammar",
                                expected_category="object",
                            ) from exc
                    try:
                        dimensions.append(
                            DifficultyDimension(
                                _text(
                                    raw_dimension["name"],
                                    "curriculum_plan_invalid",
                                    40,
                                    path=f"$.families[{index}].dimensions[{dimension_index}].name",
                                ),
                                _text(
                                    raw_dimension["meaning"],
                                    "curriculum_plan_invalid",
                                    300,
                                    path=f"$.families[{index}].dimensions[{dimension_index}].meaning",
                                ),
                                tuple(levels),
                            )
                        )
                    except ValueError as exc:
                        raise DesignError(
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].dimensions[{dimension_index}]",
                            violated_condition="difficulty dimension must use the declared grammar",
                            expected_category="object",
                        ) from exc
                compiled_dimensions = tuple(dimensions)
                if len({dimension.name for dimension in compiled_dimensions}) != len(
                    compiled_dimensions
                ):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions",
                        violated_condition="dimension names must be unique",
                        expected_category="array",
                    )
                try:
                    schema = compile_difficulty_schema(task_id, compiled_dimensions)
                except ValueError as exc:
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions",
                        violated_condition=(
                            "difficulty schema must use declared dimensions and levels"
                        ),
                        expected_category="array",
                    ) from exc
                families.append(
                    CurriculumFamily(
                        index + 1,
                        task_id,
                        _text(
                            family["objective"],
                            "curriculum_plan_invalid",
                            500,
                            path=f"$.families[{index}].objective",
                        ),
                        family["actor_index"],
                        tool_indexes,
                        schema,
                        _text(
                            family["sampling_intent"],
                            "curriculum_plan_invalid",
                            300,
                            path=f"$.families[{index}].sampling_intent",
                        ),
                        cited,
                    )
                )
            if len({family.task_family_id for family in families}) != len(families):
                raise DesignError(
                    "curriculum_plan_invalid",
                    path="$.families",
                    violated_condition="family ids must be unique",
                    expected_category="array",
                )
            return CurriculumPlan(tuple(families), _PENDING)

        value, ref, work = self._direct_commit(
            "curriculum_plan",
            {
                "architecture": json_value(architecture),
                "world_rules": json_value(rules),
                "citation_catalog": json_value(evidence.catalog),
            },
            "{families[1..8]{task_family_id:[a-z][a-z0-9_]{0,63} (1..64 code points),objective:stripped nonempty text<=500,actor_index:one frozen actor index,tool_indexes:1..tool_count unique frozen indexes,dimensions[1..6]{name:[a-z][a-z0-9_-]{0,39} (1..40 code points),meaning:stripped nonempty text<=300,levels[2..5]{name:[a-z][a-z0-9_-]{0,39} (1..40 code points),meaning:stripped nonempty text<=300}:unique names},sampling_intent:stripped nonempty text<=300,citation_indexes:1..6 unique frozen indexes}}. Objective:define compact parameterized task families using the frozen catalog;retain the accepted hyphenated dimension and level names without normalization,and recheck the complete object after correction. Do not return family indexes,difficulty schema keys,digests,IDs,seeds,rewards,verifier cases,gates,Judge,or release facts.",  # noqa: E501
            "design.curriculum_plan",
            compile,
            {
                "architecture": (architecture_ref,),
                "rules": (rules_ref,),
                "evidence": (evidence_ref,),
            },
            store,
            graph,
            run_id,
        )
        return replace(value, artifact=ref), ref, work

    def _direct_tasks(
        self,
        architecture: WorldArchitecture,
        tools: tuple[ToolDraft, ...],
        rules: WorldRuleSet,
        curriculum: CurriculumPlan,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        tool_refs: tuple[ArtifactRef, ...],
        curriculum_ref: ArtifactRef,
        rules_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[tuple[TaskRequirement, ...], tuple[ArtifactRef, ...], tuple[ArtifactRef, ...]]:
        citations = {item.index for item in evidence.catalog.items}
        result: list[TaskRequirement] = []
        refs: list[ArtifactRef] = []
        works: list[ArtifactRef] = []
        for family in curriculum.families:

            def compile(
                value: dict[str, Any], frozen: CurriculumFamily = family
            ) -> TaskRequirement:
                raw = _object(
                    value,
                    {
                        "public_goal_fields",
                        "initial_rules",
                        "success_rules",
                        "failure_rules",
                        "terminal_rules",
                    },
                    "task_requirement_invalid",
                )
                fields = tuple(
                    _array(
                        raw["public_goal_fields"],
                        1,
                        12,
                        "task_requirement_invalid",
                        path="$.public_goal_fields",
                    )
                )
                if any(
                    type(field) is not int or not 1 <= field <= len(architecture.catalog.bindings)
                    for field in fields
                ) or len(set(fields)) != len(fields):
                    raise DesignError(
                        "task_requirement_invalid",
                        path="$.public_goal_fields",
                        violated_condition="public goal fields must be unique frozen indexes",
                        expected_category="array",
                    )
                return TaskRequirement(
                    frozen.task_family_index,
                    fields,
                    _compile_task_rules(
                        raw["initial_rules"],
                        architecture.catalog.bindings,
                        citations,
                        path="$.initial_rules",
                        minimum=0,
                        maximum=8,
                    ),
                    _compile_task_rules(
                        raw["success_rules"],
                        architecture.catalog.bindings,
                        citations,
                        path="$.success_rules",
                        minimum=1,
                        maximum=8,
                    ),
                    _compile_task_rules(
                        raw["failure_rules"],
                        architecture.catalog.bindings,
                        citations,
                        path="$.failure_rules",
                        minimum=0,
                        maximum=8,
                    ),
                    _compile_task_rules(
                        raw["terminal_rules"],
                        architecture.catalog.bindings,
                        citations,
                        path="$.terminal_rules",
                        minimum=1,
                        maximum=8,
                    ),
                    _PENDING,
                )

            projection = {
                "family": {
                    "objective": family.objective,
                    "actor_index": family.actor_index,
                    "tool_indexes": list(family.tool_indexes),
                    "difficulty_schema": {
                        "dimensions": json_value(family.difficulty_schema.dimensions),
                    },
                    "sampling_intent": family.sampling_intent,
                    "citation_indexes": list(family.citation_indexes),
                },
                "semantic_catalog": {"bindings": json_value(architecture.catalog.bindings)},
                "world_rules": {
                    "initial_rules": json_value(rules.initial_rules),
                    "invariants": json_value(rules.invariants),
                },
                "tools": [
                    {
                        "surface": json_value(tools[index - 1].surface),
                        "preconditions": json_value(tools[index - 1].preconditions),
                        "transitions": json_value(tools[index - 1].transitions),
                        "postconditions": json_value(tools[index - 1].postconditions),
                        "errors": json_value(tools[index - 1].errors),
                    }
                    for index in family.tool_indexes
                ],
                "citation_catalog": json_value(evidence.catalog),
                "reachability_policy": {"action_tool_indexes": family.tool_indexes},
            }
            value, ref, work = self._direct_commit(
                "task_requirement",
                projection,
                f"{{public_goal_fields[1..12] unique frozen SemanticCatalog indexes,initial_rules[0..8] {_TASK_RULE_DRAFT_SHAPE},success_rules[1..8] {_TASK_RULE_DRAFT_SHAPE},failure_rules[0..8] {_TASK_RULE_DRAFT_SHAPE},terminal_rules[1..8] {_TASK_RULE_DRAFT_SHAPE}}}. Objective:return compact complete reset,success,failure,and terminal semantics for the frozen task family;its DifficultySchema is read-only. Recheck every section after correction and do not return task-family indexes,IDs,digests,schemas,rewards,gates,Judge,or release facts.",  # noqa: E501
                "design.task_requirement",
                compile,
                {
                    "architecture": (architecture_ref,),
                    "tool_semantics": tuple(tool_refs[index - 1] for index in family.tool_indexes),
                    "curriculum": (curriculum_ref,),
                    "rules": (rules_ref,),
                    "evidence": (evidence_ref,),
                },
                store,
                graph,
                run_id,
                shard_key=family.task_family_id,
            )
            result.append(replace(value, artifact=ref))
            refs.append(ref)
            works.append(work)
        return tuple(result), tuple(refs), tuple(works)

    def _modeling_gate(
        self,
        evidence: EvidenceGraph,
        architecture: WorldArchitecture,
        shared: tuple[SharedToolContract, ...],
        tools: tuple[ToolDraft, ...],
        rules: WorldRuleSet,
        curriculum: CurriculumPlan,
        requirements: tuple[TaskRequirement, ...],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        evidence_ref: ArtifactRef,
        architecture_ref: ArtifactRef,
        shared_refs: tuple[ArtifactRef, ...],
        tool_refs: tuple[ArtifactRef, ...],
        rules_ref: ArtifactRef,
        curriculum_ref: ArtifactRef,
        task_refs: tuple[ArtifactRef, ...],
    ) -> tuple[DesignContract, ArtifactRef, ArtifactRef]:
        if tuple(task.task_family_index for task in requirements) != tuple(
            family.task_family_index for family in curriculum.families
        ):
            raise DesignError("modeling_gate_task_closure_invalid", correctable=False)
        recipes: list[AssuranceRecipe] = []
        for family, task in zip(curriculum.families, requirements, strict=True):
            primary = tuple(
                (dimension.name, dimension.levels[0].name)
                for dimension in family.difficulty_schema.dimensions
            )
            alternate = tuple(
                (
                    dimension.name,
                    (dimension.levels[1].name if index == 0 else dimension.levels[0].name),
                )
                for index, dimension in enumerate(family.difficulty_schema.dimensions)
            )
            task_digest = digest_value(
                {"task_requirement": json_value(task), "family": json_value(family)}
            )
            for tool_index in family.tool_indexes:
                tool = tools[tool_index - 1]
                payload = {
                    "task_family_index": family.task_family_index,
                    "tool_index": tool_index,
                    "task_digest": task_digest,
                    "difficulty_digest": family.difficulty_schema.schema_digest,
                    "tool_digest": tool.local_rules_digest,
                    "actor": architecture.boundary.actors[family.actor_index - 1],
                    "primary_difficulty": primary,
                    "alternate_difficulty": alternate,
                    "action_tool_indexes": family.tool_indexes,
                }
                recipe_digest = digest_value(payload)
                recipes.append(
                    AssuranceRecipe(
                        task_family_index=family.task_family_index,
                        tool_index=tool_index,
                        task_digest=task_digest,
                        difficulty_digest=family.difficulty_schema.schema_digest,
                        tool_digest=tool.local_rules_digest,
                        actor=architecture.boundary.actors[family.actor_index - 1],
                        primary_difficulty=primary,
                        alternate_difficulty=alternate,
                        action_tool_indexes=family.tool_indexes,
                        recipe_digest=recipe_digest,
                    )
                )
        executable: list[ExecutableTaskContract] = []
        categories = _catalog_categories(architecture)
        for family, task in zip(curriculum.families, requirements, strict=True):
            public = tuple(
                (f"/goal/{index}", categories[index - 1]) for index in task.public_goal_fields
            )
            initial = tuple(
                (f"/tools/{tool.tool_index}/{field.name}", field.category)
                for tool in architecture.tools
                for field in (*tool.argument_fields, *tool.result_fields)
            )
            bindings = tuple(EvaluatorGoalBinding(path, path) for path, _ in public)
            reward = RewardSpec()
            termination = TerminationSpec()
            required = tuple(
                recipe.recipe_digest
                for recipe in recipes
                if recipe.task_family_index == family.task_family_index
            )
            verification = VerificationRequirements(family.task_family_index, True, required)
            executable.append(
                ExecutableTaskContract(
                    family.task_family_index,
                    task,
                    public,
                    initial,
                    bindings,
                    digest_value({"objective": family.objective, "public_goal_schema": public}),
                    reward,
                    digest_value(reward),
                    termination,
                    digest_value(termination),
                    verification,
                    digest_value(verification),
                )
            )

        def compile(value: dict[str, Any]) -> DesignContract:
            if value != {"closed": True}:
                raise DesignError("modeling_gate_invalid", correctable=False)
            return DesignContract(
                evidence,
                architecture,
                shared,
                tools,
                rules,
                curriculum,
                requirements,
                tuple(executable),
                tuple(recipes),
                _PENDING,
            )

        payload = {"closed": True}
        node = graph.execute(
            store,
            run_id,
            "modeling_gate",
            {
                "evidence": (evidence_ref,),
                "architecture": (architecture_ref,),
                "shared_tools": shared_refs,
                "tool_semantics": tool_refs,
                "curriculum": (curriculum_ref,),
                "tasks": task_refs,
                "rules": (rules_ref,),
            },
            "design.environment_design",
            lambda _: payload,
            compile,
            {
                "evidence": evidence_ref.digest,
                "architecture": architecture_ref.digest,
                "shared_tools": [ref.digest for ref in shared_refs],
                "tool_semantics": [ref.digest for ref in tool_refs],
                "rules": rules_ref.digest,
                "curriculum": curriculum_ref.digest,
                "tasks": [ref.digest for ref in task_refs],
                "output_shape": "EnvironmentDesign@1",
            },
            artifact_projection=_design_artifact_value,
        )
        return (
            replace(node.value, artifact=node.artifact, work_refs=(node.work,)),
            node.artifact,
            node.work,
        )

    def run(
        self, request: EnvironmentRequest, store: ArtifactStore, graph: GraphRunner, run_id: str
    ) -> DesignResult:
        request_ref = store.put_json("control.design_request", {"need_digest": request.need_digest})
        plan, plan_ref, plan_work = self._research_plan(request, store, graph, run_id, request_ref)
        sources, acquire_ref, acquire_work = self._research_acquire(
            plan, store, graph, run_id, plan_ref
        )
        evidence, evidence_ref, synthesis_work = self._research_synthesis(
            request, plan, sources, store, graph, run_id, request_ref, plan_ref, acquire_ref
        )
        architecture, architecture_ref, architecture_work = self._direct_architecture(
            request, evidence, store, graph, run_id, request_ref, evidence_ref
        )
        shared, shared_refs, shared_works = self._shared_tool_shards(
            architecture, evidence, store, graph, run_id, architecture_ref, evidence_ref
        )
        tools, tool_refs, tool_works = self._direct_tools(
            architecture,
            shared,
            evidence,
            store,
            graph,
            run_id,
            architecture_ref,
            shared_refs,
            evidence_ref,
        )
        rules, rules_ref, rules_work = self._direct_rules(
            architecture, tools, store, graph, run_id, architecture_ref, tool_refs
        )
        curriculum, curriculum_ref, curriculum_work = self._direct_curriculum(
            architecture,
            rules,
            evidence,
            store,
            graph,
            run_id,
            architecture_ref,
            rules_ref,
            evidence_ref,
        )
        tasks, task_refs, task_works = self._direct_tasks(
            architecture,
            tools,
            rules,
            curriculum,
            evidence,
            store,
            graph,
            run_id,
            architecture_ref,
            tool_refs,
            curriculum_ref,
            rules_ref,
            evidence_ref,
        )
        design, design_ref, gate_work = self._modeling_gate(
            evidence,
            architecture,
            shared,
            tools,
            rules,
            curriculum,
            tasks,
            store,
            graph,
            run_id,
            evidence_ref,
            architecture_ref,
            shared_refs,
            tool_refs,
            rules_ref,
            curriculum_ref,
            task_refs,
        )
        works = (
            plan_work,
            acquire_work,
            synthesis_work,
            architecture_work,
            *shared_works,
            *tool_works,
            rules_work,
            curriculum_work,
            *task_works,
            gate_work,
        )
        refs = (
            request_ref,
            plan_ref,
            acquire_ref,
            evidence_ref,
            architecture_ref,
            *shared_refs,
            *tool_refs,
            rules_ref,
            curriculum_ref,
            *task_refs,
            design_ref,
        )
        return DesignResult(replace(design, work_refs=works), works, refs)
