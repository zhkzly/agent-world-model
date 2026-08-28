from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import agent_env_foundry.semantic_qualification as semantic_qualification_module
from agent_env_foundry.environment import ToolObservation, ToolSpec
from agent_env_foundry.native_oracle import NativeAtomEvidence
from agent_env_foundry.qualification import QualificationConfig, QualificationResult
from agent_env_foundry.semantic_qualification import (
    ConcreteCapabilityScenario,
    PublicCapabilityEpisode,
    SemanticQualificationFailure,
    _qualify_capability,
    qualify_semantic_capabilities,
    run_public_capability_episode,
)
from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    BindingCandidate,
    CapabilitySpec,
    RenderingSpec,
    StartCase,
    TraceEvent,
)
from agent_env_foundry.semantics_author import SemanticsBuild


class _FunctionCall:
    type = "function_call"

    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _FakeResponse:
    def __init__(self, output: list[Any], output_text: str = "") -> None:
        self.output = output
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, responses: list[_FakeResponse | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse | Exception]) -> None:
        self.responses = _FakeResponses(responses)


class _TransientProviderError(RuntimeError):
    status_code = 500


class _EpisodeActor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def reset(self, start: dict[str, Any] | None = None) -> Any:
        del start
        return {"items": [{"name": "alpha", "status": "open"}]}

    def tools(self) -> tuple[ToolSpec, ...]:
        output = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["status", "name"],
            "additionalProperties": False,
        }
        return cast(
            tuple[ToolSpec, ...],
            (
                {
                    "name": "lookup",
                    "description": "Read one public item.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                    "output_schema": output,
                },
                {
                    "name": "finish",
                    "description": "Finish one public item.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                    "output_schema": output,
                },
            ),
        )

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
        self.calls.append((tool_name, arguments))
        status = "done" if tool_name == "finish" else "open"
        return {
            "ok": True,
            "data": {"name": arguments["name"], "status": status},
            "error": None,
        }

    def close(self) -> None:
        return None


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="finish-item",
        requirement_ids=("REQ-1",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="finish the selected item",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={"type": "object", "additionalProperties": True},
        facets=(),
        conditions=(),
        answer_fields=(
            AnswerFieldSpec(
                "status",
                {"type": "string", "enum": ["done", "wrong"]},
                "final status",
            ),
        ),
        read_scopes=("items",),
        write_scopes=("items",),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("finish", "item", "report the final status"),
    )


def _binding(key: str = "alpha") -> BindingCandidate:
    return BindingCandidate(
        key,
        True,
        (),
        {"private_id": f"secret-{key}"},
        {"name": key},
        {},
    )


def _query_capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="inspect-item",
        requirement_ids=("REQ-QUERY",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="operator",
        task_kind="query",
        intent_label="inspect the selected item",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={"type": "object", "additionalProperties": True},
        facets=(),
        conditions=(),
        answer_fields=(AnswerFieldSpec("status", {"type": "string"}, "observed status"),),
        read_scopes=("items",),
        write_scopes=(),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("inspect", "item", "report the observed status"),
    )


def _process_capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="finish-process",
        requirement_ids=("REQ-PROCESS",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="operator",
        task_kind="process",
        intent_label="finish the selected item through the required public process",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={"type": "object", "additionalProperties": True},
        facets=(),
        conditions=(),
        answer_fields=(),
        read_scopes=("items",),
        write_scopes=("items",),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("finish", "item", None),
    )


def _state_capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="set-item-state",
        requirement_ids=("REQ-STATE",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="set the selected item state",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={"type": "object", "additionalProperties": True},
        facets=(),
        conditions=(),
        answer_fields=(),
        read_scopes=("items",),
        write_scopes=("items",),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("set", "item", None),
    )


def _atom_result(*, satisfied: bool, answer_ok: bool | None = None) -> dict[str, Any]:
    return {
        "initially_satisfied": False,
        "satisfied": satisfied,
        "required_effects_ok": satisfied,
        "collateral_ok": satisfied,
        "answer_ok": answer_ok,
        "process_ok": None,
        "report_values": {"status": "done"} if satisfied else {},
        "failure_codes": [] if satisfied else ["not_satisfied"],
    }


def _scenario_directories(tmp_path: Path) -> Path:
    root = tmp_path / "scenario"
    for name, document in (
        ("before", {"done": False}),
        ("after", {"done": True}),
    ):
        directory = root / name
        directory.mkdir(parents=True)
        directory.joinpath("state.json").write_text(json.dumps(document))
    return root


def _scenario(
    capability_id: str,
    *,
    action_instance_unchanged: bool = True,
) -> ConcreteCapabilityScenario:
    return ConcreteCapabilityScenario(
        capability_id,
        "alpha",
        "primary",
        "before",
        "after",
        StartCase("base", None, ("base",)),
        (),
        (
            TraceEvent(
                1,
                "lookup",
                {"name": "alpha"},
                {"ok": True, "data": {"name": "alpha", "status": "done"}, "error": None},
            ),
        ),
        {"status": "done"},
        "same" if action_instance_unchanged else "before",
        "same" if action_instance_unchanged else "after",
    )


def _scripted_oracle(result_factory: Any) -> Any:
    class Oracle:
        def check_atom(self, **kwargs: Any) -> NativeAtomEvidence:
            document = result_factory(kwargs)
            return NativeAtomEvidence(
                "native-scripted",
                "a" * 64,
                "b" * 64,
                kwargs["public_binding"],
                semantic_qualification_module.atom_result_from_document(document),
                ({"native": "fact"},),
                {"reader": "independent"},
            )

    return Oracle()


def test_public_capability_episode_uses_only_actor_tools_and_records_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "episode-secret")
    client = _FakeClient(
        [
            _TransientProviderError("temporary upstream TLS failure"),
            _FakeResponse([_FunctionCall("lookup", json.dumps({"name": "alpha"}), "lookup-call")]),
            _FakeResponse([_FunctionCall("finish", json.dumps({"name": "alpha"}), "finish-call")]),
            _FakeResponse([], json.dumps({"answer": {"status": "done"}})),
        ]
    )

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        assert (api_key, base_url, max_retries) == (
            "episode-secret",
            "http://127.0.0.1:8317/v1",
            0,
        )
        return client

    actor = _EpisodeActor()
    episode = run_public_capability_episode(
        actor=actor,
        capability=_capability(),
        binding=_binding(),
        reset_observation={"items": [{"name": "alpha", "status": "open"}]},
        public_documents={"README.md": "Use lookup before changing an item."},
        client_factory=factory,
        max_provider_turns=4,
    )

    assert actor.calls == [
        ("lookup", {"name": "alpha"}),
        ("finish", {"name": "alpha"}),
    ]
    assert [item.tool_name for item in episode.trace] == ["lookup", "finish"]
    assert episode.final_answer == {"status": "done"}
    request = client.responses.calls[0]
    assert {tool["name"] for tool in request["tools"]} == {"lookup", "finish"}
    assert all(tool["strict"] is False for tool in request["tools"])
    rendered = repr(request["input"])
    assert "alpha" in rendered
    assert "Use lookup before changing an item." in rendered
    assert "secret-alpha" not in rendered
    assert "protected_binding" not in rendered
    assert request["text"]["format"]["strict"] is False
    assert client.responses.calls[0] == client.responses.calls[1]


def test_framework_rejects_answer_ignoring_query_evaluator(tmp_path: Path) -> None:
    capability = _query_capability()
    root = _scenario_directories(tmp_path)

    class AnswerIgnoringTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding().to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                satisfied = bool(request["trace_projection"])
                return _atom_result(satisfied=satisfied, answer_ok=satisfied)
            raise AssertionError(operation)

    with pytest.raises(
        SemanticQualificationFailure,
        match="schema-valid wrong answer",
    ) as captured:
        _qualify_capability(
            cast(Any, AnswerIgnoringTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id),
            root,
            oracle=_scripted_oracle(
                lambda kwargs: _atom_result(
                    satisfied=bool(kwargs["trace"]),
                    answer_ok=bool(kwargs["trace"]),
                )
            ),
        )

    assert captured.value.code == "semantic_wrong_answer_accepted"


def test_framework_rejects_query_episode_that_mutates_native_state(tmp_path: Path) -> None:
    capability = _query_capability()
    root = _scenario_directories(tmp_path)

    class QueryTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding().to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                satisfied = bool(request["trace_projection"])
                return _atom_result(satisfied=satisfied, answer_ok=satisfied)
            raise AssertionError(operation)

    with pytest.raises(
        SemanticQualificationFailure,
        match="query episode mutated",
    ) as captured:
        _qualify_capability(
            cast(Any, QueryTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id, action_instance_unchanged=False),
            root,
            oracle=_scripted_oracle(lambda _kwargs: _atom_result(satisfied=False)),
        )

    assert captured.value.code == "semantic_query_mutated_state"


def test_framework_evaluates_the_exact_publicly_prompted_binding(tmp_path: Path) -> None:
    capability = _capability()
    root = _scenario_directories(tmp_path)

    class BindingSubstitutionTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding("alpha").to_document(), _binding("beta").to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                is_beta = request["protected_binding"] == {"private_id": "secret-beta"}
                satisfied = bool(request["trace_projection"] and is_beta)
                return _atom_result(satisfied=satisfied, answer_ok=satisfied)
            raise AssertionError(operation)

    with pytest.raises(
        SemanticQualificationFailure,
        match="publicly prompted binding",
    ) as captured:
        _qualify_capability(
            cast(Any, BindingSubstitutionTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id),
            root,
            oracle=_scripted_oracle(lambda _kwargs: _atom_result(satisfied=False, answer_ok=False)),
        )

    assert captured.value.code == "semantic_prompted_binding_rejected"


def test_framework_rejects_process_evaluator_that_ignores_public_trace(
    tmp_path: Path,
) -> None:
    capability = _process_capability()
    root = _scenario_directories(tmp_path)

    class TraceIgnoringTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding().to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                satisfied = bool(request["after_facts"]["done"])
                result = _atom_result(satisfied=satisfied)
                result["process_ok"] = satisfied
                return result
            raise AssertionError(operation)

    with pytest.raises(
        SemanticQualificationFailure,
        match="same terminal state without the public process",
    ) as captured:
        _qualify_capability(
            cast(Any, TraceIgnoringTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id),
            root,
            oracle=_scripted_oracle(
                lambda kwargs: {
                    **_atom_result(
                        satisfied=json.loads(
                            Path(kwargs["after_instance"]).joinpath("state.json").read_text()
                        )["done"]
                    ),
                    "process_ok": json.loads(
                        Path(kwargs["after_instance"]).joinpath("state.json").read_text()
                    )["done"],
                }
            ),
        )

    assert captured.value.code == "semantic_process_violation_accepted"


def test_framework_rejects_evaluator_that_accepts_noop(tmp_path: Path) -> None:
    capability = _state_capability()
    root = _scenario_directories(tmp_path)

    class NoopAcceptingTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding().to_document()]
            if operation == "evaluate_atom":
                return _atom_result(satisfied=True)
            raise AssertionError(operation)

    with pytest.raises(SemanticQualificationFailure, match="accepts a no-op") as captured:
        _qualify_capability(
            cast(Any, NoopAcceptingTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id),
            root,
            oracle=_scripted_oracle(lambda _kwargs: _atom_result(satisfied=True)),
        )

    assert captured.value.code == "semantic_noop_accepted"


def test_framework_rejects_ambiguous_public_binding_documents(tmp_path: Path) -> None:
    capability = _capability()
    root = _scenario_directories(tmp_path)
    alpha = _binding("alpha")
    beta = BindingCandidate(
        "beta",
        True,
        (),
        {"private_id": "secret-beta"},
        alpha.public_descriptor,
        alpha.facets,
    )

    class AmbiguousBindingTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [alpha.to_document(), beta.to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                is_alpha = request["protected_binding"] == {"private_id": "secret-alpha"}
                answer_ok = request["final_answer"] == {"status": "done"}
                satisfied = bool(request["trace_projection"] and is_alpha and answer_ok)
                return _atom_result(satisfied=satisfied, answer_ok=answer_ok)
            raise AssertionError(operation)

    with pytest.raises(
        SemanticQualificationFailure,
        match="same public binding document",
    ) as captured:
        _qualify_capability(
            cast(Any, AmbiguousBindingTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id),
            root,
            oracle=_scripted_oracle(lambda _kwargs: _atom_result(satisfied=False)),
        )

    assert captured.value.code == "semantic_public_binding_ambiguous"


def test_public_surface_rejects_observed_leaves_hidden_by_broad_schemas() -> None:
    public = {
        "reset_observation_schema": {
            "type": "object",
            "properties": {"clock": {"type": "object"}},
            "required": ["clock"],
            "additionalProperties": False,
        },
        "tool_specs": [
            {
                "name": "snapshot",
                "description": "Read the world.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                "output_schema": {"type": "object"},
            }
        ],
        "public_probe_facts": [
            {
                "operation": "reset",
                "arguments": {"start": None},
                "result": {"clock": {"now": "2025-01-01T00:00:00Z"}},
            },
            {
                "operation": "invoke",
                "arguments": {"tool_name": "snapshot", "arguments": {}},
                "result": {
                    "ok": True,
                    "data": {"clock": {"now": "2025-01-01T00:00:00Z"}},
                    "error": None,
                },
            },
        ],
    }

    with pytest.raises(
        SemanticQualificationFailure,
        match="explicitly describe every observed public leaf",
    ) as captured:
        semantic_qualification_module._validate_public_surface_schema_evidence(public)

    assert captured.value.code == "semantic_public_schema_incomplete"


def test_framework_rejects_task_semantics_native_oracle_disagreement(tmp_path: Path) -> None:
    capability = _query_capability()
    root = _scenario_directories(tmp_path)

    class SemanticTransport:
        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding().to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                satisfied = bool(request["trace_projection"])
                return _atom_result(satisfied=satisfied, answer_ok=satisfied)
            raise AssertionError(operation)

    class DisagreeingOracle:
        def check_atom(self, **_kwargs: Any) -> NativeAtomEvidence:
            native = semantic_qualification_module.atom_result_from_document(
                _atom_result(satisfied=False, answer_ok=False)
            )
            return NativeAtomEvidence(
                "native-001",
                "a" * 64,
                "b" * 64,
                _binding().public_document(),
                native,
                ({"native": "fact"},),
                {"reader": "independent"},
            )

    with pytest.raises(
        SemanticQualificationFailure,
        match="independent native oracle",
    ) as captured:
        _qualify_capability(
            cast(Any, SemanticTransport()),
            {capability.capability_id: capability},
            _scenario(capability.capability_id),
            root,
            oracle=cast(Any, DisagreeingOracle()),
        )

    assert captured.value.code == "semantic_native_disagreement"


def test_framework_rejects_public_binding_values_absent_from_public_evidence() -> None:
    capability = _capability()
    binding = BindingCandidate(
        "hidden",
        True,
        (),
        {"private_id": "secret-hidden"},
        {"name": "hidden-native-only"},
        {},
    )
    public = {"public_probe_facts": []}

    with pytest.raises(
        SemanticQualificationFailure,
        match="publicly discoverable",
    ) as captured:
        semantic_qualification_module._validate_public_binding_visibility(
            capability,
            binding,
            {"items": [{"name": "visible"}]},
            public,
        )

    assert captured.value.code == "semantic_public_binding_hidden"


def test_fresh_replay_requires_same_referent_and_before_facts() -> None:
    with pytest.raises(SemanticQualificationFailure) as key_failure:
        semantic_qualification_module._require_fresh_replay(
            "capability",
            "selected-a",
            "selected-b",
            "facts-a",
            "facts-a",
        )
    assert key_failure.value.code == "semantic_fresh_replay_mismatch"

    with pytest.raises(SemanticQualificationFailure) as facts_failure:
        semantic_qualification_module._require_fresh_replay(
            "capability",
            "selected-a",
            "selected-a",
            "facts-a",
            "facts-b",
        )
    assert facts_failure.value.code == "semantic_fresh_replay_facts_mismatch"


def test_framework_materializes_before_after_episode_before_semantic_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "qualification/semantics-author"
    source_root.mkdir(parents=True)
    public = {
        "candidate_digest": "a" * 64,
        "actor_factory": "generated_actor.release:make_environment",
        "start_schema": {"type": "object", "additionalProperties": True},
        "reset_observation_schema": {
            "type": "object",
            "properties": {
                "selected": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "available": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["selected", "available"],
            "additionalProperties": False,
        },
        "tool_specs": list(_EpisodeActor().tools()),
        "public_documents": [],
        "public_probe_facts": [
            {
                "operation": "reset",
                "arguments": {"start": {"seed": 7}},
                "result": {"selected": {"name": "alpha"}, "available": ["alpha", "beta"]},
            }
        ],
    }
    (source_root / "PUBLIC_SURFACE.json").write_text(json.dumps(public))
    source = SimpleNamespace(root=source_root, verify_inputs=lambda: None)
    qualification = QualificationResult(
        status="passed",
        candidate_digest="a" * 64,
        expected_relations_digest="c" * 64,
        evidence_digest="d" * 64,
        probe_bundle_digest="f" * 64,
        workspace_root=source_root.parent,
        semantics_author_inputs=source,  # type: ignore[arg-type]
        expected_task_semantics_digest="g" * 64,
    )
    instances_seen: list[Path] = []

    class Actor(_EpisodeActor):
        def __init__(self, instance: Path) -> None:
            super().__init__()
            self.instance = instance

        def reset(self, start: dict[str, Any] | None = None) -> Any:
            self.instance.mkdir(parents=True, exist_ok=True)
            self.instance.joinpath("state.json").write_text(
                json.dumps({"done": False, "seed": (start or {}).get("seed"), "target": None})
            )
            return {"selected": {"name": "alpha"}, "available": ["alpha", "beta"]}

        def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
            result = super().invoke(tool_name, arguments)
            if tool_name == "finish":
                self.instance.joinpath("state.json").write_text(
                    json.dumps({"done": True, "seed": 7, "target": arguments["name"]})
                )
            return result

    def open_actor(
        _candidate: Path,
        instance: Path,
        _public: dict[str, Any],
        _config: QualificationConfig,
    ) -> Actor:
        instances_seen.append(instance)
        return Actor(instance)

    capability = _capability()

    class FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        def call(self, operation: str, arguments: dict[str, Any]) -> Any:
            if operation == "capabilities":
                return [capability.to_document()]
            if operation == "start_cases":
                return [{"case_id": "seed-7", "reset_input": {"seed": 7}, "regime_tags": []}]
            if operation == "inspect":
                return json.loads(
                    Path(arguments["instance_directory"]).joinpath("state.json").read_text()
                )
            if operation == "enumerate_bindings":
                return [_binding("alpha").to_document(), _binding("beta").to_document()]
            if operation == "evaluate_atom":
                request = arguments["request"]
                target_matches = request["after_facts"].get("target") == request[
                    "protected_binding"
                ]["private_id"].removeprefix("secret-")
                satisfied = bool(
                    request["after_facts"]["done"]
                    and request["trace_projection"]
                    and target_matches
                    and request["final_answer"] == {"status": "done"}
                )
                return {
                    "initially_satisfied": False,
                    "satisfied": satisfied,
                    "required_effects_ok": satisfied,
                    "collateral_ok": True,
                    "answer_ok": satisfied,
                    "process_ok": satisfied,
                    "report_values": {"status": "done"} if satisfied else {},
                    "failure_codes": [] if satisfied else ["not_finished"],
                }
            raise AssertionError(operation)

        def close(self, *, operation: str | None = None) -> None:
            del operation

    def episode(**kwargs: Any) -> PublicCapabilityEpisode:
        actor = kwargs["actor"]
        target = kwargs["binding"].semantic_key
        observation = actor.invoke("finish", {"name": target})
        return PublicCapabilityEpisode(
            "finish-item",
            (TraceEvent(1, "finish", {"name": target}, observation),),
            {"status": "done"},
            "gpt-5.6-luna",
        )

    monkeypatch.setattr(semantic_qualification_module, "_ChildTransport", FakeTransport)
    monkeypatch.setattr(semantic_qualification_module, "_open_candidate_actor", open_actor)
    monkeypatch.setattr(
        semantic_qualification_module,
        "compute_candidate_digest",
        lambda _path: "a" * 64,
    )
    monkeypatch.setattr(
        semantic_qualification_module,
        "compute_semantics_project_digest",
        lambda _path: "b" * 64,
    )
    monkeypatch.setattr(
        semantic_qualification_module,
        "run_public_capability_episode",
        episode,
    )
    native_calls: list[dict[str, Any]] = []

    class FakeNativeOracleSession:
        def __init__(self, **_kwargs: Any) -> None:
            return None

        def check_atom(self, **kwargs: Any) -> NativeAtomEvidence:
            native_calls.append(kwargs)
            after = json.loads(Path(kwargs["after_instance"]).joinpath("state.json").read_text())
            target = kwargs["public_binding"]["public_descriptor"]["name"]
            satisfied = bool(
                after["done"]
                and kwargs["trace"]
                and after["target"] == target
                and kwargs["final_answer"] == {"status": "done"}
            )
            document = {
                "initially_satisfied": False,
                "satisfied": satisfied,
                "required_effects_ok": satisfied,
                "collateral_ok": True,
                "answer_ok": satisfied,
                "process_ok": satisfied,
                "report_values": {"status": "done"} if satisfied else {},
                "failure_codes": [] if satisfied else ["not_finished"],
            }
            return NativeAtomEvidence(
                f"native-{len(native_calls)}",
                "1" * 64,
                "2" * 64,
                kwargs["public_binding"],
                semantic_qualification_module.atom_result_from_document(document),
                ({"native": "fact"},),
                {"reader": "test"},
            )

        @property
        def evidence_digest(self) -> str:
            return "e" * 64

    monkeypatch.setattr(
        semantic_qualification_module,
        "NativeOracleSession",
        FakeNativeOracleSession,
    )
    semantics = SemanticsBuild(
        tmp_path / "semantics",
        "thread",
        tmp_path / "semantics-home",
        "factory",
        "b" * 64,
        (),
    )

    report = qualify_semantic_capabilities(
        semantics,
        qualification,
        tmp_path / "candidate",
        config=QualificationConfig(max_turns=2),
    )

    assert len(instances_seen) == 7
    assert {path.name for path in instances_seen} == {"before", "after", "instance"}
    assert report.capabilities[0].action_result.satisfied
    assert not report.capabilities[0].no_op_result.satisfied
    assert report.capabilities[0].wrong_target_checked
    assert report.capabilities[0].physical_wrong_target_checked
    assert report.capabilities[0].fresh_replay_passed
    assert report.native_evidence_digest == "e" * 64
    assert len(native_calls) == 10
    assert {item["role"] for item in native_calls} == {
        "primary",
        "fresh-replay",
        "wrong-answer",
        "no-op",
        "wrong-target",
    }
