"""Framework-owned executable Candidate pre-commit probes.

These probes validate the exact logical Candidate workspace that later runtime
components receive.  They never decide WorldSpec semantics and never ask the
Code Agent to infer, translate, or repair framework deployment topology.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .models import CandidateCompletion
from .workspace import (
    CandidateWorkspaceDiagnostic,
    CandidateWorkspaceError,
    ValidatedCandidateWorkspace,
)

if TYPE_CHECKING:
    from agent_world.judge.supervisor import (
        CandidateProcessRunner,
        CleanCandidateBuilder,
        ProcessResult,
    )


_MISSING_MODULE_ERROR = re.compile(
    r"\bModuleNotFoundError: No module named ['\"][A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*['\"]"
)


class CandidatePrecommitInfrastructureError(RuntimeError):
    """The framework could not establish the Candidate host-process probe."""


class _CleanBuildFailure(Protocol):
    """The minimal safe shape exposed by the clean-build boundary."""

    code: str


def _classify_clean_build_error(error: _CleanBuildFailure) -> CandidateWorkspaceError:
    """Keep framework execution topology out of an Engineer correction turn.

    The only clean-build terminal that can be offered back to the Engineer is
    a completed offline ``uv sync`` whose frozen Candidate project itself
    returned a non-zero result.  The Engineer owns that project's relative
    metadata and can reproduce the same command from its logical
    ``candidate/`` directory.

    Every other ``CandidateBuildError`` arises before that proof, or reports
    framework-owned source handoff, integrity, tool, or timeout
    state.  In particular, it must never become a suggestion about host paths
    or the later Judge mount: no Code Agent can act on those facts.
    """

    # Keep the exact same attribution rule as Integration and the final
    # Judge. A later boundary must not turn an infrastructure terminal into a
    # different Code-Agent repair instruction.
    from agent_world.judge.supervisor import candidate_clean_build_failure_is_agent_actionable

    if candidate_clean_build_failure_is_agent_actionable(error.code):
        return CandidateWorkspaceError(
            "candidate dependency-only offline installation did not complete",
            safe_diagnostic=CandidateWorkspaceDiagnostic(
                "candidate_workspace_materialization_failed"
            ),
        )
    raise CandidatePrecommitInfrastructureError(
        "framework clean Candidate execution boundary is unavailable"
    )


class CandidateWorkspaceProbe(Protocol):
    """Run one framework-owned executable pre-commit boundary."""

    async def validate(
        self,
        *,
        candidate_root: Path,
        completion: CandidateCompletion,
        validated: ValidatedCandidateWorkspace,
    ) -> None: ...


def _public_test_diagnostic(result: ProcessResult) -> CandidateWorkspaceDiagnostic:
    """Classify one failed public-test result without persisting its output.

    Candidate stdout/stderr is untrusted.  A missing-import traceback is useful
    only as a bounded *kind* of failure: the Engineer can inspect its own test
    and project metadata, while the control plane must not retain arbitrary
    test text or a candidate-controlled import name.
    """

    if _MISSING_MODULE_ERROR.search(result.stderr):
        return CandidateWorkspaceDiagnostic("candidate_workspace_public_test_import_unavailable", 1)
    return CandidateWorkspaceDiagnostic("candidate_workspace_public_test_failed", 1)


@dataclass(frozen=True, slots=True)
class HostCandidateWorkspaceProbe:
    """Run declared public tests in the clean Candidate host workspace."""

    clean_builder: CleanCandidateBuilder
    process_runner: CandidateProcessRunner
    public_test_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.public_test_timeout_seconds <= 0:
            raise ValueError("public_test_timeout_seconds must be positive")

    async def validate(
        self,
        *,
        candidate_root: Path,
        completion: CandidateCompletion,
        validated: ValidatedCandidateWorkspace,
    ) -> None:
        # Import lazily to keep the Builder -> Judge composition dependency out
        # of module initialization.  ``judge.__init__`` also exports leaves
        # that import Builder, while this method runs only after Builder is
        # fully constructed.
        from agent_world.judge.supervisor import (
            CandidateBuildError,
            HostExecutionUnavailable,
            JudgeInfrastructureError,
        )

        visible_paths = tuple(item.path for item in validated.files)
        try:
            async with self.clean_builder.materialize(
                candidate_root,
                expected_source_files=validated.package_files,
                expected_source_tree_digest=validated.candidate_source_tree_digest,
            ) as clean:
                # This is deliberately separate from Candidate public tests.
                # If the framework's cwd/environment projection is wrong, it is an
                # infrastructure failure that the Code Agent cannot diagnose
                # or repair from its own workspace.
                await self.process_runner.verify_workspace_execution(
                    clean.root,
                    visible_workspace_paths=visible_paths,
                )
                for test_path in completion.public_test_paths:
                    result = await self.process_runner.run_public_test(
                        clean.root,
                        test_path=test_path,
                        visible_workspace_paths=visible_paths,
                        timeout_seconds=self.public_test_timeout_seconds,
                    )
                    if result.succeeded:
                        continue
                    code = (
                        "candidate_workspace_public_test_timeout"
                        if result.failure_class == "public_test_timeout"
                        else _public_test_diagnostic(result).code
                    )
                    raise CandidateWorkspaceError(
                        "a declared public test failed in the framework Candidate workspace",
                        safe_diagnostic=CandidateWorkspaceDiagnostic(code, 1),
                    )
        except CandidateWorkspaceError:
            raise
        except CandidateBuildError as exc:
            raise _classify_clean_build_error(exc) from exc
        except (HostExecutionUnavailable, JudgeInfrastructureError) as exc:
            raise CandidatePrecommitInfrastructureError(
                "framework Candidate host-process execution is unavailable"
            ) from exc
