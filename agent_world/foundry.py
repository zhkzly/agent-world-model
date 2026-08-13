"""Direct composition root: request -> two fixed graphs -> Registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_world.artifacts import ArtifactStore
from agent_world.candidate import CandidateError, CandidateExecutor
from agent_world.config import FoundrySettings, load_settings
from agent_world.contracts import (
    ArtifactRef,
    DirectRun,
    EnvironmentRequest,
    RunEvent,
    SafeFailure,
)
from agent_world.design import DesignError, DesignExecutor
from agent_world.graph import (
    CANDIDATE_EDGES,
    CANDIDATE_NODES,
    DESIGN_EDGES,
    DESIGN_NODES,
    ResumeContext,
    candidate_graph,
    compute_upstream,
    design_graph,
)
from agent_world.invocation import CodexAgentBackend, DirectChatBackend, InvocationError


class FoundryFailure(RuntimeError):
    def __init__(self, failure: SafeFailure) -> None:
        super().__init__(failure.code)
        self.failure = failure


class DirectFoundry:
    """The controller owns lifecycle facts; graph executors own node work."""

    def __init__(self, settings: FoundrySettings) -> None:
        self.settings = settings
        self.direct = DirectChatBackend(settings.direct_primary, settings.direct_fallback)
        self.agent = CodexAgentBackend(settings.agent_primary, settings.agent_fallback)
        self.designer = DesignExecutor(settings, self.direct, self.agent)
        self.builder = CandidateExecutor(settings, self.agent, settings.trusted_wheel_store)

    def generate(
        self,
        need: str,
        *,
        resume_run_id: str | None = None,
        restart_from: str | None = None,
    ) -> dict[str, Any]:
        if resume_run_id is not None:
            return self._generate_resume(need, resume_run_id, restart_from)
        return self._generate_fresh(need)

    def _generate_fresh(self, need: str) -> dict[str, Any]:
        request = EnvironmentRequest.create(need)
        run = DirectRun.create(request)
        store = ArtifactStore(self.settings.state_root / "runs" / run.run_id)
        heads_path = store.run_root / "heads.json"
        resume = ResumeContext()
        self._event(store, run, "intake", "passed")
        try:
            dgraph = design_graph()
            dgraph.resume = resume
            design_result = self.designer.run(request, store, dgraph, run.run_id, resume=resume)
            resume.save(heads_path)
            run.add_work_records(design_result.work_refs)
            store.write_run(run)
            cgraph = candidate_graph()
            cgraph.resume = resume
            candidate_result = self.builder.run(
                design_result.design, store, cgraph, run.run_id, resume=resume
            )
            resume.save(heads_path)
            run.add_work_records(candidate_result.work_refs)
            run.finish("released", package_ref=candidate_result.package_ref)
            store.write_run(run)
            return self._result(run)
        except DesignError as exc:
            resume.save(heads_path)
            return self._fail(store, run, SafeFailure(exc.code, exc.status, exc.retryable))
        except CandidateError as exc:
            resume.save(heads_path)
            return self._fail(store, run, SafeFailure(exc.code, exc.status, exc.retryable))
        except InvocationError as exc:
            resume.save(heads_path)
            return self._fail(store, run, exc.failure)
        except (OSError, ValueError, TypeError) as exc:
            resume.save(heads_path)
            return self._fail(store, run, SafeFailure(_safe_internal_code(exc), "error"))

    def _generate_resume(
        self, need: str, resume_run_id: str, restart_from: str | None
    ) -> dict[str, Any]:
        run_root = self.settings.state_root / "runs" / resume_run_id
        store = ArtifactStore(run_root)
        run_payload = store.read_run()
        run = DirectRun(
            run_id=run_payload["run_id"],
            request_id=run_payload["request_id"],
            request_digest=run_payload["request_digest"],
            status=run_payload["status"],
            started_at=run_payload["started_at"],
            ended_at=run_payload["ended_at"],
            events=[
                RunEvent(
                    stage=e["stage"],
                    status=e["status"],
                    at=e["at"],
                    code=e["code"],
                    artifact_ids=tuple(e["artifact_ids"]),
                )
                for e in run_payload["events"]
            ],
            artifacts=[ArtifactRef(**a) for a in run_payload["artifacts"]],
            work_records=[ArtifactRef(**w) for w in run_payload["work_records"]],
        )
        request = EnvironmentRequest(
            request_id=run.request_id, need=need, need_digest=run.request_digest
        )
        heads_path = run_root / "heads.json"
        skip_node_ids: set[str] = set()
        if restart_from is not None:
            skip_node_ids = compute_upstream(
                restart_from, DESIGN_NODES, DESIGN_EDGES, CANDIDATE_NODES, CANDIDATE_EDGES
            )
        if heads_path.exists():
            resume = ResumeContext.load(heads_path)
        else:
            resume = ResumeContext()
        resume.restart_from = restart_from
        resume.skip_node_ids = skip_node_ids
        try:
            dgraph = design_graph()
            dgraph.resume = resume
            design_result = self.designer.run(request, store, dgraph, run.run_id, resume=resume)
            resume.save(heads_path)
            run.add_work_records(design_result.work_refs)
            store.write_run(run)
            cgraph = candidate_graph()
            cgraph.resume = resume
            candidate_result = self.builder.run(
                design_result.design, store, cgraph, run.run_id, resume=resume
            )
            resume.save(heads_path)
            run.add_work_records(candidate_result.work_refs)
            run.finish("released", package_ref=candidate_result.package_ref)
            store.write_run(run)
            return self._result(run)
        except DesignError as exc:
            resume.save(heads_path)
            return self._fail(store, run, SafeFailure(exc.code, exc.status, exc.retryable))
        except CandidateError as exc:
            resume.save(heads_path)
            return self._fail(store, run, SafeFailure(exc.code, exc.status, exc.retryable))
        except InvocationError as exc:
            resume.save(heads_path)
            return self._fail(store, run, exc.failure)
        except (OSError, ValueError, TypeError) as exc:
            resume.save(heads_path)
            return self._fail(store, run, SafeFailure(_safe_internal_code(exc), "error"))

    def _event(self, store: ArtifactStore, run: DirectRun, stage: str, status: str) -> None:
        run.add_event(stage, status)
        store.write_run(run)

    def _fail(self, store: ArtifactStore, run: DirectRun, failure: SafeFailure) -> dict[str, Any]:
        run.finish(failure.status, code=failure.code)
        store.write_run(run)
        return self._result(run)

    @staticmethod
    def _result(run: DirectRun) -> dict[str, Any]:
        package_ref = run.release
        return {
            "run_id": run.run_id,
            "status": run.status,
            "release": (
                {
                    "status": "released",
                    "package_id": package_ref.package_id,
                    "version": package_ref.version,
                    "package_digest": package_ref.package_digest,
                    "manifest_digest": package_ref.manifest_digest,
                    "registry_receipt_digest": package_ref.registry_receipt_ref.digest,
                }
                if package_ref is not None
                else {"status": "not_published"}
            ),
        }

def _safe_internal_code(exc: BaseException) -> str:
    del exc
    return "foundry_internal_error"


def generate(
    need: str,
    config_path: Path | str,
    *,
    resume_run_id: str | None = None,
    restart_from: str | None = None,
) -> dict[str, Any]:
    """Public Direct API. It returns an honest terminal result."""

    return DirectFoundry(load_settings(config_path)).generate(
        need, resume_run_id=resume_run_id, restart_from=restart_from
    )


def check_config(config_path: Path | str) -> dict[str, str]:
    settings = load_settings(config_path)
    return {
        "status": "ok",
        "direct_primary": settings.direct_primary.model,
        "direct_fallback": settings.direct_fallback.model,
        "agent_primary": settings.agent_primary.model,
        "agent_fallback": settings.agent_fallback.model,
        "research": "configured",
    }
