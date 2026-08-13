from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

import agent_world.candidate as candidate_module
import agent_world.design as design_module
from agent_world.artifacts import ArtifactIntegrityError, ArtifactStore
from agent_world.contracts import (
    ArtifactEnvelope,
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
    EntityDeclaration,
    EvaluatorGoalBinding,
    EvidenceClaim,
    EvidenceGraph,
    ExecutableTaskContract,
    FieldDeclaration,
    GraphId,
    OperationEvidence,
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
    WorkCoordinate,
    WorldArchitecture,
    WorldBoundary,
    WorldRuleSet,
    compile_difficulty_schema,
    digest_value,
    json_value,
)
from agent_world.graph import (
    CANDIDATE_NODES,
    DESIGN_NODES,
    GraphRunner,
    NodeExecutionError,
    NodeSpec,
    candidate_graph,
    design_graph,
)
from agent_world.invocation import InvocationResult


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


def _ref(name: str) -> ArtifactRef:
    return ArtifactRef(name, "test.contract", _digest("a"), f"artifacts/{name}.json")


def _rule() -> RuleDraft:
    return RuleDraft((), (), None, "bounded semantic rule", (1,))


def _design() -> DesignContract:
    catalog = CitationCatalog((CitationCatalogItem(1, "docs", "https://example.test", "evidence"),))
    evidence = EvidenceGraph(
        (EvidenceClaim("the workflow has two tools", "observed", (1,)),),
        (),
        ("concurrency is bounded",),
        catalog,
        _ref("evidence"),
    )
    field = FieldDeclaration("request_id", "identifier", True)
    surface_a = ToolSurface(1, "create", "create a record", (1,), (field,), (field,))
    surface_b = ToolSurface(2, "close", "close a record", (1,), (field,), (field,))
    architecture = WorldArchitecture(
        WorldBoundary("support", "manage records", "support-db", "operator", ("operator",)),
        (EntityDeclaration("record", "a support record", (field,)),),
        (surface_a, surface_b),
        (),
        SemanticCatalog((SemanticBinding(1, "argument", "request_id", ("request_id",)),)),
        ToolCouplingPlan(((1, 2),)),
        _ref("architecture"),
    )
    shared = SharedToolContract(
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
    tool_a = ToolDraft(
        1,
        surface_a,
        architecture.catalog.bindings,
        (_rule(),),
        (_rule(),),
        (),
        (),
        shared.digest,
        _digest("c"),
    )
    tool_b = ToolDraft(
        2,
        surface_b,
        architecture.catalog.bindings,
        (_rule(),),
        (_rule(),),
        (),
        (),
        shared.digest,
        _digest("d"),
    )
    world_rules = WorldRuleSet((), (_rule(),), _digest("e"), _ref("rules"))
    schema = compile_difficulty_schema(
        "resolve-record",
        (
            DifficultyDimension(
                "urgency",
                "how urgent the record is",
                (DifficultyLevel("low", "normal"), DifficultyLevel("high", "urgent")),
            ),
        ),
    )
    family = CurriculumFamily(
        1, "resolve-record", "resolve the public record", 1, (1, 2), schema, "sample records", (1,)
    )
    curriculum = CurriculumPlan((family,), _ref("curriculum"))
    requirement = TaskRequirement(1, (1,), (), (_rule(),), (), (_rule(),), _ref("task"))
    recipe_a = AssuranceRecipe(
        1,
        1,
        _digest("f"),
        schema.schema_digest,
        _digest("c"),
        "operator",
        (("urgency", "low"),),
        (("urgency", "high"),),
        (1, 2),
        _digest("1"),
    )
    recipe_b = AssuranceRecipe(
        1,
        2,
        _digest("f"),
        schema.schema_digest,
        _digest("d"),
        "operator",
        (("urgency", "low"),),
        (("urgency", "high"),),
        (1, 2),
        _digest("2"),
    )
    requirements = VerificationRequirements(
        1, True, (recipe_a.recipe_digest, recipe_b.recipe_digest)
    )
    reward = RewardSpec()
    termination = TerminationSpec()
    executable = ExecutableTaskContract(
        1,
        requirement,
        (("/request_id", "identifier"),),
        (("/record/request_id", "identifier"),),
        (EvaluatorGoalBinding("/request_id", "/request_id"),),
        _digest("3"),
        reward,
        digest_value(reward),
        termination,
        digest_value(termination),
        requirements,
        digest_value(requirements),
    )
    return DesignContract(
        evidence,
        architecture,
        (shared,),
        (tool_a, tool_b),
        world_rules,
        curriculum,
        (requirement,),
        (executable,),
        (recipe_a, recipe_b),
        _ref("design"),
    )


def test_design_contract_closes_all_families_tools_and_recipe_order() -> None:
    design = _design()

    assert [
        (recipe.task_family_index, recipe.tool_index) for recipe in design.assurance_recipes
    ] == [
        (1, 1),
        (1, 2),
    ]
    assert design.executable_tasks[0].verification_requirements.required_recipe_digests == tuple(
        recipe.recipe_digest for recipe in design.assurance_recipes
    )

    with pytest.raises(ValueError, match="design_assurance_recipe_order_invalid"):
        replace(design, assurance_recipes=tuple(reversed(design.assurance_recipes)))
    with pytest.raises(ValueError, match="design_verification_recipe_binding_invalid"):
        bad_requirements = replace(
            design.executable_tasks[0].verification_requirements,
            required_recipe_digests=(_digest("2"), _digest("1")),
        )
        bad_task = replace(
            design.executable_tasks[0],
            verification_requirements=bad_requirements,
            verification_digest=digest_value(bad_requirements),
        )
        replace(design, executable_tasks=(bad_task,))


def test_executable_task_exact_reward_termination_and_verification_digests() -> None:
    executable = _design().executable_tasks[0]

    with pytest.raises(ValueError, match="reward_digest_invalid"):
        replace(executable, reward_digest=_digest("9"))
    with pytest.raises(ValueError, match="termination_spec_invalid"):
        TerminationSpec(terminate_on=("success", "failure", "terminal"))
    with pytest.raises(ValueError, match="verification_requirements_invalid"):
        VerificationRequirements(1, True, (), ("task_materialization", "task_reachability"))
    with pytest.raises(ValueError, match="reward_spec_invalid"):
        RewardSpec(success=cast(Literal[1], 0))


def test_closed_architecture_and_shared_contract_reject_invalid_references() -> None:
    design = _design()
    architecture = design.architecture

    with pytest.raises(ValueError, match="world_architecture_actor_reference_invalid"):
        bad_surface = replace(architecture.tools[0], actor_indexes=(2,))
        WorldArchitecture(
            architecture.boundary,
            architecture.entities,
            (bad_surface, architecture.tools[1]),
            architecture.known_divergences,
            architecture.catalog,
            architecture.coupling_plan,
            architecture.artifact,
        )
    with pytest.raises(ValueError, match="tool_coupling_plan_invalid"):
        replace(architecture, coupling_plan=ToolCouplingPlan(()))
    with pytest.raises(ValueError, match="design_shared_contract_order_invalid"):
        replace(design, shared_tool_contracts=())


def test_public_verifier_commitment_binds_one_recipe_and_preserves_artifact_reference() -> None:
    recipe = _design().assurance_recipes[0]
    commitment = VerifierCommitment(
        "verifier-unknown-seed",
        1,
        1,
        "unknown_seed",
        None,
        "exercise public runtime behavior",
        recipe.recipe_digest,
    )
    bundle = VerifierBundle((commitment,), _ref("verifier"))

    assert bundle.artifact == _ref("verifier")
    assert bundle.commitments[0].baseline_recipe_digest == recipe.recipe_digest
    with pytest.raises(ValueError, match="verifier_bundle_commitment_invalid"):
        VerifierBundle((commitment, commitment), _ref("duplicate-verifier"))
    with pytest.raises(ValueError, match="verifier_commitment_recipe_digest_invalid"):
        replace(commitment, baseline_recipe_digest="not-a-digest")


def _envelope(
    store: ArtifactStore,
    node_id: str,
    *,
    graph_id: GraphId = "design",
    shard_key: str | None = None,
    output_ports: tuple[str, ...] | None = None,
) -> ArtifactRef:
    graph = design_graph() if graph_id == "design" else candidate_graph()
    node = graph.node(node_id)
    return store.put_envelope(
        ArtifactEnvelope(
            "test.output",
            1,
            WorkCoordinate("run-ports", graph_id, node_id, shard_key, 1),
            _digest("a"),
            (),
            output_ports or node.output_ports,
            {"closed": True},
        )
    )


def test_shared_tools_are_the_only_declared_optional_input_ports(tmp_path) -> None:
    graph = design_graph()
    node, gate = graph.node("tool_semantics"), graph.node("modeling_gate")
    assert node.optional_input_ports == gate.optional_input_ports == ("shared_tools",)
    assert all(
        not item.optional_input_ports for item in graph.nodes if item.id not in {node.id, gate.id}
    )
    with pytest.raises(ValueError, match="graph_optional_port_invalid"):
        NodeSpec(
            "other",
            "designer",
            "framework",
            ("input",),
            ("output",),
            "Closed@1",
            local_corrections=0,
            optional_input_ports=("input",),
        )

    store = ArtifactStore(tmp_path)
    architecture = _envelope(store, "world_architecture")
    evidence = _envelope(store, "research_synthesis")
    result = graph.execute(
        store,
        "run-ports",
        "tool_semantics",
        {"architecture": (architecture,), "evidence": (evidence,)},
        "design.tool_semantics",
        lambda _correction: {"closed": True},
        lambda proposal: proposal,
        {"projection": "closed"},
    )
    assert result.value == {"closed": True}
    empty = graph.execute(
        store,
        "run-ports-empty",
        "tool_semantics",
        {"architecture": (architecture,), "shared_tools": (), "evidence": (evidence,)},
        "design.tool_semantics",
        lambda _correction: {"closed": True},
        lambda proposal: proposal,
        {"projection": "closed"},
    )
    assert empty.value == {"closed": True}
    with pytest.raises(ValueError, match="graph_input_port_set_invalid"):
        graph._resolve_inputs(
            store,
            node,
            {
                "architecture": (architecture,),
                "shared_tools": (),
                "evidence": (evidence,),
                "extra": (evidence,),
            },
        )
    with pytest.raises(ValueError, match="graph_input_binding_invalid"):
        graph._resolve_inputs(store, node, {"architecture": (), "evidence": (evidence,)})


def test_two_fixed_graphs_use_one_node_and_edge_abstraction() -> None:
    assert design_graph().graph_id == "design"
    assert candidate_graph().graph_id == "candidate"
    assert {node.id for node in DESIGN_NODES} == {
        "research_plan",
        "research_acquire",
        "research_synthesis",
        "world_architecture",
        "shared_tool_semantics",
        "tool_semantics",
        "world_rules",
        "curriculum_plan",
        "task_requirement",
        "modeling_gate",
    }
    candidate = {node.id: node for node in CANDIDATE_NODES}
    design = {node.id: node for node in DESIGN_NODES}
    assert {
        node_id: (node.input_ports, node.route, node.skill) for node_id, node in design.items()
    } == {
        "research_plan": (("request",), "agent", "research-world-evidence"),
        "research_acquire": (("research_plan",), None, None),
        "research_synthesis": (
            ("request", "research_plan", "sources", "citations"),
            "agent",
            "research-world-evidence",
        ),
        "world_architecture": (("request", "evidence", "coverage"), "direct", None),
        "shared_tool_semantics": (("architecture", "evidence"), "direct", None),
        "tool_semantics": (("architecture", "shared_tools", "evidence"), "direct", None),
        "world_rules": (("architecture", "tool_semantics"), "direct", None),
        "curriculum_plan": (("architecture", "rules", "evidence"), "direct", None),
        "task_requirement": (
            ("architecture", "tool_semantics", "curriculum", "rules", "evidence"),
            "direct",
            None,
        ),
        "modeling_gate": (
            (
                "evidence",
                "architecture",
                "shared_tools",
                "tool_semantics",
                "curriculum",
                "tasks",
                "rules",
            ),
            None,
            None,
        ),
    }
    assert {
        edge.target
        for edge in design_graph().edges
        if edge.source == "research_synthesis" and edge.source_port == "evidence"
    } == {
        "world_architecture",
        "shared_tool_semantics",
        "tool_semantics",
        "curriculum_plan",
        "task_requirement",
        "modeling_gate",
    }
    assert ("shared_tool_semantics", "shared_tools", "modeling_gate", "shared_tools") in {
        (edge.source, edge.source_port, edge.target, edge.target_port)
        for edge in design_graph().edges
    }
    assert candidate["candidate_build"].input_ports == ("design", "build_plan")
    assert candidate["integration"].input_ports == ("design", "candidate")
    assert candidate["verifier_intent"].owner == "designer"
    assert not hasattr(design_graph(), "schedule")
    assert not hasattr(design_graph(), "register_handler")


@pytest.mark.parametrize(
    ("node_id", "port_sources"),
    (
        ("shared_tool_semantics", {"architecture": "world_architecture"}),
        (
            "curriculum_plan",
            {"architecture": "world_architecture", "rules": "world_rules"},
        ),
        (
            "task_requirement",
            {
                "architecture": "world_architecture",
                "tool_semantics": "tool_semantics",
                "curriculum": "curriculum_plan",
                "rules": "world_rules",
            },
        ),
    ),
)
def test_evidence_only_change_is_a_declared_dependency_and_semantic_identity(
    tmp_path, node_id: str, port_sources: dict[str, str]
) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    source_refs = {
        port: _envelope(store, source, shard_key="one" if port == "tool_semantics" else None)
        for port, source in port_sources.items()
    }

    def evidence(revision: int, marker: str) -> ArtifactRef:
        return store.put_envelope(
            ArtifactEnvelope(
                "test.evidence",
                1,
                WorkCoordinate("run-evidence", "design", "research_synthesis", None, revision),
                _digest(marker),
                (),
                ("evidence", "coverage"),
                {"catalog": marker},
            )
        )

    first_evidence, second_evidence = evidence(1, "a"), evidence(2, "b")

    def execute(run_id: str, evidence_ref: ArtifactRef, marker: str):
        return graph.execute(
            store,
            run_id,
            node_id,
            {**{port: (ref,) for port, ref in source_refs.items()}, "evidence": (evidence_ref,)},
            f"design.{node_id}",
            lambda _correction: {"closed": True},
            lambda proposal: proposal,
            {"effective_projection": {"citation_catalog": {"marker": marker}}},
        )

    first = execute("run-evidence-one", first_evidence, "one")
    second = execute("run-evidence-two", second_evidence, "two")
    first_work, second_work = store.read_json(first.work), store.read_json(second.work)
    assert first.semantic_revision_digest != second.semantic_revision_digest
    assert first_work["dependency_refs"][-1]["artifact_id"] == first_evidence.artifact_id
    assert second_work["dependency_refs"][-1]["artifact_id"] == second_evidence.artifact_id


def test_runner_commits_only_compiled_envelopes_with_closed_provenance(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    request = store.put_json("control.design_request", {"need_digest": _digest("1")})
    validated: list[tuple[str, ...]] = []
    result = graph.execute(
        store,
        "run-compiled",
        "research_plan",
        {"request": (request,)},
        "design.research_plan",
        lambda _correction: {"queries": ["trusted"], "raw": "drop"},
        lambda value: tuple(value["queries"]),
        {"effective_projection": {"need": "digest-only"}},
        validator=validated.append,
    )

    envelope = store.read_envelope(result.artifact)
    assert envelope["payload"] == ["trusted"]
    assert envelope["output_ports"] == ["research_plan"]
    assert [item["artifact_id"] for item in envelope["dependencies"]] == [request.artifact_id]
    work = store.read_json(result.work)
    assert work["input_refs"] == envelope["dependencies"]
    assert work["dependency_refs"] == envelope["dependencies"]
    assert work["output_refs"][0]["artifact_id"] == result.artifact.artifact_id
    assert validated == [("trusted",)]
    assert result.semantic_revision_digest != graph.semantic_revision(
        graph.node("research_plan"), {"effective_projection": {"need": "changed"}}
    )


def test_envelope_output_ports_are_closed_at_write_and_cold_read(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    coordinate = WorkCoordinate("run-envelope", "design", "research_plan", None, 1)
    with pytest.raises(ValueError, match="artifact_output_ports_invalid"):
        ArtifactEnvelope("test.output", 1, coordinate, _digest("a"), (), (), {})
    malformed = store.put_json(
        "test.output",
        {
            "schema_version": 1,
            "producer": json_value(coordinate),
            "semantic_revision_digest": _digest("a"),
            "dependencies": [],
            "output_ports": ["research_plan", "research_plan"],
            "payload": {},
        },
    )
    with pytest.raises(ArtifactIntegrityError, match="artifact_envelope_invalid"):
        store.read_envelope(malformed)


def test_runner_records_route_free_failure_and_not_run(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = candidate_graph()
    design = store.put_json("design.environment_design", {"closed": True})
    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-failure",
            "build_plan",
            {"design": (design,)},
            "candidate.build_plan",
            lambda _correction: (_ for _ in ()).throw(NodeExecutionError("proposal_rejected")),
            lambda value: value,
            {"projection": "closed"},
        )
    work = store.read_json(raised.value.artifact_refs[-1])
    finding = store.read_json(ArtifactRef(**work["finding_refs"][0]))
    assert work["status"] == "failed"
    assert "target_node" not in finding
    assert set(finding) == {
        "finding_id",
        "failed_claim_ref",
        "subject_ref",
        "evidence_refs",
        "expected_condition",
        "owner",
        "code",
        "category",
        "severity",
        "blocks_release",
        "fingerprint",
    }
    not_run = store.read_json(
        graph.not_run(store, "run-failure", "judge", code="integration_failed")
    )
    assert not_run["status"] == "not_run"
    assert not not_run["output_refs"] and not not_run["finding_refs"]


def test_runner_fail_cold_reads_zip_dependency_and_commits_failed_work(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = candidate_graph()
    package = store.put_bytes("registry.package", b"package", media_type="application/zip")
    evidence = store.put_json("test.failure_evidence", {"safe": True})

    work_ref = graph.fail(
        store,
        "run-zip-failure",
        "registry",
        (package,),
        "registry_physical_package_mismatch",
        subject_ref=package,
        evidence_refs=(evidence,),
        category="node_execution",
    )

    work = store.read_json(work_ref)
    validation = store.read_json(ArtifactRef(**work["validation_ref"]))
    finding = store.read_json(ArtifactRef(**work["finding_refs"][0]))
    assert work["status"] == "failed"
    assert work["dependency_refs"] == [json_value(package)]
    assert validation["status"] == "failed"
    assert validation["code"] == "registry_physical_package_mismatch"
    assert finding["subject_ref"] == json_value(package)
    assert finding["evidence_refs"] == [json_value(evidence)]


def test_runner_requires_closed_named_ports_and_literal_edge_producers(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = candidate_graph()
    design = store.put_json("design.environment_design", {"closed": True})

    def operation(_correction: CorrectionPacket | None) -> dict[str, bool]:
        return {"closed": True}

    def compiler(value: object) -> object:
        return value

    for bindings in (
        {"design": (design,)},
        {"design": (design,), "build_plan": (design,), "extra": (design,)},
    ):
        with pytest.raises(ValueError, match="graph_input_port_set_invalid"):
            graph.execute(
                store,
                "run-ports",
                "candidate_build",
                bindings,
                "build.environment_candidate",
                operation,
                compiler,
                {},
            )
    wrong_source = _envelope(store, "verifier_intent", graph_id="candidate")
    with pytest.raises(ValueError, match="graph_input_binding_duplicate"):
        graph._resolve_inputs(
            store,
            graph.node("candidate_build"),
            {"design": (design,), "build_plan": (wrong_source, wrong_source)},
        )
    with pytest.raises(ValueError, match="graph_edge_source_invalid"):
        graph._resolve_inputs(
            store,
            graph.node("candidate_build"),
            {"design": (design,), "build_plan": (wrong_source,)},
        )
    wrong_port = _envelope(store, "build_plan", graph_id="candidate", output_ports=("verifier",))
    with pytest.raises(ValueError, match="graph_envelope_output_ports_invalid"):
        graph._resolve_inputs(
            store,
            graph.node("candidate_build"),
            {"design": (design,), "build_plan": (wrong_port,)},
        )


def test_runner_accepts_sharded_refs_and_one_source_for_two_logical_ports(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    request = store.put_json("control.design_request", {"need_digest": _digest("1")})
    evidence = _envelope(store, "research_synthesis")
    architecture = graph.execute(
        store,
        "run-shards",
        "world_architecture",
        {"request": (request,), "evidence": (evidence,), "coverage": (evidence,)},
        "design.world_architecture",
        lambda _correction: {"closed": True},
        lambda value: value,
        {},
    )
    assert len(store.read_envelope(architecture.artifact)["dependencies"]) == 2

    architecture_ref = _envelope(store, "world_architecture")
    tools = (
        _envelope(store, "tool_semantics", shard_key="create"),
        _envelope(store, "tool_semantics", shard_key="close"),
    )
    rules: Any = graph.execute(
        store,
        "run-shards",
        "world_rules",
        {"architecture": (architecture_ref,), "tool_semantics": tools},
        "design.world_rules",
        lambda _correction: {"invariants": []},
        lambda value: value,
        {},
    )
    assert [item["digest"] for item in store.read_envelope(rules.artifact)["dependencies"]] == [
        architecture_ref.digest,
        *(tool.digest for tool in tools),
    ]


def test_runner_cold_reads_only_json_and_existing_package_bindings(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = candidate_graph()
    design = store.put_json("design.environment_design", {"closed": True})
    envelope_ports = {
        port: _envelope(store, node, graph_id="candidate")
        for port, node in {
            "package": "package",
            "candidate": "candidate_build",
            "integration": "integration",
            "judge": "judge",
            "verifier": "verifier_intent",
        }.items()
    }
    plain = {
        name: store.put_json(f"test.{name}", {"closed": True})
        for name in (
            "dossier",
            "telemetry",
            "semantic_lineage",
            "implementation_lineage",
            "design_work_records",
            "candidate_work_records",
        )
    }
    physical = store.put_bytes("registry.package", b"package", media_type="application/zip")
    bindings = {
        **{name: (ref,) for name, ref in envelope_ports.items()},
        "design": (design,),
        "physical_package": (physical,),
        **{name: (ref,) for name, ref in plain.items()},
    }
    assert graph._resolve_inputs(store, graph.node("registry"), bindings) == tuple(
        ref for port in graph.node("registry").input_ports for ref in bindings[port]
    )
    with pytest.raises(ArtifactIntegrityError, match="artifact_ref_invalid"):
        graph._resolve_inputs(
            store,
            graph.node("registry"),
            {**bindings, "physical_package": (replace(physical, media_type="application/json"),)},
        )
    with pytest.raises(ValueError, match="graph_input_media_type_invalid"):
        graph._resolve_inputs(
            store,
            graph.node("registry"),
            {
                **bindings,
                "physical_package": (replace(physical, media_type="application/octet-stream"),),
            },
        )


def _correction(code: str = "closed_output_invalid", path: str = "$.field") -> CorrectionPacket:
    return CorrectionPacket(code, path, "field must satisfy the closed contract", "string")


def _tool_semantics_inputs(store: ArtifactStore) -> dict[str, tuple[ArtifactRef, ...]]:
    return {
        "architecture": (_envelope(store, "world_architecture"),),
        "evidence": (_envelope(store, "research_synthesis"),),
    }


def _curriculum_inputs(store: ArtifactStore) -> dict[str, tuple[ArtifactRef, ...]]:
    return {
        "architecture": (_envelope(store, "world_architecture"),),
        "rules": (_envelope(store, "world_rules"),),
        "evidence": (_envelope(store, "research_synthesis"),),
    }


def test_two_correction_declarations_are_explicit_and_direct_only() -> None:
    graph = design_graph()
    assert {node.id for node in graph.nodes if node.local_corrections == 2} == {
        "tool_semantics",
        "curriculum_plan",
        "task_requirement",
    }
    assert {node.id: node.local_corrections for node in (*DESIGN_NODES, *CANDIDATE_NODES)} == {
        "research_plan": 1,
        "research_acquire": 0,
        "research_synthesis": 1,
        "world_architecture": 1,
        "shared_tool_semantics": 1,
        "tool_semantics": 2,
        "world_rules": 1,
        "curriculum_plan": 2,
        "task_requirement": 2,
        "modeling_gate": 0,
        "build_plan": 1,
        "verifier_intent": 1,
        "candidate_build": 1,
        "integration": 0,
        "judge": 0,
        "package": 0,
        "registry": 0,
    }
    assert (
        NodeSpec(
            "world_rules",
            "designer",
            "direct_llm",
            ("architecture", "tool_semantics"),
            ("rules",),
            "WorldRulesSourceDraft@1",
            "world-rules@1",
            route="direct",
            local_corrections=2,
        ).local_corrections
        == 2
    )
    with pytest.raises(ValueError, match="graph_correction_limit_invalid"):
        NodeSpec(
            "research_synthesis",
            "designer",
            "agent",
            ("request", "research_plan", "sources", "citations"),
            ("evidence", "coverage"),
            "ResearchSynthesisDraft@1",
            "research-synthesis@1",
            "research-synthesis",
            "agent",
            local_corrections=2,
        )


@pytest.mark.parametrize("node_id", ("tool_semantics", "curriculum_plan"))
def test_two_correction_direct_format_first_admits_final_semantic_correction(
    tmp_path, node_id: str
) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    inputs = (
        _tool_semantics_inputs(store) if node_id == "tool_semantics" else _curriculum_inputs(store)
    )
    format_packet = CorrectionPacket(
        "direct_response_not_json",
        "$",
        "response must be exactly one JSON object",
        "object",
    )
    semantic_packet = CorrectionPacket(
        f"{node_id}_invalid", "$.field", "field must satisfy the contract", "string"
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(value: dict[str, bool]) -> dict[str, bool]:
        if len(corrections) == 1:
            raise NodeExecutionError(format_packet.code, correction=format_packet)
        if len(corrections) == 2:
            raise NodeExecutionError(semantic_packet.code, correction=semantic_packet)
        return value

    result = graph.execute(
        store,
        f"run-{node_id}-format-semantic",
        node_id,
        inputs,
        f"design.{node_id}",
        operation,
        compiler,
        {"projection": "frozen"},
    )

    assert corrections == [None, format_packet, semantic_packet]
    work = store.read_json(result.work)
    attempts = [
        store.read_json(ArtifactRef(**item))
        for item in work["assurance_refs"]
        if item["kind"] == "control.attempt"
    ]
    assert [attempt["status"] for attempt in attempts] == [
        "correction_requested",
        "correction_requested",
        "passed",
    ]


@pytest.mark.parametrize("node_id", ("tool_semantics", "curriculum_plan"))
def test_two_correction_direct_semantic_then_format_is_terminal(tmp_path, node_id: str) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    inputs = (
        _tool_semantics_inputs(store) if node_id == "tool_semantics" else _curriculum_inputs(store)
    )
    semantic_packet = CorrectionPacket(
        f"{node_id}_invalid", "$.field", "field must satisfy the contract", "string"
    )
    format_packet = CorrectionPacket(
        "direct_response_not_json",
        "$",
        "response must be exactly one JSON object",
        "object",
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(_value: object) -> object:
        packet = semantic_packet if len(corrections) == 1 else format_packet
        raise NodeExecutionError(packet.code, correction=packet)

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            f"run-{node_id}-semantic-format",
            node_id,
            inputs,
            f"design.{node_id}",
            operation,
            compiler,
            {"projection": "frozen"},
        )

    assert raised.value.correction == format_packet
    assert corrections == [None, semantic_packet]


@pytest.mark.parametrize("node_id", ("tool_semantics", "curriculum_plan"))
@pytest.mark.parametrize("third_valid", (True, False))
def test_two_correction_direct_repeated_format_has_three_proposal_ceiling(
    tmp_path, node_id: str, third_valid: bool
) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    inputs = (
        _tool_semantics_inputs(store) if node_id == "tool_semantics" else _curriculum_inputs(store)
    )
    packet = CorrectionPacket(
        "direct_response_not_json",
        "$",
        "response must be exactly one JSON object",
        "object",
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(value: dict[str, bool]) -> dict[str, bool]:
        if len(corrections) < 3 or not third_valid:
            raise NodeExecutionError(packet.code, correction=packet)
        return value

    arguments = (
        store,
        f"run-{node_id}-repeated-format-{third_valid}",
        node_id,
        inputs,
        f"design.{node_id}",
        operation,
        compiler,
        {"projection": "frozen"},
    )
    if third_valid:
        graph.execute(*arguments)
    else:
        with pytest.raises(NodeExecutionError) as raised:
            graph.execute(*arguments)
        assert raised.value.correction == packet

    assert corrections == [None, packet, packet]


def test_tool_semantics_admits_one_distinct_second_semantic_correction(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    first = CorrectionPacket(
        "tool_semantics_invalid", "$.transitions", "first semantic issue", "array"
    )
    second = CorrectionPacket(
        "tool_semantics_invalid", "$.errors[0]", "second semantic issue", "object"
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> InvocationResult:
        corrections.append(correction)
        return InvocationResult({"closed": True}, "direct-test", None)

    def compiler(result: InvocationResult) -> dict[str, bool]:
        if len(corrections) == 1:
            raise NodeExecutionError(first.code, correction=first)
        if len(corrections) == 2:
            raise NodeExecutionError(second.code, correction=second)
        return result.value

    result = graph.execute(
        store,
        "run-tool-progress",
        "tool_semantics",
        _tool_semantics_inputs(store),
        "design.tool_semantics",
        operation,
        compiler,
        {"projection": "frozen"},
        operation_evidence=lambda response: (
            OperationEvidence("direct_llm", "tool_semantics", response.route_model, response.usage),
        ),
    )

    assert corrections == [None, first, second]
    work = store.read_json(result.work)
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    attempts = [store.read_json(ref) for ref in assurance if ref.kind == "control.attempt"]
    operations = [store.read_json(ref) for ref in assurance if ref.kind == "assurance.operation"]
    assert [attempt["status"] for attempt in attempts] == [
        "correction_requested",
        "correction_requested",
        "passed",
    ]
    assert len(operations) == len(attempts) == 3


def test_tool_semantics_same_issue_stops_after_two_proposals(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    packet = CorrectionPacket(
        "tool_semantics_invalid", "$.transitions", "unchanged semantic issue", "array"
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-tool-same-issue",
            "tool_semantics",
            _tool_semantics_inputs(store),
            "design.tool_semantics",
            operation,
            lambda _value: (_ for _ in ()).throw(
                NodeExecutionError(packet.code, correction=packet)
            ),
            {"projection": "frozen"},
        )

    assert raised.value.code == packet.code
    assert corrections == [None, packet]


def test_tool_semantics_third_invalid_proposal_stops_without_a_fourth_call(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    packets = (
        CorrectionPacket("tool_semantics_invalid", "$.preconditions", "issue A", "array"),
        CorrectionPacket("tool_semantics_invalid", "$.transitions", "issue B", "array"),
        CorrectionPacket("tool_semantics_invalid", "$.errors", "issue C", "array"),
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(_value: object) -> object:
        packet = packets[len(corrections) - 1]
        raise NodeExecutionError(packet.code, correction=packet)

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-tool-third-invalid",
            "tool_semantics",
            _tool_semantics_inputs(store),
            "design.tool_semantics",
            operation,
            compiler,
            {"projection": "frozen"},
        )

    assert raised.value.correction == packets[2]
    assert corrections == [None, packets[0], packets[1]]


def test_curriculum_admits_one_distinct_second_semantic_correction(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    first = CorrectionPacket(
        "curriculum_plan_invalid", "$.families[0].dimensions", "first semantic issue", "array"
    )
    second = CorrectionPacket(
        "curriculum_plan_invalid", "$.families[1].actor_index", "second semantic issue", "integer"
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(value: dict[str, bool]) -> dict[str, bool]:
        if len(corrections) == 1:
            raise NodeExecutionError(first.code, correction=first)
        if len(corrections) == 2:
            raise NodeExecutionError(second.code, correction=second)
        return value

    result = graph.execute(
        store,
        "run-curriculum-progress",
        "curriculum_plan",
        _curriculum_inputs(store),
        "design.curriculum_plan",
        operation,
        compiler,
        {"projection": "frozen"},
    )

    assert corrections == [None, first, second]
    work = store.read_json(result.work)
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    attempts = [store.read_json(ref) for ref in assurance if ref.kind == "control.attempt"]
    assert [attempt["status"] for attempt in attempts] == [
        "correction_requested",
        "correction_requested",
        "passed",
    ]


def test_curriculum_same_issue_stops_after_two_proposals(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    packet = CorrectionPacket(
        "curriculum_plan_invalid", "$.families[0].dimensions", "unchanged semantic issue", "array"
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-curriculum-same-issue",
            "curriculum_plan",
            _curriculum_inputs(store),
            "design.curriculum_plan",
            operation,
            lambda _value: (_ for _ in ()).throw(
                NodeExecutionError(packet.code, correction=packet)
            ),
            {"projection": "frozen"},
        )

    assert raised.value.code == packet.code
    assert corrections == [None, packet]


def test_curriculum_third_invalid_proposal_stops_without_a_fourth_call(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    packets = (
        CorrectionPacket("curriculum_plan_invalid", "$.families[0].dimensions", "issue A", "array"),
        CorrectionPacket(
            "curriculum_plan_invalid", "$.families[0].actor_index", "issue B", "integer"
        ),
        CorrectionPacket("curriculum_plan_invalid", "$.families[1].dimensions", "issue C", "array"),
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(_value: object) -> object:
        packet = packets[len(corrections) - 1]
        raise NodeExecutionError(packet.code, correction=packet)

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-curriculum-third-invalid",
            "curriculum_plan",
            _curriculum_inputs(store),
            "design.curriculum_plan",
            operation,
            compiler,
            {"projection": "frozen"},
        )

    assert raised.value.correction == packets[2]
    assert corrections == [None, packets[0], packets[1]]


@pytest.mark.parametrize("failure_stage", ("provider", "postcompile"))
def test_curriculum_provider_or_postcompile_failure_never_admits_a_third_proposal(
    tmp_path, failure_stage: str
) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    packet = CorrectionPacket(
        "curriculum_plan_invalid", "$.families[0].dimensions", "terminal issue", "array"
    )
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        if failure_stage == "provider":
            raise NodeExecutionError("provider", "error", True, correction=packet)
        return {"closed": True}

    def validator(_value: dict[str, bool]) -> None:
        if failure_stage == "postcompile":
            raise NodeExecutionError(packet.code, correction=packet)

    with pytest.raises(NodeExecutionError):
        graph.execute(
            store,
            f"run-curriculum-{failure_stage}-terminal",
            "curriculum_plan",
            _curriculum_inputs(store),
            "design.curriculum_plan",
            operation,
            lambda value: value,
            {"projection": "frozen"},
            validator=validator,
        )

    assert corrections == [None]


def test_non_tool_semantics_node_never_admits_a_second_correction(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    first = CorrectionPacket("world_rules_invalid", "$.initial_rules", "issue A", "array")
    second = CorrectionPacket("world_rules_invalid", "$.invariants", "issue B", "array")
    architecture = _envelope(store, "world_architecture")
    tools = _envelope(store, "tool_semantics", shard_key="tool_1")
    corrections: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        corrections.append(correction)
        return {"closed": True}

    def compiler(_value: object) -> object:
        packet = first if len(corrections) == 1 else second
        raise NodeExecutionError(packet.code, correction=packet)

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-non-tool-second-correction",
            "world_rules",
            {"architecture": (architecture,), "tool_semantics": (tools,)},
            "design.world_rules",
            operation,
            compiler,
            {"projection": "frozen"},
        )

    assert raised.value.correction == second
    assert corrections == [None, first]


def test_runner_permits_one_safe_model_correction_and_persists_both_attempts(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    request = store.put_json("control.design_request", {"need_digest": _digest("1")})
    packet = _correction("research_plan_invalid", "$.queries")
    corrections: list[CorrectionPacket | None] = []
    semantic_material = {"projection": "frozen"}
    assert graph.semantic_revision(
        graph.node("research_plan"), semantic_material
    ) == graph.semantic_revision(
        replace(graph.node("research_plan"), local_corrections=0), semantic_material
    )

    def operation(correction: CorrectionPacket | None) -> InvocationResult:
        corrections.append(correction)
        return InvocationResult({"queries": ["safe"]}, "model-test", None, _digest("b"))

    def compiler(result: InvocationResult) -> tuple[str, ...]:
        if len(corrections) == 1:
            raise NodeExecutionError("research_plan_invalid", correction=packet)
        return tuple(result.value["queries"])

    result = graph.execute(
        store,
        "run-correction",
        "research_plan",
        {"request": (request,)},
        "design.research_plan",
        operation,
        compiler,
        semantic_material,
        operation_evidence=lambda response: (
            OperationEvidence(
                "agent",
                "research_plan",
                response.route_model,
                response.usage,
                response.skill_digest,
            ),
        ),
    )
    assert corrections == [None, packet]
    work = store.read_json(result.work)
    assurance = tuple(ArtifactRef(**item) for item in work["assurance_refs"])
    attempts = [store.read_json(ref) for ref in assurance if ref.kind == "control.attempt"]
    assert [attempt["status"] for attempt in attempts] == ["correction_requested", "passed"]
    assert attempts[0]["correction"] == json_value(packet)


def test_runner_never_corrects_provider_framework_or_candidate_terminals(tmp_path) -> None:
    packet = _correction()
    cases: list[tuple[object, str, dict[str, tuple[ArtifactRef, ...]], NodeExecutionError]] = []
    store = ArtifactStore(tmp_path)
    design = design_graph()
    candidate = candidate_graph()
    request = store.put_json("control.design_request", {"need_digest": _digest("1")})
    research_plan = _envelope(store, "research_plan")
    architecture = _envelope(store, "world_architecture")
    evidence = _envelope(store, "research_synthesis")
    candidate_ref = _envelope(store, "candidate_build", graph_id="candidate")
    design_ref = store.put_json("design.environment_design", {"closed": True})
    cases.extend(
        (
            (
                design,
                "research_plan",
                {"request": (request,)},
                NodeExecutionError("provider", "error", True, correction=packet),
            ),
            (
                design,
                "research_acquire",
                {"research_plan": (research_plan,)},
                NodeExecutionError("framework", correction=packet),
            ),
            (
                design,
                "tool_semantics",
                {"architecture": (architecture,), "evidence": (evidence,)},
                NodeExecutionError("framework", correction=packet),
            ),
            (
                candidate,
                "integration",
                {"design": (design_ref,), "candidate": (candidate_ref,)},
                NodeExecutionError("candidate", correction=packet),
            ),
        )
    )
    for graph, node_id, inputs, terminal in cases:
        calls = 0

        def operation(
            _correction: CorrectionPacket | None, failure: NodeExecutionError = terminal
        ) -> object:
            nonlocal calls
            calls += 1
            raise failure

        with pytest.raises(NodeExecutionError):
            cast(GraphRunner, graph).execute(
                store,
                f"run-no-correction-{node_id}",
                node_id,
                inputs,
                f"test.{node_id}",
                operation,
                lambda value: value,
                {},
            )
        assert calls == 1


@pytest.mark.parametrize(
    ("explicit_evidence", "expected_evidence"),
    [
        (None, "terminal_packet"),
        ({}, {}),
        ({"safe": "explicit terminal evidence"}, {"safe": "explicit terminal evidence"}),
    ],
)
def test_runner_persists_terminal_safe_feedback_without_a_third_call(
    tmp_path, explicit_evidence, expected_evidence
) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    request = store.put_json("control.design_request", {"need_digest": _digest("1")})
    first = _correction("initial_invalid", "$.field")
    terminal = _correction("terminal_invalid", "$.field")
    calls: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> dict[str, bool]:
        calls.append(correction)
        return {"closed": True}

    def compiler(_value: object) -> object:
        packet = first if len(calls) == 1 else terminal
        raise NodeExecutionError(
            packet.code,
            correction=packet,
            evidence=explicit_evidence if len(calls) == 2 else None,
        )

    with pytest.raises(NodeExecutionError) as raised:
        graph.execute(
            store,
            "run-terminal-feedback",
            "research_plan",
            {"request": (request,)},
            "design.research_plan",
            operation,
            compiler,
            {"projection": "frozen"},
        )
    assert calls == [None, first]
    failure_ref = next(ref for ref in raised.value.artifact_refs if ref.kind.endswith(".failure"))
    persisted = store.read_json(failure_ref)["evidence"]
    assert persisted == (
        json_value(terminal) if expected_evidence == "terminal_packet" else expected_evidence
    )


def test_runner_persists_canonical_direct_usage_in_work_assurance_closure(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    request = store.put_json("control.design_request", {"need_digest": _digest("1")})
    usage = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    result = graph.execute(
        store,
        "run-usage",
        "research_plan",
        {"request": (request,)},
        "design.research_plan",
        lambda _correction: InvocationResult({"closed": True}, "direct-test", usage),
        lambda response: response.value,
        {},
        operation_evidence=lambda response: (
            OperationEvidence("direct_llm", "research_plan", response.route_model, response.usage),
        ),
    )
    work = store.read_json(result.work)
    evidence_refs = [
        ArtifactRef(**item)
        for item in work["assurance_refs"]
        if item["kind"] == "assurance.operation"
    ]
    assert len(evidence_refs) == 1
    assert store.read_json(evidence_refs[0])["usage"] == usage


@pytest.mark.parametrize("alias", ["prompt_tokens", "completion_tokens"])
def test_operation_evidence_rejects_direct_provider_usage_aliases(alias: str) -> None:
    with pytest.raises(ValueError, match="operation_evidence_usage_invalid"):
        OperationEvidence("direct_llm", "world_architecture", "model-test", {alias: 1})


@pytest.mark.parametrize(
    ("graph_name", "node_id", "expected_path", "compiler_name"),
    [
        ("candidate", "build_plan", "$.steps", "build_plan"),
        ("candidate", "candidate_build", "$", "candidate_completion"),
        ("design", "research_plan", "$.name", "design"),
        ("candidate", "verifier_intent", "$.checks[0].family", "verifier_intent"),
    ],
)
def test_model_compiler_corrections_are_causal_and_keep_projection_frozen(
    tmp_path, graph_name: str, node_id: str, expected_path: str, compiler_name: str
) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph() if graph_name == "design" else candidate_graph()
    external_design = store.put_json("design.environment_design", {"closed": True})
    if node_id == "research_plan":
        inputs = {"request": (store.put_json("control.request", {"closed": True}),)}
    elif node_id == "candidate_build":
        inputs = {
            "design": (external_design,),
            "build_plan": (_envelope(store, "build_plan", graph_id="candidate"),),
        }
    else:
        inputs = {"design": (external_design,)}
    proposals: tuple[object, object] = {
        "build_plan": (
            {"steps": [], "risks": []},
            {
                "steps": [
                    {
                        "goal": "implement runtime",
                        "suggested_paths": ["runtime.py"],
                        "contract_sections": ["runtime"],
                        "self_check": "run protocol check",
                    }
                ],
                "risks": [],
            },
        ),
        "candidate_completion": (
            {},
            {"summary": "implemented", "self_checks": [], "known_limits": []},
        ),
        "design": ({}, {"name": "closed"}),
        "verifier_intent": ({}, {"checks": []}),
    }[compiler_name]
    seen: list[CorrectionPacket | None] = []

    def operation(correction: CorrectionPacket | None) -> object:
        seen.append(correction)
        return proposals[len(seen) - 1]

    def compile_value(value: object) -> object:
        if compiler_name == "build_plan":
            return candidate_module.validate_build_plan(value, {"sections": ["runtime"]})
        if compiler_name == "candidate_completion":
            return candidate_module.validate_candidate_completion(value)
        if len(seen) == 1:
            raise NodeExecutionError(
                f"{compiler_name}_invalid",
                correction=_correction(f"{compiler_name}_invalid", expected_path),
            )
        return value

    semantic_material = {"effective_projection": {"frozen": [1, 2, 3]}}
    expected_semantic = graph.semantic_revision(graph.node(node_id), semantic_material)
    result = graph.execute(
        store,
        f"run-frozen-{node_id}",
        node_id,
        inputs,
        f"test.{node_id}",
        operation,
        compile_value,
        semantic_material,
    )
    assert len(seen) == 2 and seen[0] is None
    assert seen[1] is not None and seen[1].path == expected_path
    assert result.semantic_revision_digest == expected_semantic
    assert semantic_material == {"effective_projection": {"frozen": [1, 2, 3]}}


def test_direct_compiler_framework_defect_is_terminal_without_a_second_call(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    graph = design_graph()
    request = store.put_json("control.request", {"closed": True})
    calls = 0

    def operation(_correction: CorrectionPacket | None) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"closed": True}

    with pytest.raises(NodeExecutionError):
        graph.execute(
            store,
            "run-framework-defect",
            "research_plan",
            {"request": (request,)},
            "design.research_plan",
            operation,
            lambda _value: (_ for _ in ()).throw(NodeExecutionError("compiler_defect")),
            {},
        )
    assert calls == 1


def test_design_model_helpers_attach_only_the_safe_correction_packet() -> None:
    executor = object.__new__(design_module.DesignExecutor)
    captured_agent: list[dict[str, object]] = []
    captured_direct: list[dict[str, str]] = []
    packet = _correction()

    class Agent:
        def invoke_json(self, **kwargs: object) -> InvocationResult:
            captured_agent.append(dict(kwargs))
            return InvocationResult({}, "agent-test", None, _digest("d"))

    class Direct:
        def invoke_json(self, **kwargs: str) -> InvocationResult:
            captured_direct.append(dict(kwargs))
            return InvocationResult({}, "direct-test", None)

    executor.agent = cast(Any, Agent())
    executor.direct = cast(Any, Direct())
    executor._agent_json("research_plan", "research-world-evidence", Path("."), "frozen", packet)
    prior = design_module._canonical({"previous": "proposal"}).decode()
    executor._direct_json(
        "world_architecture",
        {"closed": True},
        "Closed@1",
        packet,
        previous_output=prior,
    )

    agent_instruction = str(captured_agent[0]["instruction"])
    assert agent_instruction.startswith("frozen\nAuthorized correction packet: ")
    assert json.loads(agent_instruction.partition(": ")[2]) == json_value(packet)
    direct_user = json.loads(captured_direct[0]["user"])
    assert direct_user == {
        "node": "world_architecture",
        "input": {"closed": True},
        "output_shape": "Closed@1",
        "correction": None,
    }
    assert captured_direct[0]["previous_assistant"] == prior
    feedback = captured_direct[0]["feedback"]
    assert "code closed_output_invalid" in feedback
    assert "path $.field" in feedback
    assert "condition field must satisfy the closed contract" in feedback
    assert "expected category string" in feedback
    assert "correct the response at the flagged path" in feedback
    assert "one complete replacement as exactly one JSON object" in feedback
    assert "self-check the whole replacement object" in feedback
    assert "release authority" in captured_direct[0]["system"]


@pytest.mark.parametrize(
    ("work", "skill", "writable"),
    [
        ("build_plan", "engineer-build-planning", False),
        ("verifier_intent", "challenge-agent-world", False),
        ("candidate_build", "engineer-environment-codegen", True),
    ],
)
def test_candidate_agent_helper_delivers_the_same_safe_correction_to_each_agent_work(
    work: str, skill: str, writable: bool
) -> None:
    executor = object.__new__(candidate_module.CandidateExecutor)
    captured: list[dict[str, object]] = []
    packet = _correction()

    class Agent:
        def invoke_json(self, **kwargs: object) -> InvocationResult:
            captured.append(dict(kwargs))
            return InvocationResult({}, "agent-test", None, _digest("d"))

    executor.agent = cast(Any, Agent())
    executor._agent_json(
        work,
        skill,
        Path("."),
        "frozen",
        correction=packet,
        writable=writable,
    )
    assert captured[0]["workspace"] == Path(".")
    assert captured[0]["writable"] is writable
    instruction = str(captured[0]["instruction"])
    assert instruction.startswith("frozen\nAuthorized correction packet: ")
    assert json.loads(instruction.partition(": ")[2]) == json_value(packet)


def test_direct_architecture_discloses_the_complete_compiler_contract_and_commits() -> None:
    architecture = _design().architecture
    payload = json_value(architecture)
    assert set(payload) == {
        "boundary",
        "entities",
        "tools",
        "known_divergences",
        "catalog",
        "coupling_plan",
        "artifact",
    }
    assert [tool["tool_index"] for tool in payload["tools"]] == [1, 2]
    assert payload["coupling_plan"] == {"groups": [[1, 2]]}
    assert payload["catalog"]["bindings"][0]["name"] == "request_id"
    with pytest.raises(TypeError):
        WorldArchitecture(**{**payload, "framework_gate": "forbidden"})


def test_tool_semantics_replaces_the_echo_contract_with_closed_local_rules() -> None:
    tool = _design().tools[0]
    payload = json_value(tool)
    assert set(payload) == {
        "tool_index",
        "surface",
        "bindings",
        "preconditions",
        "transitions",
        "postconditions",
        "errors",
        "shared_contract_digest",
        "local_rules_digest",
    }
    assert all(isinstance(rule, RuleDraft) for rule in (*tool.preconditions, *tool.transitions))
    assert "success_result" not in payload and "description" not in payload
    with pytest.raises(ValueError, match="tool_draft_digest_invalid"):
        replace(tool, local_rules_digest="invalid")
