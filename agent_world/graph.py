"""Two fixed Foundry graphs and one small node-transaction runner.

The graph is a domain contract, not a scheduler.  A transaction resolves exact
Artifact inputs, executes one proposal/process/framework operation, validates
it, and commits one immutable output plus one terminal WorkRecord.  Raw model
output never crosses an edge.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeVar

from agent_world.artifacts import ArtifactStore, canonical_json
from agent_world.contracts import (
    ArtifactEnvelope,
    ArtifactRef,
    CorrectionPacket,
    ExecutionKind,
    Finding,
    GraphId,
    NodeOwner,
    OperationEvidence,
    TerminalStatus,
    WorkCoordinate,
    WorkRecord,
    digest_text,
    from_value,
    json_value,
)
from agent_world.invocation import runtime_skill_digest

T = TypeVar("T")
P = TypeVar("P")


@dataclass(frozen=True, slots=True)
class NodeSpec:
    id: str
    owner: NodeOwner
    execution_kind: ExecutionKind
    input_ports: tuple[str, ...]
    output_ports: tuple[str, ...]
    output_contract: str
    prompt_id: str | None = None
    skill: str | None = None
    route: Literal["direct", "agent"] | None = None
    local_corrections: int = 1
    optional_input_ports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        model_kind = self.execution_kind in {"direct_llm", "agent"}
        if model_kind != (self.prompt_id is not None):
            raise ValueError("graph_prompt_binding_invalid")
        if (self.execution_kind == "agent") != (self.skill is not None):
            raise ValueError("graph_skill_binding_invalid")
        expected_route = (
            "direct"
            if self.execution_kind == "direct_llm"
            else "agent"
            if self.execution_kind == "agent"
            else None
        )
        if self.route != expected_route:
            raise ValueError("graph_route_binding_invalid")
        if self.execution_kind == "direct_llm" and self.skill is not None:
            raise ValueError("graph_direct_skill_forbidden")
        if self.local_corrections not in {0, 1, 2}:
            raise ValueError("graph_correction_limit_invalid")
        if self.local_corrections == 2 and (
            self.execution_kind,
            self.route,
        ) != ("direct_llm", "direct"):
            raise ValueError("graph_correction_limit_invalid")
        if self.optional_input_ports and (self.id, self.optional_input_ports) not in {
            ("tool_semantics", ("shared_tools",)),
            ("modeling_gate", ("shared_tools",)),
        }:
            raise ValueError("graph_optional_port_invalid")
        if not set(self.optional_input_ports).issubset(self.input_ports):
            raise ValueError("graph_optional_port_invalid")


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    source: str
    source_port: str
    target: str
    target_port: str
    condition: str = "passed"


@dataclass(frozen=True, slots=True)
class NodeResult[T]:
    value: T
    artifact: ArtifactRef
    work: ArtifactRef
    semantic_revision_digest: str


# ---------------------------------------------------------------------------
# Resume infrastructure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeadEntry:
    """One committed node output, cached for resume/restart-from-node."""

    artifact_ref: ArtifactRef
    work_ref: ArtifactRef
    semantic_revision_digest: str
    compiled_json: Any  # json_value(compiled) at commit time


def _head_key(graph_id: str, node_id: str, shard_key: str | None) -> str:
    return f"{graph_id}:{node_id}:{shard_key or ''}"


def _ancestors(node_id: str, edges: tuple[EdgeSpec, ...]) -> set[str]:
    """Return all strictly-upstream node ids of *node_id* within one graph."""
    parents = {edge.source for edge in edges if edge.target == node_id}
    result: set[str] = set()
    for parent in parents:
        result.add(parent)
        result |= _ancestors(parent, edges)
    return result


def compute_upstream(
    restart_from: str,
    design_nodes: tuple[NodeSpec, ...],
    design_edges: tuple[EdgeSpec, ...],
    candidate_nodes: tuple[NodeSpec, ...],
    candidate_edges: tuple[EdgeSpec, ...],
) -> set[str]:
    """Nodes strictly upstream of *restart_from* across both graphs.

    Candidate nodes are all downstream of design nodes (the design output
    feeds the candidate graph).
    """
    design_ids = {n.id for n in design_nodes}
    candidate_ids = {n.id for n in candidate_nodes}
    if restart_from in design_ids:
        return _ancestors(restart_from, design_edges)
    if restart_from in candidate_ids:
        return design_ids | _ancestors(restart_from, candidate_edges)
    raise ValueError(f"resume_unknown_node:{restart_from}")


class ResumeContext:
    """Carries resume state through the pipeline.

    ``restart_from`` (``--from``) re-runs that node and everything downstream,
    skipping strictly-upstream nodes that have cached heads.  Without
    ``restart_from`` (pure ``--resume``), every node with a committed head
    whose ``semantic_revision`` still matches is skipped.
    """

    def __init__(
        self,
        *,
        restart_from: str | None = None,
        skip_node_ids: set[str] | None = None,
    ) -> None:
        self.restart_from = restart_from
        self.skip_node_ids = skip_node_ids or set()
        self.heads: dict[str, HeadEntry] = {}

    # -- head access --------------------------------------------------------

    def get_head(
        self, graph_id: str, node_id: str, shard_key: str | None
    ) -> HeadEntry | None:
        return self.heads.get(_head_key(graph_id, node_id, shard_key))

    def should_skip(
        self,
        graph_id: str,
        node_id: str,
        shard_key: str | None,
        semantic_revision: str,
    ) -> bool:
        head = self.get_head(graph_id, node_id, shard_key)
        if head is None:
            return False
        if self.restart_from is not None:
            return node_id in self.skip_node_ids
        return head.semantic_revision_digest == semantic_revision

    def record(
        self,
        graph_id: str,
        node_id: str,
        shard_key: str | None,
        *,
        compiled_json: Any,
        artifact_ref: ArtifactRef,
        work_ref: ArtifactRef,
        semantic_revision_digest: str,
    ) -> None:
        self.heads[_head_key(graph_id, node_id, shard_key)] = HeadEntry(
            artifact_ref, work_ref, semantic_revision_digest, compiled_json
        )

    # -- persistence --------------------------------------------------------

    def save(self, path: Path) -> None:
        data: dict[str, Any] = {
            "restart_from": self.restart_from,
            "heads": {
                key: {
                    "artifact_ref": json_value(entry.artifact_ref),
                    "work_ref": json_value(entry.work_ref),
                    "semantic_revision_digest": entry.semantic_revision_digest,
                    "compiled_json": entry.compiled_json,
                }
                for key, entry in self.heads.items()
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        )

    @classmethod
    def load(cls, path: Path) -> ResumeContext:
        data = json.loads(path.read_bytes())
        ctx = cls(restart_from=data.get("restart_from"))
        for key, raw in data.get("heads", {}).items():
            ctx.heads[key] = HeadEntry(
                ArtifactRef(**raw["artifact_ref"]),
                ArtifactRef(**raw["work_ref"]),
                raw["semantic_revision_digest"],
                raw["compiled_json"],
            )
        return ctx


class NodeExecutionError(RuntimeError):
    """Safe node terminal that the runner can persist without raw details."""

    def __init__(
        self,
        code: str,
        status: TerminalStatus = "rejected",
        retryable: bool = False,
        *,
        evidence: Any = None,
        correction: CorrectionPacket | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.retryable = retryable
        self.evidence = evidence
        self.correction = correction
        self.node_id: str | None = None
        self.artifact_refs: tuple[ArtifactRef, ...] = ()


DESIGN_NODES = (
    NodeSpec(
        "research_plan",
        "designer",
        "agent",
        ("request",),
        ("research_plan",),
        "ResearchPlanDraft@1",
        "research-plan@1",
        "research-world-evidence",
        "agent",
    ),
    NodeSpec(
        "research_acquire",
        "designer",
        "framework",
        ("research_plan",),
        ("sources", "citations"),
        "ResearchAcquisition@1",
        local_corrections=0,
    ),
    NodeSpec(
        "research_synthesis",
        "designer",
        "agent",
        ("request", "research_plan", "sources", "citations"),
        ("evidence", "coverage"),
        "ResearchSynthesisDraft@1",
        "research-synthesis@1",
        "research-world-evidence",
        "agent",
    ),
    NodeSpec(
        "world_architecture",
        "designer",
        "direct_llm",
        ("request", "evidence", "coverage"),
        ("architecture",),
        "WorldArchitectureSourceDraft@1",
        "world-architecture@2",
        route="direct",
    ),
    NodeSpec(
        "shared_tool_semantics",
        "designer",
        "direct_llm",
        ("architecture", "evidence"),
        ("shared_tools",),
        "SharedToolSemanticsSourceDraft@1",
        "shared-tool-semantics@1",
        route="direct",
    ),
    NodeSpec(
        "tool_semantics",
        "designer",
        "direct_llm",
        ("architecture", "shared_tools", "evidence"),
        ("tool_semantics",),
        "ToolSemanticsSourceDraft@1",
        "tool-semantics@4",
        route="direct",
        local_corrections=2,
        optional_input_ports=("shared_tools",),
    ),
    NodeSpec(
        "world_rules",
        "designer",
        "direct_llm",
        ("architecture", "tool_semantics"),
        ("rules",),
        "WorldRulesSourceDraft@1",
        "world-rules@1",
        route="direct",
    ),
    NodeSpec(
        "curriculum_plan",
        "designer",
        "direct_llm",
        ("architecture", "rules", "evidence"),
        ("curriculum",),
        "CurriculumPlanSourceDraft@1",
        "curriculum-plan@1",
        route="direct",
        local_corrections=2,
    ),
    NodeSpec(
        "task_requirement",
        "designer",
        "direct_llm",
        ("architecture", "tool_semantics", "curriculum", "rules", "evidence"),
        ("tasks",),
        "TaskRequirementSourceDraft@1",
        "task-requirement@3",
        route="direct",
        local_corrections=2,
    ),
    NodeSpec(
        "modeling_gate",
        "designer",
        "framework",
        (
            "evidence",
            "architecture",
            "shared_tools",
            "tool_semantics",
            "curriculum",
            "tasks",
            "rules",
        ),
        ("design",),
        "EnvironmentDesign@1",
        local_corrections=0,
        optional_input_ports=("shared_tools",),
    ),
)

CANDIDATE_NODES = (
    NodeSpec(
        "build_plan",
        "builder",
        "agent",
        ("design",),
        ("build_plan",),
        "BuildPlanDraft@1",
        "build-plan@1",
        "engineer-build-planning",
        "agent",
    ),
    NodeSpec(
        "verifier_intent",
        "designer",
        "agent",
        ("design",),
        ("verifier",),
        "VerifierIntentDraft@1",
        "verifier-intent@1",
        "challenge-agent-world",
        "agent",
    ),
    NodeSpec(
        "candidate_build",
        "builder",
        "agent",
        ("design", "build_plan"),
        ("candidate",),
        "EnvironmentCandidate@1",
        "candidate-build@2",
        "engineer-environment-codegen",
        "agent",
        local_corrections=1,
    ),
    NodeSpec(
        "integration",
        "builder",
        "candidate_process",
        ("design", "candidate"),
        ("integration",),
        "IntegrationReport@1",
        local_corrections=0,
    ),
    NodeSpec(
        "judge",
        "judge",
        "candidate_process",
        ("design", "candidate", "integration", "verifier"),
        ("judge", "findings"),
        "JudgeReport@1",
        local_corrections=0,
    ),
    NodeSpec(
        "package",
        "controller",
        "framework",
        (
            "design",
            "candidate",
            "integration",
            "judge",
            "verifier",
            "semantic_lineage",
            "implementation_lineage",
            "design_work_records",
            "candidate_work_records",
        ),
        ("package", "dossier", "telemetry"),
        "EnvironmentPackage@1",
        local_corrections=0,
    ),
    NodeSpec(
        "registry",
        "registry",
        "framework",
        (
            "package",
            "design",
            "candidate",
            "integration",
            "judge",
            "verifier",
            "physical_package",
            "dossier",
            "telemetry",
            "semantic_lineage",
            "implementation_lineage",
            "design_work_records",
            "candidate_work_records",
        ),
        ("receipt",),
        "RegistryReceipt@1",
        local_corrections=0,
    ),
)

DESIGN_EDGES = (
    EdgeSpec("research_plan", "research_plan", "research_acquire", "research_plan"),
    EdgeSpec("research_plan", "research_plan", "research_synthesis", "research_plan"),
    EdgeSpec("research_acquire", "sources", "research_synthesis", "sources"),
    EdgeSpec("research_acquire", "citations", "research_synthesis", "citations"),
    EdgeSpec("research_synthesis", "evidence", "world_architecture", "evidence"),
    EdgeSpec("research_synthesis", "coverage", "world_architecture", "coverage"),
    EdgeSpec("world_architecture", "architecture", "shared_tool_semantics", "architecture"),
    EdgeSpec("research_synthesis", "evidence", "shared_tool_semantics", "evidence"),
    EdgeSpec("world_architecture", "architecture", "tool_semantics", "architecture"),
    EdgeSpec("shared_tool_semantics", "shared_tools", "tool_semantics", "shared_tools"),
    EdgeSpec("research_synthesis", "evidence", "tool_semantics", "evidence"),
    EdgeSpec("world_architecture", "architecture", "world_rules", "architecture"),
    EdgeSpec("tool_semantics", "tool_semantics", "world_rules", "tool_semantics"),
    EdgeSpec("world_architecture", "architecture", "curriculum_plan", "architecture"),
    EdgeSpec("world_rules", "rules", "curriculum_plan", "rules"),
    EdgeSpec("research_synthesis", "evidence", "curriculum_plan", "evidence"),
    EdgeSpec("curriculum_plan", "curriculum", "task_requirement", "curriculum"),
    EdgeSpec("world_architecture", "architecture", "task_requirement", "architecture"),
    EdgeSpec("tool_semantics", "tool_semantics", "task_requirement", "tool_semantics"),
    EdgeSpec("world_rules", "rules", "task_requirement", "rules"),
    EdgeSpec("research_synthesis", "evidence", "task_requirement", "evidence"),
    EdgeSpec("research_synthesis", "evidence", "modeling_gate", "evidence"),
    EdgeSpec("world_architecture", "architecture", "modeling_gate", "architecture"),
    EdgeSpec("shared_tool_semantics", "shared_tools", "modeling_gate", "shared_tools"),
    EdgeSpec("tool_semantics", "tool_semantics", "modeling_gate", "tool_semantics"),
    EdgeSpec("curriculum_plan", "curriculum", "modeling_gate", "curriculum"),
    EdgeSpec("task_requirement", "tasks", "modeling_gate", "tasks"),
    EdgeSpec("world_rules", "rules", "modeling_gate", "rules"),
)

CANDIDATE_EDGES = (
    EdgeSpec("build_plan", "build_plan", "candidate_build", "build_plan"),
    EdgeSpec("candidate_build", "candidate", "integration", "candidate"),
    EdgeSpec("candidate_build", "candidate", "judge", "candidate"),
    EdgeSpec("integration", "integration", "judge", "integration"),
    EdgeSpec("verifier_intent", "verifier", "judge", "verifier"),
    EdgeSpec("candidate_build", "candidate", "package", "candidate"),
    EdgeSpec("integration", "integration", "package", "integration"),
    EdgeSpec("judge", "judge", "package", "judge"),
    EdgeSpec("verifier_intent", "verifier", "package", "verifier"),
    EdgeSpec("package", "package", "registry", "package"),
    EdgeSpec("candidate_build", "candidate", "registry", "candidate"),
    EdgeSpec("integration", "integration", "registry", "integration"),
    EdgeSpec("judge", "judge", "registry", "judge"),
    EdgeSpec("verifier_intent", "verifier", "registry", "verifier"),
)

_OWNER_KINDS: dict[str, tuple[NodeOwner, ExecutionKind]] = {
    node.id: (node.owner, node.execution_kind) for node in (*DESIGN_NODES, *CANDIDATE_NODES)
}


class GraphRunner:
    """Validate one fixed graph and own each node transaction."""

    def __init__(
        self, graph_id: GraphId, nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...]
    ) -> None:
        self.graph_id = graph_id
        self.nodes = nodes
        self.edges = edges
        self._by_id = {node.id: node for node in nodes}
        self.resume: ResumeContext | None = None
        self._validate()

    def node(self, node_id: str) -> NodeSpec:
        try:
            return self._by_id[node_id]
        except KeyError as exc:
            raise ValueError("graph_node_unknown") from exc

    def _validate(self) -> None:
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("graph_duplicate_node")
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in ids}
        for node in self.nodes:
            if len(set(node.input_ports)) != len(node.input_ports) or len(
                set(node.output_ports)
            ) != len(node.output_ports):
                raise ValueError("graph_port_duplicate")
            if _OWNER_KINDS.get(node.id) != (node.owner, node.execution_kind):
                raise ValueError("graph_owner_kind_invalid")
        for edge in self.edges:
            if edge.source not in ids or edge.target not in ids:
                raise ValueError("graph_edge_unknown_node")
            source = self.node(edge.source)
            target = self.node(edge.target)
            if (
                edge.source_port not in source.output_ports
                or edge.target_port not in target.input_ports
            ):
                raise ValueError("graph_edge_port_invalid")
            if edge.condition != "passed":
                raise ValueError("graph_edge_condition_invalid")
            adjacency[edge.source].append(edge.target)
        indegree = {node_id: 0 for node_id in ids}
        for targets in adjacency.values():
            for target_id in targets:
                indegree[target_id] += 1
        queue: list[str] = [node_id for node_id, degree in indegree.items() if degree == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for target_id in adjacency[current]:
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    queue.append(target_id)
        if visited != len(ids):
            raise ValueError("graph_cycle")

    @staticmethod
    def semantic_revision(node: NodeSpec, semantic_material: Any) -> str:
        material_digest = sha256(canonical_json(semantic_material)).hexdigest()
        declaration = {
            "id": node.id,
            "owner": node.owner,
            "execution_kind": node.execution_kind,
            "input_ports": node.input_ports,
            "output_ports": node.output_ports,
            "output_contract": node.output_contract,
            # Prompt text and Skill contents never enter an Artifact.  Their
            # effective identities do, so semantic reuse cannot cross a route,
            # output-shape, projection, prompt, or mounted-Skill revision.
            "effective_projection_digest": material_digest,
            "output_shape": node.output_contract,
            "prompt_identity": node.prompt_id,
            "route": node.route,
            "agent_skill_digest": runtime_skill_digest(node.skill) if node.skill else None,
        }
        return "sha256:" + sha256(canonical_json(declaration)).hexdigest()

    def execute(
        self,
        store: ArtifactStore,
        run_id: str,
        node_id: str,
        inputs: Mapping[str, tuple[ArtifactRef, ...]],
        output_kind: str,
        operation: Callable[[CorrectionPacket | None], P],
        compiler: Callable[[P], T],
        semantic_material: Any,
        *,
        validator: Callable[[T], None] | None = None,
        artifact_projection: Callable[[T], Any] = json_value,
        operation_evidence: Callable[[P], tuple[OperationEvidence, ...]] | None = None,
        failure_subject: ArtifactRef | None = None,
        shard_key: str | None = None,
        output_type: Any = None,
    ) -> NodeResult[T]:
        """Execute and commit exactly one node proposal/validation transaction."""

        node = self.node(node_id)
        semantic = self.semantic_revision(node, semantic_material)

        # Resume short-circuit: skip upstream / committed-matching nodes.
        if self.resume is not None and output_type is not None:
            if self.resume.should_skip(self.graph_id, node_id, shard_key, semantic):
                head = self.resume.get_head(self.graph_id, node_id, shard_key)
                if head is not None:
                    compiled = from_value(head.compiled_json, output_type)
                    return NodeResult(
                        compiled, head.artifact_ref, head.work_ref, head.semantic_revision_digest
                    )

        dependencies = self._resolve_inputs(store, node, inputs)
        attempts: list[ArtifactRef] = []
        assurance_refs: list[ArtifactRef] = []
        correction: CorrectionPacket | None = None
        for ordinal in range(1, node.local_corrections + 2):
            semantic_rejection = False
            try:
                proposal = operation(correction)
                assurance_refs.extend(
                    self._persist_operation_evidence(store, operation_evidence, proposal)
                )
                semantic_rejection = True
                compiled = compiler(proposal)
                semantic_rejection = False
                if validator is not None:
                    validator(compiled)
            except NodeExecutionError as exc:
                eligible = self._eligible_local_correction(
                    node, exc, ordinal, correction, semantic_rejection
                )
                attempts.append(
                    store.put_json(
                        "control.attempt",
                        {
                            "graph": self.graph_id,
                            "node": node.id,
                            "shard": shard_key,
                            "semantic_revision_digest": semantic,
                            "invocation": ordinal,
                            "status": "correction_requested" if eligible else "failed",
                            "code": exc.code,
                            "correction": json_value(exc.correction) if eligible else None,
                        },
                    )
                )
                if eligible:
                    correction = exc.correction
                    continue
                evidence = store.put_json(
                    f"{output_kind}.failure",
                    {
                        "code": exc.code,
                        "evidence": json_value(
                            exc.evidence if exc.evidence is not None else exc.correction
                        ),
                    },
                )
                work = self.fail(
                    store,
                    run_id,
                    node_id,
                    dependencies,
                    exc.code,
                    subject_ref=failure_subject or dependencies[-1],
                    evidence_refs=(*attempts, *assurance_refs, evidence),
                    category="node_execution",
                    semantic_material=semantic_material,
                    shard_key=shard_key,
                )
                exc.node_id = node_id
                exc.artifact_refs = (*attempts, *assurance_refs, evidence, work)
                raise
            attempts.append(
                store.put_json(
                    "control.attempt",
                    {
                        "graph": self.graph_id,
                        "node": node.id,
                        "shard": shard_key,
                        "semantic_revision_digest": semantic,
                        "invocation": ordinal,
                        "status": "passed",
                        "code": None,
                        "correction": json_value(correction) if correction is not None else None,
                    },
                )
            )
            break
        else:  # pragma: no cover - the declared bounded loop always terminates above.
            raise AssertionError("graph_correction_loop_exhausted")
        compiled_digest = "sha256:" + sha256(canonical_json(compiled)).hexdigest()
        validation = store.put_json(
            "control.validation",
            {
                "node": node.id,
                "semantic_revision_digest": semantic,
                "compiled_digest": compiled_digest,
                "status": "passed",
            },
        )
        coordinate = WorkCoordinate(run_id, self.graph_id, node.id, shard_key, 1)
        output = store.put_envelope(
            ArtifactEnvelope(
                output_kind,
                1,
                coordinate,
                semantic,
                tuple(dependencies),
                node.output_ports,
                artifact_projection(compiled),
            )
        )
        record = store.put_work_record(
            WorkRecord(
                coordinate,
                node.owner,
                node.execution_kind,
                semantic,
                tuple(dependencies),
                tuple(dependencies),
                (output,),
                validation,
                tuple((*attempts, *assurance_refs)),
                (),
                "passed",
            )
        )
        if self.resume is not None:
            self.resume.record(
                self.graph_id,
                node_id,
                shard_key,
                compiled_json=json_value(compiled),
                artifact_ref=output,
                work_ref=record,
                semantic_revision_digest=semantic,
            )
        return NodeResult(compiled, output, record, semantic)

    def _resolve_inputs(
        self,
        store: ArtifactStore,
        node: NodeSpec,
        bindings: Mapping[str, tuple[ArtifactRef, ...]],
    ) -> tuple[ArtifactRef, ...]:
        """Cold-read only JSON/package bindings and validate literal graph ports."""

        allowed_ports = set(node.input_ports)
        required_ports = allowed_ports - set(node.optional_input_ports)
        if (
            not isinstance(bindings, Mapping)
            or not required_ports.issubset(bindings)
            or not set(bindings).issubset(allowed_ports)
        ):
            raise ValueError("graph_input_port_set_invalid")
        flattened: list[ArtifactRef] = []
        for port in node.input_ports:
            if port not in bindings:
                continue
            refs = bindings[port]
            if (
                not isinstance(refs, tuple)
                or (not refs and port not in node.optional_input_ports)
                or not all(isinstance(ref, ArtifactRef) for ref in refs)
            ):
                raise ValueError("graph_input_binding_invalid")
            if not refs:
                continue
            if len({ref.artifact_id for ref in refs}) != len(refs):
                raise ValueError("graph_input_binding_duplicate")
            edges = tuple(
                edge for edge in self.edges if edge.target == node.id and edge.target_port == port
            )
            expected_sources = {(edge.source, edge.source_port) for edge in edges}
            actual_sources: set[tuple[str, str]] = set()
            for ref in refs:
                if ref.media_type == "application/json":
                    value = store.read_json(ref)
                    is_envelope = isinstance(value, dict) and "producer" in value
                elif ref.media_type == "application/zip":
                    store.read_bytes(ref)
                    is_envelope = False
                else:
                    raise ValueError("graph_input_media_type_invalid")
                if edges:
                    if not is_envelope:
                        raise ValueError("graph_edge_envelope_required")
                    envelope = store.read_envelope(ref)
                    producer = envelope["producer"]
                    if producer["graph_id"] != self.graph_id:
                        raise ValueError("graph_edge_source_invalid")
                    producer_node = self.node(producer["node_id"])
                    if tuple(envelope["output_ports"]) != producer_node.output_ports:
                        raise ValueError("graph_envelope_output_ports_invalid")
                    matches = {
                        (edge.source, edge.source_port)
                        for edge in edges
                        if edge.source == producer["node_id"]
                        and edge.source_port in envelope["output_ports"]
                    }
                    if not matches:
                        raise ValueError("graph_edge_source_invalid")
                    actual_sources.update(matches)
                elif is_envelope:
                    producer = store.read_envelope(ref)["producer"]
                    if producer["graph_id"] == self.graph_id:
                        raise ValueError("graph_external_source_invalid")
                if ref not in flattened:
                    flattened.append(ref)
            if edges and actual_sources != expected_sources:
                raise ValueError("graph_edge_source_missing")
        return tuple(flattened)

    @staticmethod
    def _eligible_local_correction(
        node: NodeSpec,
        exc: NodeExecutionError,
        ordinal: int,
        previous_correction: CorrectionPacket | None,
        semantic_rejection: bool,
    ) -> bool:
        if not (
            node.execution_kind in {"direct_llm", "agent"}
            and exc.status == "rejected"
            and not exc.retryable
            and exc.correction is not None
        ):
            return False
        if ordinal == 1:
            return node.local_corrections >= 1 and (
                node.local_corrections != 2 or semantic_rejection
            )
        if not (
            ordinal == 2
            and node.execution_kind == "direct_llm"
            and node.route == "direct"
            and node.local_corrections == 2
            and semantic_rejection
            and previous_correction is not None
        ):
            return False
        if previous_correction.code == "direct_response_not_json":
            return True
        return exc.correction.code != "direct_response_not_json" and (
            previous_correction.code,
            previous_correction.path,
            previous_correction.violated_condition,
            previous_correction.expected_category,
        ) != (
            exc.correction.code,
            exc.correction.path,
            exc.correction.violated_condition,
            exc.correction.expected_category,
        )

    @staticmethod
    def _persist_operation_evidence(
        store: ArtifactStore,
        factory: Callable[[P], tuple[OperationEvidence, ...]] | None,
        proposal: P,
    ) -> tuple[ArtifactRef, ...]:
        if factory is None:
            return ()
        evidence = factory(proposal)
        if (
            not isinstance(evidence, tuple)
            or not evidence
            or not all(isinstance(item, OperationEvidence) for item in evidence)
        ):
            raise ValueError("graph_operation_evidence_invalid")
        return tuple(store.put_json("assurance.operation", item) for item in evidence)

    def fail(
        self,
        store: ArtifactStore,
        run_id: str,
        node_id: str,
        inputs: tuple[ArtifactRef, ...],
        code: str,
        *,
        subject_ref: ArtifactRef,
        evidence_refs: tuple[ArtifactRef, ...],
        category: str,
        severity: Literal["block_revision", "block_integration", "block_release"] = (
            "block_release"
        ),
        expected_condition: str = "node contract passes",
        semantic_material: Any = None,
        shard_key: str | None = None,
    ) -> ArtifactRef:
        """Commit a route-free Finding backed by real subject/evidence refs."""

        if not evidence_refs:
            raise ValueError("graph_failure_evidence_required")
        node = self.node(node_id)
        dependencies = inputs
        if not inputs or len({ref.artifact_id for ref in inputs}) != len(inputs):
            raise ValueError("graph_dependency_duplicate")
        for ref in inputs:
            if ref.media_type == "application/json":
                value = store.read_json(ref)
                if isinstance(value, dict) and "producer" in value:
                    store.read_envelope(ref)
            elif ref.media_type == "application/zip":
                store.read_bytes(ref)
            else:
                raise ValueError("graph_input_media_type_invalid")
        semantic = self.semantic_revision(node, semantic_material)
        validation = store.put_json(
            "control.validation",
            {
                "node": node.id,
                "semantic_revision_digest": semantic,
                "status": "failed",
                "code": code,
            },
        )
        fingerprint = digest_text(
            canonical_json(
                {
                    "node": node.id,
                    "subject": subject_ref.digest,
                    "evidence": [ref.digest for ref in evidence_refs],
                    "code": code,
                }
            ).decode("utf-8")
        )
        finding = Finding(
            f"finding_{fingerprint[7:23]}",
            validation,
            subject_ref,
            evidence_refs,
            expected_condition,
            node.owner,
            code,
            category,
            severity,
            True,
            fingerprint,
        )
        finding_ref = store.put_json("control.finding", finding)
        coordinate = WorkCoordinate(run_id, self.graph_id, node.id, shard_key, 1)
        return store.put_work_record(
            WorkRecord(
                coordinate,
                node.owner,
                node.execution_kind,
                semantic,
                tuple(inputs),
                tuple(dependencies),
                (),
                validation,
                evidence_refs,
                (finding_ref,),
                "failed",
                code,
            )
        )

    def not_run(
        self,
        store: ArtifactStore,
        run_id: str,
        node_id: str,
        *,
        shard_key: str | None = None,
        code: str | None = None,
    ) -> ArtifactRef:
        node = self.node(node_id)
        coordinate = WorkCoordinate(run_id, self.graph_id, node.id, shard_key, 1)
        semantic = self.semantic_revision(node, {"not_run": True})
        return store.put_work_record(
            WorkRecord(
                coordinate,
                node.owner,
                node.execution_kind,
                semantic,
                (),
                (),
                (),
                None,
                (),
                (),
                "not_run",
                code,
            )
        )


def design_graph() -> GraphRunner:
    return GraphRunner("design", DESIGN_NODES, DESIGN_EDGES)


def candidate_graph() -> GraphRunner:
    return GraphRunner("candidate", CANDIDATE_NODES, CANDIDATE_EDGES)
