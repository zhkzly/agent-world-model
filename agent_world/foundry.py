"""Direct composition root: request -> two fixed graphs -> Registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_world.artifacts import ArtifactStore
from agent_world.candidate import CandidateError, CandidateExecutor, _verify_package
from agent_world.config import FoundrySettings, load_settings
from agent_world.contracts import (
    DirectRun,
    EnvironmentRequest,
    SafeFailure,
)
from agent_world.design import DesignError, DesignExecutor
from agent_world.graph import candidate_graph, design_graph
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

    def generate(self, need: str) -> dict[str, Any]:
        request = EnvironmentRequest.create(need)
        run = DirectRun.create(request)
        store = ArtifactStore(self.settings.state_root / "runs" / run.run_id)
        self._event(store, run, "intake", "passed")
        try:
            design_result = self.designer.run(request, store, design_graph(), run.run_id)
            run.add_work_records(design_result.work_refs)
            store.write_run(run)
            candidate_result = self.builder.run(
                design_result.design, store, candidate_graph(), run.run_id
            )
            run.add_work_records(candidate_result.work_refs)
            run.finish("released", package_ref=candidate_result.package_ref)
            store.write_run(run)
            return self._result(run)
        except DesignError as exc:
            return self._fail(store, run, SafeFailure(exc.code, exc.status, exc.retryable))
        except CandidateError as exc:
            return self._fail(store, run, SafeFailure(exc.code, exc.status, exc.retryable))
        except InvocationError as exc:
            return self._fail(store, run, exc.failure)
        except (OSError, ValueError, TypeError) as exc:
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

    @staticmethod
    def _verify_package(path: Path, expected_digest: str, manifest: dict[str, Any]) -> None:
        _verify_package(path, expected_digest, manifest)


def _safe_internal_code(exc: BaseException) -> str:
    del exc
    return "foundry_internal_error"


def generate(need: str, config_path: Path | str) -> dict[str, Any]:
    """Public Direct API. It returns an honest terminal result."""

    return DirectFoundry(load_settings(config_path)).generate(need)


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
