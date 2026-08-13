"""Tests for from_value round-trip and the resume/restart-from-node feature."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_world.artifacts import ArtifactStore
from agent_world.contracts import (
    ArtifactRef,
    AssuranceRecipe,
    CandidateManifest,
    CitationCatalog,
    CitationCatalogItem,
    CorrectionPacket,
    CurriculumFamily,
    CurriculumPlan,
    DesignContract,
    DifficultyDimension,
    DifficultyLevel,
    EntityDeclaration,
    EvaluatorGoalBinding,
    EvidenceClaim,
    EvidenceGraph,
    ExecutableTaskContract,
    FieldDeclaration,
    GateResult,
    JudgeReport,
    OperationEvidence,
    RegistryReceipt,
    RewardSpec,
    RuleDraft,
    SemanticBinding,
    SemanticCatalog,
    SharedToolContract,
    TaskRequirement,
    TerminationSpec,
    ToolCouplingPlan,
    ToolDraft,
    ToolSurface,
    VerificationRequirements,
    VerifierBundle,
    VerifierCommitment,
    WorldArchitecture,
    WorldBoundary,
    WorldRuleSet,
    compile_difficulty_schema,
    digest_value,
    from_value,
    json_value,
)
from agent_world.graph import (
    CANDIDATE_EDGES,
    CANDIDATE_NODES,
    DESIGN_EDGES,
    DESIGN_NODES,
    ResumeContext,
    compute_upstream,
    design_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


def _ref(name: str) -> ArtifactRef:
    return ArtifactRef(name, "test.contract", _digest("a"), f"artifacts/{name}.json")


def _rule() -> RuleDraft:
    return RuleDraft((), (), None, "bounded semantic rule", (1,))


def _evidence() -> EvidenceGraph:
    catalog = CitationCatalog(
        (CitationCatalogItem(1, "docs", "https://example.test", "evidence"),)
    )
    return EvidenceGraph(
        (EvidenceClaim("the workflow has two tools", "observed", (1,)),),
        (),
        ("concurrency is bounded",),
        catalog,
        _ref("evidence"),
    )


def _architecture() -> WorldArchitecture:
    field = FieldDeclaration("request_id", "identifier", True)
    return WorldArchitecture(
        WorldBoundary("support", "manage records", "support-db", "operator", ("operator",)),
        (EntityDeclaration("record", "a support record", (field,)),),
        (
            ToolSurface(1, "create", "create a record", (1,), (field,), (field,)),
            ToolSurface(2, "close", "close a record", (1,), (field,), (field,)),
        ),
        (),
        SemanticCatalog((SemanticBinding(1, "argument", "request_id", ("request_id",)),)),
        ToolCouplingPlan(((1, 2),)),
        _ref("architecture"),
    )


def _shared() -> SharedToolContract:
    return SharedToolContract(
        (1, 2),
        ((1, 2),),
        ((1, 2),),
        ((1, 2),),
        (),
        (),
        ((1, "reject invalid create"), (2, "reject invalid close")),
        _digest("b"),
        _ref("shared"),
    )


def _design() -> DesignContract:
    evidence = _evidence()
    architecture = _architecture()
    shared = _shared()
    surface_a = architecture.tools[0]
    surface_b = architecture.tools[1]
    tool_a = ToolDraft(
        1, surface_a, architecture.catalog.bindings,
        (_rule(),), (_rule(),), (), (), shared.digest, _digest("c"),
    )
    tool_b = ToolDraft(
        2, surface_b, architecture.catalog.bindings,
        (_rule(),), (_rule(),), (), (), shared.digest, _digest("d"),
    )
    world_rules = WorldRuleSet((), (_rule(),), _digest("e"), _ref("rules"))
    schema = compile_difficulty_schema(
        "resolve-record",
        (DifficultyDimension(
            "urgency", "how urgent",
            (DifficultyLevel("low", "normal"), DifficultyLevel("high", "urgent")),
        ),),
    )
    family = CurriculumFamily(
        1, "resolve-record", "resolve the public record", 1, (1, 2), schema, "sample", (1,)
    )
    curriculum = CurriculumPlan((family,), _ref("curriculum"))
    requirement = TaskRequirement(1, (1,), (), (_rule(),), (), (_rule(),), _ref("task"))
    recipe_a = AssuranceRecipe(
        1, 1, _digest("f"), schema.schema_digest, _digest("c"), "operator",
        (("urgency", "low"),), (("urgency", "high"),), (1, 2), _digest("1"),
    )
    recipe_b = AssuranceRecipe(
        1, 2, _digest("f"), schema.schema_digest, _digest("d"), "operator",
        (("urgency", "low"),), (("urgency", "high"),), (1, 2), _digest("2"),
    )
    requirements = VerificationRequirements(
        1, True, (recipe_a.recipe_digest, recipe_b.recipe_digest)
    )
    reward = RewardSpec()
    termination = TerminationSpec()
    executable = ExecutableTaskContract(
        1, requirement,
        (("/request_id", "identifier"),),
        (("/record/request_id", "identifier"),),
        (EvaluatorGoalBinding("/request_id", "/request_id"),),
        _digest("3"), reward, digest_value(reward),
        termination, digest_value(termination),
        requirements, digest_value(requirements),
    )
    return DesignContract(
        evidence, architecture, (shared,), (tool_a, tool_b),
        world_rules, curriculum, (requirement,), (executable,),
        (recipe_a, recipe_b), _ref("design"),
    )


# ---------------------------------------------------------------------------
# from_value round-trip tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "instance,type_hint",
    [
        (_ref("test"), ArtifactRef),
        (_rule(), RuleDraft),
        (_evidence(), EvidenceGraph),
        (_architecture(), WorldArchitecture),
        (_shared(), SharedToolContract),
        (_design(), DesignContract),
        (
            CorrectionPacket("bad_code", "$.field", "must be present", "string"),
            CorrectionPacket,
        ),
        (
            OperationEvidence("direct_llm", "test_node", "test-model", {"total_tokens": 10}),
            OperationEvidence,
        ),
        (
            CandidateManifest(
                "main.py", _digest("x"),
                ({"path": "main.py", "digest": _digest("x"), "size": 100},),
                _ref("manifest"),
            ),
            CandidateManifest,
        ),
        (
            JudgeReport(
                _digest("c"),
                (GateResult("gate_1", "passed", None, _ref("evidence")),),
                _ref("judge"),
            ),
            JudgeReport,
        ),
        (
            VerifierBundle(
                (VerifierCommitment(
                    "verifier-test", 1, 1, "unknown_seed", None, "risk", _digest("a"),
                ),),
                _ref("verifier"),
            ),
            VerifierBundle,
        ),
        (
            RegistryReceipt(
                "pkg-1", "1.0.0", _digest("p"), _digest("m"), "rev-1", "2025-01-01T00:00:00Z",
            ),
            RegistryReceipt,
        ),
    ],
    ids=lambda inst: type(inst).__name__ if not isinstance(inst, tuple) else "tuple",
)
def test_from_value_round_trip(instance: Any, type_hint: Any) -> None:
    """from_value(json_value(x), T) == x for representative contract instances."""
    serialized = json_value(instance)
    reconstructed = from_value(serialized, type_hint)
    assert reconstructed == instance


def test_from_value_tuple_of_dataclasses() -> None:
    """from_value handles tuple[X, ...] of dataclasses."""
    refs = (_ref("a"), _ref("b"))
    serialized = json_value(refs)
    reconstructed = from_value(serialized, tuple[ArtifactRef, ...])
    assert reconstructed == refs
    assert isinstance(reconstructed, tuple)


def test_from_value_optional_none() -> None:
    """from_value handles Optional types with None."""
    assert from_value(None, str | None) is None
    assert from_value("hello", str | None) == "hello"


def test_from_value_dict_of_int() -> None:
    """from_value handles dict[str, int]."""
    original = {"a": 1, "b": 2}
    reconstructed = from_value(original, dict[str, int])
    assert reconstructed == original


# ---------------------------------------------------------------------------
# Resume infrastructure tests
# ---------------------------------------------------------------------------

def test_compute_upstream_design_node() -> None:
    """Upstream of a design node excludes the node itself and all downstream."""
    upstream = compute_upstream(
        "world_architecture", DESIGN_NODES, DESIGN_EDGES, CANDIDATE_NODES, CANDIDATE_EDGES
    )
    assert "world_architecture" not in upstream
    assert "research_plan" in upstream
    assert "research_acquire" in upstream
    assert "research_synthesis" in upstream
    assert "modeling_gate" not in upstream
    # No candidate nodes when restart is in design
    assert not (upstream & {n.id for n in CANDIDATE_NODES})


def test_compute_upstream_candidate_node() -> None:
    """Upstream of a candidate node includes ALL design nodes."""
    upstream = compute_upstream(
        "judge", DESIGN_NODES, DESIGN_EDGES, CANDIDATE_NODES, CANDIDATE_EDGES
    )
    assert "judge" not in upstream
    # All design nodes are upstream of candidate nodes
    assert {n.id for n in DESIGN_NODES}.issubset(upstream)
    assert "build_plan" in upstream
    assert "candidate_build" in upstream
    assert "integration" in upstream
    assert "verifier_intent" in upstream


def test_compute_upstream_unknown_node() -> None:
    with pytest.raises(ValueError, match="resume_unknown_node"):
        compute_upstream(
            "nonexistent", DESIGN_NODES, DESIGN_EDGES, CANDIDATE_NODES, CANDIDATE_EDGES
        )


def test_resume_context_save_load_round_trip(tmp_path: Path) -> None:
    """ResumeContext persists and loads correctly."""
    ctx = ResumeContext(restart_from="world_architecture")
    ctx.record(
        "design", "research_plan", None,
        compiled_json={"queries": ["q1"], "questions": ["a?"]},
        artifact_ref=_ref("plan"),
        work_ref=_ref("plan_work"),
        semantic_revision_digest=_digest("s"),
    )
    heads_path = tmp_path / "heads.json"
    ctx.save(heads_path)
    loaded = ResumeContext.load(heads_path)
    assert loaded.restart_from == "world_architecture"
    head = loaded.get_head("design", "research_plan", None)
    assert head is not None
    assert head.artifact_ref == _ref("plan")
    assert head.compiled_json == {"queries": ["q1"], "questions": ["a?"]}


def test_resume_context_should_skip_pure_resume() -> None:
    """Pure resume (no restart_from) skips nodes with matching semantic."""
    ctx = ResumeContext()
    ctx.record(
        "design", "research_plan", None,
        compiled_json={},
        artifact_ref=_ref("plan"),
        work_ref=_ref("work"),
        semantic_revision_digest=_digest("s"),
    )
    # Matching semantic → skip
    assert ctx.should_skip("design", "research_plan", None, _digest("s"))
    # Mismatched semantic → don't skip (inputs changed)
    assert not ctx.should_skip("design", "research_plan", None, _digest("x"))
    # No head → don't skip
    assert not ctx.should_skip("design", "world_architecture", None, _digest("s"))


def test_resume_context_should_skip_restart_from() -> None:
    """--from mode skips upstream nodes, re-runs from target onward."""
    upstream = compute_upstream(
        "world_architecture", DESIGN_NODES, DESIGN_EDGES, CANDIDATE_NODES, CANDIDATE_EDGES
    )
    ctx = ResumeContext(restart_from="world_architecture", skip_node_ids=upstream)
    ctx.record(
        "design", "research_plan", None,
        compiled_json={},
        artifact_ref=_ref("plan"),
        work_ref=_ref("work"),
        semantic_revision_digest=_digest("s"),
    )
    # Upstream node with head → skip
    assert ctx.should_skip("design", "research_plan", None, _digest("s"))
    # The restart target itself → never skip
    ctx.record(
        "design", "world_architecture", None,
        compiled_json={},
        artifact_ref=_ref("arch"),
        work_ref=_ref("arch_work"),
        semantic_revision_digest=_digest("s"),
    )
    assert not ctx.should_skip("design", "world_architecture", None, _digest("s"))


# ---------------------------------------------------------------------------
# Graph execute skip integration test
# ---------------------------------------------------------------------------

def test_graph_execute_skips_on_resume(tmp_path: Path) -> None:
    """graph.execute returns cached result when resume says skip."""
    store = ArtifactStore(tmp_path)
    graph = design_graph()

    # Manually record a head for "research_synthesis"
    compiled_evidence = _evidence()
    artifact = _ref("evidence")
    work = _ref("evidence_work")
    semantic = graph.semantic_revision(
        graph.node("research_synthesis"), {"test": True}
    )
    resume = ResumeContext()
    resume.record(
        "design", "research_synthesis", None,
        compiled_json=json_value(compiled_evidence),
        artifact_ref=artifact,
        work_ref=work,
        semantic_revision_digest=semantic,
    )
    graph.resume = resume

    # Execute should skip (matching semantic) and return cached result
    def operation(_: Any) -> str:
        pytest.fail("operation should not be called during skip")

    def compiler(_: str) -> EvidenceGraph:
        pytest.fail("compiler should not be called during skip")

    request_ref = _ref("request")
    result = graph.execute(
        store, "test-run", "research_synthesis",
        {"request": (request_ref,), "research_plan": (_ref("plan"),),
         "sources": (_ref("acq"),), "citations": (_ref("acq"),)},
        "design.evidence_graph",
        operation, compiler,
        {"test": True},  # semantic_material matches what we recorded
        output_type=EvidenceGraph,
    )
    # The result should be the cached evidence
    assert result.artifact == artifact
    assert result.work == work
    assert result.value.claims == compiled_evidence.claims


def test_resume_head_recorded_after_commit(tmp_path: Path) -> None:
    """After a successful execute (non-skip), the head is recorded on the resume context."""
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    resume = ResumeContext()
    graph.resume = resume

    # Build proper envelope inputs for research_synthesis.
    from agent_world.contracts import ArtifactEnvelope, WorkCoordinate

    coord_plan = WorkCoordinate("test-run", "design", "research_plan", None, 1)
    coord_acq = WorkCoordinate("test-run", "design", "research_acquire", None, 1)
    request_ref = store.put_json("control.design_request", {"need_digest": _digest("a")})
    plan_ref = store.put_envelope(
        ArtifactEnvelope(
            "design.research_plan", 1, coord_plan, _digest("a"), (), ("research_plan",), {}
        )
    )
    acq_ref = store.put_envelope(
        ArtifactEnvelope(
            "design.research_acquire", 1, coord_acq, _digest("a"), (),
            ("sources", "citations"), {},
        )
    )

    def operation(_: Any) -> str:
        return "proposal"

    def compiler(_: str) -> EvidenceGraph:
        return _evidence()

    result = graph.execute(
        store, "test-run", "research_synthesis",
        {
            "request": (request_ref,),
            "research_plan": (plan_ref,),
            "sources": (acq_ref,),
            "citations": (acq_ref,),
        },
        "design.evidence_graph",
        operation, compiler,
        {"new": True},
        output_type=EvidenceGraph,
    )
    head = resume.get_head("design", "research_synthesis", None)
    assert head is not None
    assert head.artifact_ref == result.artifact
    assert head.semantic_revision_digest == result.semantic_revision_digest
    # The compiled_json should round-trip back to the original value.
    reconstructed = from_value(head.compiled_json, EvidenceGraph)
    assert reconstructed == result.value
