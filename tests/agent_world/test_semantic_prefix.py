from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import HttpUrl

from agent_world.app import build_application
from agent_world.cli import build_parser
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    ArtifactRef,
    BudgetUsage,
    GenerationContext,
    sha256_digest,
)
from agent_world.control.direct_runner import DirectWorkRunner, SemanticPrefixRun
from agent_world.control.semantic_prefix import SemanticPrefixError, SemanticPrefixRunner
from agent_world.diagnostic_state import is_marked_test_node_diagnostic_state_root
from agent_world.observability import SceneProjector


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "configured-state",
        agent=AgentBackendConfig(
            model="grok-4.5",
            api_key_environment="OPENAI_API_KEY",
            openai_base_url_environment="OPENAI_BASE_URL",
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )


def _ref(name: str, artifact_type: str = "control.test") -> ArtifactRef:
    digest = sha256_digest(name.encode())
    return ArtifactRef(
        artifact_id=name,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=1,
    )


def test_semantic_prefix_cli_exposes_only_need_and_request_identity() -> None:
    parsed = build_parser().parse_args(
        [
            "semantic-prefix",
            "--need",
            "用户预订宾馆",
            "--request-id",
            "semantic-prefix:test",
        ]
    )

    assert parsed.command == "semantic-prefix"
    assert parsed.need == "用户预订宾馆"
    assert parsed.request_id == "semantic-prefix:test"
    assert not hasattr(parsed, "target_coordinate")
    assert not hasattr(parsed, "diagnostic_state_root")


def test_semantic_prefix_ready_requires_complete_active_commit_closure() -> None:
    with pytest.raises(
        ValueError,
        match="ready semantic prefix requires its complete typed commit closure",
    ):
        SemanticPrefixRun(
            run_id="semantic-prefix:incomplete",
            scope_id="generate-job:incomplete",
            context_ref=_ref("context:incomplete", "control.generation_context"),
            status="semantic_prefix_ready",
            bootstrap_epoch_ref=_ref(
                "epoch:incomplete-bootstrap",
                "control.work_graph_epoch",
            ),
            observed_actual=BudgetUsage(),
            unknown_upper_bound=BudgetUsage(),
        )


@pytest.mark.asyncio
async def test_semantic_prefix_rejects_reserved_live_state_parent(
    tmp_path: Path,
) -> None:
    runner = SemanticPrefixRunner(
        config=_config(tmp_path),
        state_parent=tmp_path / ".agent-world-live",
    )

    with pytest.raises(
        SemanticPrefixError,
        match="normal semantic-prefix state cannot use the reserved live directory",
    ):
        await runner.run(need="用户预订宾馆")


@pytest.mark.asyncio
async def test_controller_semantic_prefix_creates_normal_context_without_direct_job_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-credential-canary")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unit.invalid/v1")
    app = build_application(_config(tmp_path))
    captured: dict[str, object] = {}

    class FakePrefixRunner:
        async def run_semantic_prefix(
            self,
            *,
            context_ref: ArtifactRef,
            run_id: str,
        ) -> SemanticPrefixRun:
            captured["context_ref"] = context_ref
            captured["run_id"] = run_id
            context = app.controller.artifacts.get_json(
                context_ref,
                GenerationContext,
            )
            bootstrap_epoch_ref = app.controller.artifacts.put_json(
                artifact_id="epoch:bootstrap",
                artifact_type="control.work_graph_epoch",
                value={"kind": "bootstrap"},
            )
            design_epoch_ref = app.controller.artifacts.put_json(
                artifact_id="epoch:design",
                artifact_type="control.work_graph_epoch",
                value={"kind": "design"},
            )
            modeling_commit_ref = app.controller.artifacts.put_json(
                artifact_id="commit:modeling",
                artifact_type="control.work_commit",
                value={"kind": "modeling"},
            )
            verifier_plan_commit_ref = app.controller.artifacts.put_json(
                artifact_id="commit:verifier-plan",
                artifact_type="control.work_commit",
                value={"kind": "verifier-plan"},
            )
            return SemanticPrefixRun(
                run_id=run_id,
                scope_id=app.controller.artifacts.get_json(context.job_ref)["job_id"],
                context_ref=context_ref,
                status="semantic_prefix_ready",
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                design_epoch_ref=design_epoch_ref,
                modeling_commit_ref=modeling_commit_ref,
                verifier_plan_commit_ref=verifier_plan_commit_ref,
                environment_design_ref=_ref(
                    "design:environment",
                    "design.environment_design",
                ),
                verifier_batch_plan_ref=_ref(
                    "plan:verifier-batches",
                    "judge.verifier_batch_plan",
                ),
                observed_actual=BudgetUsage(),
                unknown_upper_bound=BudgetUsage(),
            )

    app.controller.direct_work_runner = FakePrefixRunner()  # type: ignore[assignment]
    outcome = await app.controller.run_semantic_prefix(
        "用户预订宾馆",
        request_id="semantic-prefix:controller-test",
    )

    assert outcome.status == "semantic_prefix_ready"
    assert outcome.diagnostic_only is False
    assert outcome.release_attempted is False
    context_ref = captured["context_ref"]
    assert isinstance(context_ref, ArtifactRef)
    context = app.controller.artifacts.get_json(context_ref, GenerationContext)
    request = app.controller.artifacts.get_json(context.request_ref)
    job = app.controller.artifacts.get_json(context.job_ref)
    assert request["need"] == "用户预订宾馆"
    assert job["job_id"] == outcome.scope_id
    assert not tuple((app.config.state_root / "direct-jobs" / "heads").iterdir())


@pytest.mark.asyncio
async def test_semantic_prefix_runner_uses_a_fresh_non_diagnostic_state_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-credential-canary")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unit.invalid/v1")

    async def fake_controller_run(
        controller,
        need: str,
        *,
        request_id: str | None = None,
        permissions=None,
        budget=None,
        release_profile=None,
    ) -> SemanticPrefixRun:
        del controller, permissions, budget, release_profile
        assert need == "用户预订宾馆"
        assert request_id == "semantic-prefix:fresh-root"
        return SemanticPrefixRun(
            run_id="semantic-prefix:run",
            scope_id="generate-job:fresh-root",
            context_ref=_ref("context:fresh", "control.generation_context"),
            status="semantic_prefix_ready",
            bootstrap_epoch_ref=_ref(
                "epoch:fresh-bootstrap",
                "control.work_graph_epoch",
            ),
            design_epoch_ref=_ref(
                "epoch:fresh-design",
                "control.work_graph_epoch",
            ),
            modeling_commit_ref=_ref(
                "commit:fresh-modeling",
                "control.work_commit",
            ),
            verifier_plan_commit_ref=_ref(
                "commit:fresh-verifier-plan",
                "control.work_commit",
            ),
            environment_design_ref=_ref(
                "design:fresh-environment",
                "design.environment_design",
            ),
            verifier_batch_plan_ref=_ref(
                "plan:fresh-verifier-batches",
                "judge.verifier_batch_plan",
            ),
            observed_actual=BudgetUsage(),
            unknown_upper_bound=BudgetUsage(),
        )

    class _SceneValue:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return self.value

    monkeypatch.setattr(
        "agent_world.controller.FoundryController.run_semantic_prefix",
        fake_controller_run,
    )
    monkeypatch.setattr(
        SceneProjector,
        "rebuild",
        lambda _self, scope_id, *, run_id: SimpleNamespace(
            index=_SceneValue({"scope_id": scope_id, "run_id": run_id}),
            coordinates=(),
        ),
    )
    result = await SemanticPrefixRunner(
        config=_config(tmp_path),
        state_parent=tmp_path / ".agent-world-staged",
    ).run(
        need="用户预订宾馆",
        request_id="semantic-prefix:fresh-root",
    )

    state_root = Path(result.state_root)
    assert state_root.parent == (tmp_path / ".agent-world-staged").resolve()
    assert state_root.name.startswith("semantic-prefix-")
    assert is_marked_test_node_diagnostic_state_root(state_root) is False
    assert not (state_root / "work-control" / ".test-node-diagnostic").exists()
    assert result.diagnostic_only is False
    assert result.release_attempted is False
    assert result.scene["coordinates"] == []


@pytest.mark.asyncio
async def test_direct_runner_semantic_prefix_never_enters_final_executors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_ref = _ref("context:control-flow", "control.generation_context")
    outcome = SemanticPrefixRun(
        run_id="semantic-prefix:control-flow",
        scope_id="generate-job:control-flow",
        context_ref=context_ref,
        status="semantic_prefix_ready",
        bootstrap_epoch_ref=_ref(
            "epoch:control-flow-bootstrap",
            "control.work_graph_epoch",
        ),
        design_epoch_ref=_ref(
            "epoch:control-flow-design",
            "control.work_graph_epoch",
        ),
        modeling_commit_ref=_ref(
            "commit:control-flow-modeling",
            "control.work_commit",
        ),
        verifier_plan_commit_ref=_ref(
            "commit:control-flow-plan",
            "control.work_commit",
        ),
        environment_design_ref=_ref(
            "design:control-flow",
            "design.environment_design",
        ),
        verifier_batch_plan_ref=_ref(
            "plan:control-flow",
            "judge.verifier_batch_plan",
        ),
        observed_actual=BudgetUsage(),
        unknown_upper_bound=BudgetUsage(),
    )
    finished: list[str] = []

    class _Span:
        span_id = "span:semantic-prefix"

        def finish(self, *, status: str, **_kwargs) -> None:
            finished.append(status)

    class _Telemetry:
        def start_span(self, **_kwargs):
            return _Span()

        def activate_trace(self, **_kwargs) -> None:
            return None

        def flush(self) -> None:
            return None

    runner = DirectWorkRunner(
        artifacts=object(),  # type: ignore[arg-type]
        heads=object(),  # type: ignore[arg-type]
        designer=object(),  # type: ignore[arg-type]
        builder=object(),  # type: ignore[arg-type]
        verifier_compiler=object(),  # type: ignore[arg-type]
        judge=object(),  # type: ignore[arg-type]
        registry=object(),  # type: ignore[arg-type]
        telemetry=_Telemetry(),  # type: ignore[arg-type]
        workspace_root=tmp_path,
        structured_turn_token_limit=32_768,
        structured_turn_wall_seconds=30,
    )
    monkeypatch.setattr(
        DirectWorkRunner,
        "_load_context",
        lambda _self, _context_ref: (
            SimpleNamespace(context_id="context:control-flow"),
            SimpleNamespace(job_id="generate-job:control-flow"),
            object(),
        ),
    )

    async def fake_prefix_execution(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(
        DirectWorkRunner,
        "_run_semantic_prefix_under_trace",
        fake_prefix_execution,
    )
    monkeypatch.setattr(
        DirectWorkRunner,
        "_semantic_prefix_outcome",
        lambda *_args, **_kwargs: outcome,
    )
    monkeypatch.setattr(
        DirectWorkRunner,
        "_final_executors",
        lambda *_args, **_kwargs: pytest.fail("semantic-prefix must not construct final executors"),
    )

    result = await runner.run_semantic_prefix(context_ref=context_ref)

    assert result == outcome
    assert finished == ["passed"]
