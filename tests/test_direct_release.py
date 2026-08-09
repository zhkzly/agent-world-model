from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.request import Request

import pytest

from agent_world.artifacts import ArtifactStore
from agent_world.config import load_settings
from agent_world.contracts import (
    ArtifactRef,
    CandidateManifest,
    DesignContract,
    DirectRun,
    EnvironmentRequest,
)
from agent_world.foundry import (
    _CHALLENGE_SKILL,
    _PLAN_SKILL,
    _RESEARCH_SKILL,
    DirectFoundry,
    FoundryFailure,
)
from agent_world.invocation import InvocationResult
from agent_world.observe import observe_run


def _proposal(expected_result: object) -> dict[str, object]:
    return {
        "name": "inventory-handoff",
        "summary": "Track a handoff.",
        "tools": [
            {
                "name": "record_handoff",
                "description": "Records one handoff.",
                "arguments": [],
                "result_fields": ["value"],
            }
        ],
        "scenario": [
            {"tool": "record_handoff", "arguments": {}, "expected_result": expected_result}
        ],
        "invariants": [],
    }


def _runtime(root: Path, *, value: str = "ok") -> None:
    source = """import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    operation = request.get("op")
    if operation == "handshake":
        response = {"operations": ["handshake", "reset", "invoke", "close"]}
    elif operation == "reset":
        response = {"status": "ok"}
    elif operation == "invoke":
        response = {"status": "ok", "result": {"value": __VALUE__}}
    elif operation == "close":
        response = {"status": "ok"}
        print(json.dumps(response), flush=True)
        break
    else:
        response = {"status": "error"}
    print(json.dumps(response), flush=True)
"""
    (root / "runtime.py").write_text(
        source.replace("__VALUE__", repr(value)),
        encoding="utf-8",
    )


def test_framework_release_is_registry_backed_and_observable(tmp_path: Path) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    store = ArtifactStore(settings.state_root / "runs" / run.run_id)
    design = foundry._compile_design(_proposal({"value": "ok"}), store)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    _runtime(candidate_root)
    candidate = foundry._scan_candidate(candidate_root, store)
    report = foundry._judge(candidate_root, design, candidate, store)

    assert report.passed
    receipt, _ = foundry._release(design, candidate, report, candidate_root, store)

    run.finish("released", receipt=receipt)
    store.write_run(run)
    scene = observe_run(settings.state_root, run.run_id)

    assert scene["release"]["status"] == "released"
    assert scene["release"]["package_digest"] == receipt.package_digest


def test_candidate_scan_rejects_non_python_source(tmp_path: Path) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    store = ArtifactStore(settings.state_root / "runs" / "run_scan")
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    (candidate_root / "notes.txt").write_text("not Python", encoding="utf-8")

    with pytest.raises(FoundryFailure, match="candidate_source_non_python"):
        foundry._scan_candidate(candidate_root, store)


def test_compiler_freezes_scalar_result_in_artifact_and_projection(tmp_path: Path) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    store = ArtifactStore(settings.state_root / "runs" / "run_compiler")
    expected_result = {"value": True}

    design = foundry._compile_design(_proposal(expected_result), store)
    expected_result["value"] = False

    assert design.public_steps[0].expected_result == {"value": True}
    assert store.read_json(design.artifact)["public_steps"] == [
        {
            "tool": "record_handoff",
            "arguments": {},
            "expected_result": {"value": True},
        }
    ]
    assert foundry._design_projection(design)["public_step"]["expected_result"] == {"value": True}


def test_compiler_retains_long_invariant_in_contract_and_artifact(tmp_path: Path) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    store = ArtifactStore(settings.state_root / "runs" / "run_compiler")
    invariant = (
        "A handoff must preserve the originating inventory owner and destination across every "
        "recorded transfer step. Additional audit context is retained for independent verification."
    )
    assert 100 < len(invariant) < 500

    proposal = _proposal({"value": "ok"})
    proposal["invariants"] = [invariant]
    design = foundry._compile_design(proposal, store)

    assert design.invariants == (invariant,)
    assert store.read_json(design.artifact)["invariants"] == [invariant]


def test_design_prompt_matches_existing_tool_name_compiler_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    store = ArtifactStore(settings.state_root / "runs" / "run_design_prompt")
    captured: list[str] = []

    def fake_invoke_json(*, system: str, user: str) -> InvocationResult:
        assert "Direct semantic designer" in system
        captured.append(user)
        return InvocationResult(value=_proposal({"value": "ok"}), route_model="test-direct")

    monkeypatch.setattr(foundry.direct, "invoke_json", fake_invoke_json)

    design = foundry._design(
        EnvironmentRequest.create("Track an inventory handoff"),
        {
            "sources": [{"url": "https://example.invalid/evidence"}],
            "claims": ["The source supports inventory handoffs."],
        },
        store,
    )

    assert len(captured) == 1
    payload = json.loads(captured[0])
    output = payload["output"]
    assert output["tools"][0]["name"] == "tool_name"
    assert output["scenario"][0]["tool"] == "tool_name"
    assert (
        "Every tool name must use lower snake_case matching [a-z][a-z0-9_]{0,59}; "
        "the scenario tool must exactly equal one declared tool name."
    ) in payload["rules"]
    assert (
        "Each tool's result_fields must be a nonempty list of at most 6 unique, "
        "nonempty short public text field names."
    ) in payload["rules"]
    assert (
        "Each tool's arguments must be a list of at most 6 unique, nonempty short "
        "public argument names; use [] when none."
    ) in payload["rules"]
    assert design.tools[0].name == "record_handoff"
    assert design.public_steps[0].tool == "record_handoff"

    hyphenated = _proposal({"value": "ok"})
    hyphenated["tools"] = [
        {
            "name": "record-handoff",
            "description": "Records one handoff.",
            "arguments": [],
            "result_fields": ["value"],
        }
    ]
    hyphenated["scenario"] = [
        {"tool": "record-handoff", "arguments": {}, "expected_result": {"value": "ok"}}
    ]
    with pytest.raises(FoundryFailure) as error:
        foundry._compile_design(hyphenated, store)
    assert error.value.failure.code == "design_tool_invalid"

    empty_result_fields = _proposal({"value": "ok"})
    empty_result_fields["tools"] = [
        {
            "name": "record_handoff",
            "description": "Records one handoff.",
            "arguments": [],
            "result_fields": [],
        }
    ]
    with pytest.raises(FoundryFailure) as error:
        foundry._compile_design(empty_result_fields, store)
    assert error.value.failure.code == "design_tool_invalid"


def test_advisory_agent_skills_state_list_contract_and_accept_valid_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    store = ArtifactStore(settings.state_root / "runs" / "run_advice")
    design = foundry._compile_design(_proposal({"value": "ok"}), store)
    long_step = (
        "Implement the public runtime protocol while preserving framework-owned validation, "
        "source closure, and isolated execution boundaries."
    )
    long_risk = (
        "Verify that public tool behavior remains conformant across reset, invocation, "
        "restart, and independent runtime execution boundaries."
    )
    assert 100 < len(long_step) <= 500
    assert 100 < len(long_risk) <= 500
    responses = {
        "build_implementation_plan": {"steps": [long_step, "Map runtime behavior"]},
        "verifier_intent": {"risks": [long_risk, "Check restart behavior"]},
    }
    expected_instructions = {
        "build_implementation_plan": 'Return exactly {"steps":["short advisory item"]}.',
        "verifier_intent": 'Return exactly {"risks":["short advisory item"]}.',
    }
    captured: dict[str, tuple[str, str]] = {}
    design_files_seen: dict[str, bool] = {}

    def fake_invoke_json(
        *,
        work: str,
        skill_name: str,
        skill_body: str,
        workspace: Path,
        instruction: str,
        writable: bool = False,
        require_json: bool = True,
    ) -> InvocationResult:
        design_file = workspace / ".foundry-design.json"
        design_files_seen[work] = design_file.is_file()
        assert design_file.is_file()
        assert json.loads(design_file.read_text(encoding="utf-8")) == json.loads(
            json.dumps(foundry._design_projection(design))
        )
        assert instruction == expected_instructions[work]
        assert writable is False
        assert require_json is True
        captured[work] = (skill_name, skill_body)
        return InvocationResult(value=responses[work], route_model="test-agent")

    monkeypatch.setattr(foundry.agent, "invoke_json", fake_invoke_json)

    plan = foundry._advice(
        work="build_implementation_plan",
        skill_name="engineer-build-planning",
        skill_body=_PLAN_SKILL,
        design=design,
        field="steps",
    )
    challenge = foundry._advice(
        work="verifier_intent",
        skill_name="challenge-agent-world",
        skill_body=_CHALLENGE_SKILL,
        design=design,
        field="risks",
    )

    assert plan == {"steps": (long_step, "Map runtime behavior"), "model": "test-agent"}
    assert challenge == {
        "risks": (long_risk, "Check restart behavior"),
        "model": "test-agent",
    }
    assert design_files_seen == {"build_implementation_plan": True, "verifier_intent": True}
    plan_name, plan_skill = captured["build_implementation_plan"]
    challenge_name, challenge_skill = captured["verifier_intent"]
    assert plan_name == "engineer-build-planning"
    assert 'Return exactly {"steps":["short advisory item"]}.' in plan_skill
    assert (
        "self-check\nthat `steps` contains 1-8 unique, nonempty items, each at most 500 characters."
        in plan_skill
    )
    assert challenge_name == "challenge-agent-world"
    assert 'Return exactly {"risks":["short public risk"]}.' in challenge_skill
    assert (
        "self-check\nthat `risks` contains 1-8 unique, nonempty items, each at most 500 characters."
        in challenge_skill
    )


def test_researcher_skill_states_claims_contract_and_actual_handoff_accepts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    request = EnvironmentRequest.create("Track a public inventory handoff")
    store = ArtifactStore(settings.state_root / "runs" / "run_research")
    documents = {
        "https://example.com/handoffs": "Public handbook covers handoff confirmation.",
        "https://example.org/inventory": "Public guide covers inventory transfer records.",
    }
    long_claim = (
        "The public handoff handbook requires the receiving worker to record confirmation, "
        "responsible party, timestamp, and exception note before inventory status changes."
    )
    captured: dict[str, object] = {}
    stages: list[str] = []

    monkeypatch.setenv(settings.research.api_key_env, "test-research-key")

    def fake_http_text(url: str, *, key: str | None, stage: str) -> str:
        stages.append(stage)
        assert key == "test-research-key"
        if stage == "research_search":
            return "\n".join(documents)
        assert stage == "research_fetch"
        for source, document in documents.items():
            if url.endswith(source):
                return document
        raise AssertionError("unexpected research source")

    def fake_invoke_json(
        *,
        work: str,
        skill_name: str,
        skill_body: str,
        workspace: Path,
        instruction: str,
        writable: bool = False,
        require_json: bool = True,
    ) -> InvocationResult:
        evidence_file = workspace / ".foundry-evidence.json"
        assert evidence_file.is_file()
        captured["evidence"] = json.loads(evidence_file.read_text(encoding="utf-8"))
        captured["work"] = work
        captured["skill_name"] = skill_name
        captured["skill_body"] = skill_body
        captured["instruction"] = instruction
        captured["writable"] = writable
        captured["require_json"] = require_json
        return InvocationResult(
            value={
                "claims": [
                    long_claim,
                    "The guide records inventory transfers.",
                ]
            },
            route_model="test-agent",
        )

    monkeypatch.setattr(foundry, "_http_text", fake_http_text)
    monkeypatch.setattr(foundry.agent, "invoke_json", fake_invoke_json)

    research = foundry._research(request, store)

    assert stages == ["research_search", "research_fetch", "research_fetch"]
    assert captured["evidence"] == {
        "request_digest": request.need_digest,
        "sources": [{"url": source, "text": document} for source, document in documents.items()],
    }
    assert captured["work"] == "researcher"
    assert captured["skill_name"] == "research-world-evidence"
    assert captured["skill_body"] == _RESEARCH_SKILL
    assert captured["instruction"] == (
        'Read staged evidence and return exactly {"claims":["short source-backed claim"]}.'
    )
    assert captured["writable"] is False
    assert captured["require_json"] is True
    assert 'Return exactly {"claims":["short source-backed claim"]}.' in _RESEARCH_SKILL
    assert (
        "self-check that `claims` contains 1-8 unique, nonempty short source-backed text\nitems."
        in _RESEARCH_SKILL
    )
    assert 100 < len(long_claim) < 500
    assert research["claims"] == (long_claim, "The guide records inventory transfers.")
    artifact = store.read_json(research["artifact"])
    assert artifact["claims"] == list(research["claims"])
    assert artifact["agent_model"] == "test-agent"
    assert [item["url"] for item in artifact["sources"]] == list(documents)
    assert all(item["content_digest"].startswith("sha256:") for item in artifact["sources"])
    assert [item["content_length"] for item in artifact["sources"]] == [
        len(document.encode("utf-8")) for document in documents.values()
    ]


def test_research_http_request_preserves_headers_with_and_without_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    captured: list[Request] = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"source body"

    def fake_urlopen(request: Request, timeout: int) -> FakeResponse:
        assert timeout == 120
        captured.append(request)
        return FakeResponse()

    monkeypatch.setattr("agent_world.foundry.urlopen", fake_urlopen)

    assert foundry._http_text(
        "https://example.invalid/no-key", key=None, stage="research_search"
    ) == ("source body")
    assert (
        foundry._http_text(
            "https://example.invalid/with-key", key="test-only-key", stage="research_search"
        )
        == "source body"
    )

    no_key_headers = {name.lower(): value for name, value in captured[0].header_items()}
    with_key_headers = {name.lower(): value for name, value in captured[1].header_items()}
    for headers in (no_key_headers, with_key_headers):
        assert headers["accept"] == "text/plain, text/markdown, text/html"
        assert headers["user-agent"] == "agent-world-foundry/0.3"
    assert "authorization" not in no_key_headers
    assert with_key_headers["authorization"] == "Bearer test-only-key"


@pytest.mark.parametrize(
    "expected_result",
    (
        {},
        {"undeclared": "value"},
        {"value": []},
        {"value": {"nested": "value"}},
        {"value": float("nan")},
        {"value": float("inf")},
    ),
    ids=("empty", "undeclared", "array", "object", "nan", "infinity"),
)
def test_compiler_rejects_invalid_expected_result(tmp_path: Path, expected_result: object) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)
    store = ArtifactStore(settings.state_root / "runs" / "run_compiler")

    with pytest.raises(FoundryFailure, match="design_scenario_invalid"):
        foundry._compile_design(_proposal(expected_result), store)


def test_failed_judge_cannot_reach_registry_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    foundry = DirectFoundry(settings)

    def research(_: EnvironmentRequest, store: ArtifactStore) -> dict[str, object]:
        return {"artifact": store.put_json("research", {"sources": [], "claims": []})}

    def design(
        _: EnvironmentRequest, __: dict[str, object], store: ArtifactStore
    ) -> DesignContract:
        return foundry._compile_design(_proposal({"value": "ok"}), store)

    def build(
        _: DesignContract, candidate_root: Path, store: ArtifactStore
    ) -> tuple[CandidateManifest, tuple[ArtifactRef, ...]]:
        _runtime(candidate_root, value="wrong")
        return foundry._scan_candidate(candidate_root, store), ()

    monkeypatch.setattr(foundry, "_research", research)
    monkeypatch.setattr(foundry, "_design", design)
    monkeypatch.setattr(foundry, "_build", build)

    result = foundry.generate("Track an inventory handoff")
    run = ArtifactStore(settings.state_root / "runs" / str(result["run_id"])).read_run()

    assert result["status"] == "rejected"
    assert result["release"] == {"status": "not_published"}
    assert any(event["stage"] == "judge" and event["status"] == "failed" for event in run["events"])
    assert all(event["stage"] != "registry" for event in run["events"])
    assert not (settings.state_root / "registry").exists()
