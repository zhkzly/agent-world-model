"""Preflight the real dependencies and direct-host execution boundaries of a Foundry run."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_world.agent_profiles import AgentProfileProvider
from agent_world.config import FoundryConfig
from agent_world.contracts import PermissionScope
from agent_world.control import TelemetryStore
from agent_world.invocation import (
    CodexSdkBackend,
    InvocationControlPlane,
    InvocationControlStore,
    InvocationOwnerKind,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    NodeCapabilityRequirement,
)
from agent_world.invocation.codex_runtime import CodexRuntimeUnavailable, resolve_codex_runtime
from agent_world.invocation.contracts import JsonObject
from agent_world.invocation.structured_diagnostics import safe_terminal_details
from agent_world.judge import (
    CandidateProcessRunner,
    CleanCandidateBuilder,
    HostExecutionPolicy,
)
from agent_world.research import SearchQuery, build_research_toolchain

_CLEAN_BUILD_PYTHON_REQUIRES = ">=3.12,<3.13"
_CLEAN_BUILD_PROBE_SOURCE = "\n".join(
    (
        "[project]",
        'name = "agent-world-doctor-clean-build-probe"',
        'version = "0.0.0"',
        f'requires-python = "{_CLEAN_BUILD_PYTHON_REQUIRES}"',
        "dependencies = []",
        "",
    )
)
_RUNTIME_PYTHON_PROBE = (
    "import json,sys;"
    "print(json.dumps({'major':sys.version_info.major,'minor':sys.version_info.minor},"
    "sort_keys=True,separators=(',',':')))"
)
_LIVE_AGENT_STATUS_FILENAME = "doctor-live-agent.json"
_LIVE_AGENT_DEBUG_FILENAME = "doctor-live-agent-debug.json"
# The probe's tool-dispatch evidence.  A fixed name and content keep the check
# deterministic and make the file recognizable as framework-owned, so a leftover
# marker can never be mistaken for Agent-authored candidate material.
_LIVE_AGENT_PROBE_FILENAME = "agent-world-live-agent-probe.txt"
_LIVE_AGENT_PROBE_CONTENT = "agent-world-live-agent-probe-ok"
_LOCAL_EXECUTION_CHECKS = frozenset(
    {
        "state_root",
        "executable_uv",
        "standalone_python",
        "codex_sdk",
        "codex_runtime",
        "judge_host_execution",
        "clean_build",
        "profile_materialization",
    }
)


class DoctorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check: str
    status: Literal["pass", "fail", "skipped"]
    summary: str


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_level: Literal["configured", "live-agent", "live-research", "production"]
    ok: bool
    local_execution_ready: bool
    configuration_ready: bool
    live_agent_verified: bool
    live_research_verified: bool
    production_ready: bool
    checks: tuple[DoctorCheck, ...]


def _local_execution_ready(checks: Iterable[DoctorCheck]) -> bool:
    """Require every named direct-host prerequisite, not a stale subset."""

    observed = {check.check: check.status for check in checks}
    return all(observed.get(name) == "pass" for name in _LOCAL_EXECUTION_CHECKS)


async def run_doctor(
    config: FoundryConfig,
    *,
    live_agent: bool = False,
    live_research: bool = False,
) -> DoctorReport:
    checks: list[DoctorCheck] = []

    try:
        config.state_root.mkdir(  # noqa: ASYNC240 - one bounded preflight operation
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        if config.state_root.is_symlink() or not config.state_root.is_dir():
            raise OSError("state_root must be a real directory")
        checks.append(DoctorCheck(check="state_root", status="pass", summary="state root ready"))
    except OSError as exc:
        checks.append(DoctorCheck(check="state_root", status="fail", summary=str(exc)))

    checks.append(_authentication_check(config))
    checks.append(_model_catalog_check(config))
    uv_executable = shutil.which("uv")
    checks.append(_executable_check("uv", uv_executable))
    checks.append(_standalone_python_check(uv_executable))

    try:
        version = importlib.metadata.version("openai-codex")
        checks.append(
            DoctorCheck(
                check="codex_sdk",
                status="pass",
                summary=f"openai-codex {version} importable",
            )
        )
    except importlib.metadata.PackageNotFoundError:
        checks.append(
            DoctorCheck(
                check="codex_sdk",
                status="fail",
                summary="openai-codex is not installed in the uv environment",
            )
        )

    checks.append(await _codex_runtime_check(config))

    try:
        await HostExecutionPolicy(purpose="runtime").ensure_available()
        await HostExecutionPolicy(purpose="build").ensure_available()
        checks.append(
            DoctorCheck(
                check="judge_host_execution",
                status="pass",
                summary="runtime and configured clean-build host-process probes passed",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck(check="judge_host_execution", status="fail", summary=str(exc)))

    checks.append(await _clean_build_readiness_check(config))

    try:
        provider = AgentProfileProvider(config.agent)
        with tempfile.TemporaryDirectory(
            prefix="doctor-profile-",
            dir=config.state_root,
        ) as temporary:
            profile = provider.resolve(
                role="researcher",
                lineage_id="doctor.profile",
                workspace=Path(temporary) / "logical",
                output_schema={"type": "object", "additionalProperties": False},
                permissions=PermissionScope(),
                requirement=NodeCapabilityRequirement.structured_read(
                    node_id="researcher.doctor",
                    role="researcher",
                ),
            )
            if profile.authentication_kind != "api_key":
                raise ValueError("profile authentication kind is invalid")
        checks.append(
            DoctorCheck(
                check="profile_materialization",
                status="pass",
                summary="private Researcher profile state materialized and removed",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck(check="profile_materialization", status="fail", summary=str(exc)))

    live_agent_check: DoctorCheck
    if live_agent:
        live_agent_check = await _live_agent_check(config)
    else:
        live_agent_check = DoctorCheck(
            check="live_agent",
            status="skipped",
            summary="enable explicitly to spend one real Codex model turn",
        )
    checks.append(live_agent_check)

    research_credential = _research_credential_check(config)
    checks.append(research_credential)
    if live_research and research_credential.status == "pass":
        try:
            toolchain = build_research_toolchain(config.research)
            credential_handles = (
                (config.research.jina_credential_handle,)
                if config.research.jina_api_key_environment is not None
                else ()
            )
            permissions = PermissionScope(credential_handles=credential_handles)
            bundle = await toolchain.run(
                (SearchQuery("programmatic agent environment state transition tools"),),
                request_permissions=permissions,
                run_permissions=permissions,
                allowed_source_kinds=("web",),
                # A readiness probe must distinguish a broken research stack
                # from ordinary Web-source attrition.  Search results routinely
                # include paywalls, bot challenges, and transient failures, so
                # reserve several independent fetch attempts while keeping the
                # probe small and explicitly metered.
                maximum_tool_calls=6,
                results_per_query=5,
                max_documents=5,
                require_evidence=False,
            )
            bundle.require_evidence()
            checks.append(
                DoctorCheck(
                    check="live_research",
                    status="pass",
                    summary=(
                        f"real search/fetch/extract returned {len(bundle.documents)} document"
                    ),
                )
            )
        except Exception as exc:
            checks.append(DoctorCheck(check="live_research", status="fail", summary=str(exc)))
    else:
        checks.append(
            DoctorCheck(
                check="live_research",
                status="skipped",
                summary="enable explicitly to spend real search/fetch calls",
            )
        )

    local_execution_ready = _local_execution_ready(checks)
    configuration_ready = local_execution_ready and all(
        item.status != "fail"
        for item in checks
        if item.check in {"model_authentication", "research_configuration", "model_catalog"}
    )
    live_agent_verified = live_agent_check.status == "pass"
    live_research_check = next(item for item in checks if item.check == "live_research")
    live_research_verified = live_research_check.status == "pass"
    production_ready = configuration_ready and live_agent_verified and live_research_verified
    requested_level: Literal["configured", "live-agent", "live-research", "production"]
    if live_agent and live_research:
        requested_level = "production"
    elif live_agent:
        requested_level = "live-agent"
    elif live_research:
        requested_level = "live-research"
    else:
        requested_level = "configured"
    requested_checks_pass = configuration_ready and (
        (not live_agent or live_agent_verified) and (not live_research or live_research_verified)
    )
    return DoctorReport(
        requested_level=requested_level,
        ok=requested_checks_pass,
        local_execution_ready=local_execution_ready,
        configuration_ready=configuration_ready,
        live_agent_verified=live_agent_verified,
        live_research_verified=live_research_verified,
        production_ready=production_ready,
        checks=tuple(checks),
    )


async def _live_agent_check(config: FoundryConfig) -> DoctorCheck:
    """Spend one observable real Agent turn without persisting private content.

    ``doctor --live-agent`` is a provider control, not a miniature node test.
    It deliberately receives the largest configured real-Agent token envelope;
    a small requested result must not silently create a smaller SDK budget.  A
    compact current-status file and the ordinary telemetry trace make a long
    control observable from a second process while it is still running.

    This probe asks the Agent to USE A TOOL -- write a file in its direct host
    workspace -- and then verifies that file on disk.  A prompt-only round trip
    ("return this object, do not call tools") proves the transport and nothing
    else: worker spawn, app-server startup, direct SDK tool dispatch can
    all be broken while it still passes.  Those are exactly the layers that fail
    in practice, so the control has to cross them.  The structured answer alone is
    not sufficient evidence: only the observed workspace file proves a tool ran.

    The probe deliberately exercises one framework-owned primitive rather than
    surveying the runtime's tool catalogue.  Which tools a Codex runtime offers is
    its own business, and a readiness check that asserted a specific catalogue
    would fail whenever that catalogue legitimately changed.
    """

    trace_id = f"doctor-live-agent:{uuid.uuid4().hex}"
    invocation_id = f"doctor-live-agent-round-trip:{uuid.uuid4().hex}"
    started_at = datetime.now(UTC).isoformat()
    rollout_token_limit = _live_agent_probe_rollout_token_limit(config)
    terminal_status: Literal["running", "passed", "failed", "interrupted"] = "running"
    failure_code: str | None = None
    terminal_details: JsonObject = {}
    debug_feedback_path: Path | None = None
    telemetry: TelemetryStore | None = None
    try:
        _write_live_agent_status(
            config,
            trace_id=trace_id,
            started_at=started_at,
            status=terminal_status,
            rollout_token_limit=rollout_token_limit,
            failure_code=None,
            terminal_details=terminal_details,
            debug_feedback_path=None,
        )
        telemetry = TelemetryStore(config.state_root / "telemetry")
        control_store = InvocationControlStore(config.state_root / "invocation-control")
        # A doctor probe has no Work head to reconcile, but it must still not
        # leave a prior crashed physical turn looking live in the shared
        # invocation view.  This scan only writes a terminal owner-loss fact;
        # it never performs a provider retry.
        control_store.reconcile_owner_loss()
        backend = InvocationControlPlane(
            CodexSdkBackend(telemetry=telemetry),
            control_store,
            require_explicit_ownership=True,
        )
        with tempfile.TemporaryDirectory(
            prefix="doctor-live-agent-",
            dir=config.state_root,
        ) as temporary:
            provider = AgentProfileProvider(config.agent)
            # The Engineer role is the one with workspace-write authority, so it
            # is the only role that can prove tool dispatch end to end.  Probing
            # a read-only role would leave the write path -- the one CandidateBuild
            # depends on -- untested.
            profile = provider.resolve(
                role="environment-engineer",
                lineage_id="doctor.live-agent",
                workspace=Path(temporary) / "logical",
                output_schema={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["ok"]},
                        "wrote_file": {"type": "boolean"},
                    },
                    "required": ["status", "wrote_file"],
                    "additionalProperties": False,
                },
                permissions=_live_agent_probe_permissions(config),
                requirement=NodeCapabilityRequirement.host_build(
                    node_id="engineer.doctor-live-agent",
                ),
                rollout_token_limit=rollout_token_limit,
            )
            probe_marker = profile.workspace / _LIVE_AGENT_PROBE_FILENAME
            result = await backend.invoke(
                InvocationRequest(
                    invocation_id=invocation_id,
                    prompt=(
                        "This is a production Agent readiness probe. Use your real "
                        "tools; do not simulate their results. Follow the mounted "
                        "`engineer-agent-world` Skill only for its supplied "
                        "workspace/tool method; this is not a CandidateBuild.\n"
                        f"1. Write a file named {_LIVE_AGENT_PROBE_FILENAME} in your "
                        "current working directory. Its content must be exactly the "
                        f"single line {_LIVE_AGENT_PROBE_CONTENT}\n"
                        '2. Return the structured object with status "ok" and '
                        "wrote_file set to whether the write actually succeeded. "
                        "Report false if it failed; do not claim success you did "
                        "not achieve."
                    ),
                    profile=profile,
                    metadata={
                        "trace_id": trace_id,
                        "run_id": trace_id,
                        "role": "environment-engineer",
                        "semantic_transaction": "doctor_live_agent_probe",
                        "diagnostic_capture_terminal_excerpt": True,
                    },
                    ownership=InvocationOwnership(
                        owner_kind=InvocationOwnerKind.DIAGNOSTIC_AUDIT,
                        owner_id=invocation_id,
                        scope_id=trace_id,
                        coordinate="doctor:live_agent",
                    ),
                )
            )
            # Observed while the Agent workspace still exists.  The Agent's own
            # booleans are a self-report; this is the framework's independent
            # evidence that a tool really ran, so the two are recorded separately.
            tool_evidence = _live_agent_tool_evidence(result, probe_marker)
        failure_code = _live_agent_failure_code(result)
        if failure_code is not None:
            terminal_status = "failed"
            terminal_details = safe_terminal_details(result.error)
            excerpt = _live_agent_diagnostic_excerpt(result)
            if excerpt is not None:
                debug_feedback_path = _write_live_agent_debug_feedback(
                    config,
                    trace_id=trace_id,
                    failure_code=failure_code,
                    excerpt=excerpt,
                )
            return DoctorCheck(
                check="live_agent",
                status="fail",
                summary=f"real Codex SDK turn failed ({failure_code})",
            )
        if not tool_evidence.workspace_write_observed:
            terminal_status = "failed"
            failure_code = "agent_workspace_write_not_observed"
            terminal_details = dict(tool_evidence.to_public_dict())
            return DoctorCheck(
                check="live_agent",
                status="fail",
                summary=(
                    "the Codex turn completed but its workspace write was not "
                    "observed on disk; tool dispatch or the Agent workspace setup is broken "
                    "even though the transport works"
                ),
            )
        terminal_status = "passed"
        terminal_details = dict(tool_evidence.to_public_dict())
        return DoctorCheck(
            check="live_agent",
            status="pass",
            summary="real Codex Agent turn dispatched a tool and wrote its workspace file",
        )
    except asyncio.CancelledError:
        terminal_status = "interrupted"
        failure_code = "interrupted"
        raise
    except Exception as exc:
        terminal_status = "failed"
        failure_code = "doctor_exception"
        return DoctorCheck(
            check="live_agent",
            status="fail",
            summary=f"real Codex SDK turn failed ({type(exc).__name__})",
        )
    finally:
        if telemetry is not None:
            telemetry.close()
        _write_live_agent_status(
            config,
            trace_id=trace_id,
            started_at=started_at,
            status=terminal_status,
            rollout_token_limit=rollout_token_limit,
            failure_code=failure_code,
            terminal_details=terminal_details,
            debug_feedback_path=debug_feedback_path,
        )


def _write_live_agent_status(
    config: FoundryConfig,
    *,
    trace_id: str,
    started_at: str,
    status: Literal["running", "passed", "failed", "interrupted"],
    rollout_token_limit: int,
    failure_code: str | None,
    terminal_details: JsonObject,
    debug_feedback_path: Path | None,
) -> None:
    """Publish only durable, credential-free liveness facts for one Doctor turn."""

    payload: dict[str, object] = {
        "diagnostic_only": True,
        "kind": "doctor_live_agent",
        "rollout_token_limit": rollout_token_limit,
        "started_at": started_at,
        "status": status,
        "telemetry_root": str(config.state_root / "telemetry"),
        "trace_id": trace_id,
        "updated_at": datetime.now(UTC).isoformat(),
        "wall_timeout_seconds": config.agent.structured_invocation_timeout_seconds,
    }
    if failure_code is not None:
        payload["failure_code"] = failure_code
    if terminal_details:
        payload["terminal_details"] = terminal_details
    if debug_feedback_path is not None:
        payload["debug_feedback_path"] = str(debug_feedback_path)
    _write_live_agent_json(config.state_root / _LIVE_AGENT_STATUS_FILENAME, payload)


def _live_agent_diagnostic_excerpt(result: InvocationResult) -> str | None:
    """Read an explicitly opted-in, worker-redacted local Doctor excerpt."""

    if result.error is None:
        return None
    excerpt = result.error.details.get("diagnostic_error_excerpt")
    if not isinstance(excerpt, str) or not excerpt or len(excerpt) > 512:
        return None
    return excerpt


def _write_live_agent_debug_feedback(
    config: FoundryConfig,
    *,
    trace_id: str,
    failure_code: str,
    excerpt: str,
) -> Path:
    """Write an on-demand local Code-Agent debug sidecar, never runtime feedback."""

    target = config.state_root / _LIVE_AGENT_DEBUG_FILENAME
    _write_live_agent_json(
        target,
        {
            "diagnostic_only": True,
            "failure_code": failure_code,
            "kind": "doctor_live_agent_debug",
            "terminal_error_excerpt": excerpt,
            "trace_id": trace_id,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    return target


def _write_live_agent_json(target: Path, payload: dict[str, object]) -> None:
    """Atomically write a private, local Doctor view below one safe state root."""

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise OSError("Doctor live-Agent state root must be a real directory")
    if target.exists() and target.is_symlink():
        raise OSError("Doctor live-Agent status path cannot be a symlink")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _live_agent_probe_rollout_token_limit(config: FoundryConfig) -> int:
    """Use the configured real-Agent envelope for a live provider control.

    A readiness probe has a tiny requested output, but its SDK turn still
    materializes the actual Codex profile and may consume non-cached context
    before it can emit the small structured response.  It must not introduce
    an unrelated 16K cutoff that contradicts a deliberately enlarged
    diagnostic envelope.  Selecting the larger configured structured/codegen
    limit keeps this control capable of proving the route used by either real
    Agent lane; actual usage remains metered by InvocationBackend.
    """

    return max(
        config.agent.structured_turn_token_limit,
        config.agent.environment_codegen_turn_token_limit,
    )


def _live_agent_probe_permissions(config: FoundryConfig) -> PermissionScope:
    """Grant the probe the same job-level ceiling a real Agent node receives.

    A probe under a narrower grant than production would pass while the real
    thing is denied, which is the failure this control exists to catch.
    """

    return PermissionScope(
        network_domains=tuple(
            sorted(
                {
                    *config.agent.engineer_network_domain_ceiling,
                    *config.agent.engineer_dependency_network_domains,
                    *config.agent.research_network_domain_ceiling,
                }
            )
        ),
    )


class _LiveAgentToolEvidence(BaseModel):
    """Framework-observed tool evidence, kept apart from the Agent's self-report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_write_observed: bool
    workspace_content_matched: bool
    workspace_write_self_reported: bool

    def to_public_dict(self) -> JsonObject:
        return {
            "workspace_write_observed": self.workspace_write_observed,
            "workspace_content_matched": self.workspace_content_matched,
            "workspace_write_self_reported": self.workspace_write_self_reported,
        }


def _live_agent_tool_evidence(
    result: InvocationResult,
    probe_marker: Path,
) -> _LiveAgentToolEvidence:
    """Observe the workspace directly instead of trusting the structured answer.

    ``workspace_write_observed`` is the only load-bearing field: a model can
    report ``wrote_file: true`` without a tool ever running, so the file on disk
    is what proves worker spawn and tool dispatch both work. The
    self-report is retained beside it because a disagreement between the two is
    itself the useful diagnostic -- a real run reported false while the file was
    present, which told us more than either fact alone.
    """

    observed = False
    matched = False
    try:
        if probe_marker.is_file():
            observed = True
            matched = probe_marker.read_text(encoding="utf-8", errors="replace").strip() == (
                _LIVE_AGENT_PROBE_CONTENT
            )
    except OSError:
        observed = False
    output = result.structured_output if isinstance(result.structured_output, dict) else {}
    return _LiveAgentToolEvidence(
        workspace_write_observed=observed,
        workspace_content_matched=matched,
        workspace_write_self_reported=output.get("wrote_file") is True,
    )


def _live_agent_failure_code(result: InvocationResult) -> str | None:
    """Classify a live probe result without disclosing provider diagnostics."""

    if result.status is not InvocationStatus.COMPLETED:
        return result.error.code if result.error is not None else result.status.value
    output = result.structured_output
    if not isinstance(output, dict) or output.get("status") != "ok":
        return "structured_output_mismatch"
    if result.session is None:
        return "missing_session"
    if result.backend_version is None:
        return "missing_backend_version"
    return None


def _authentication_check(config: FoundryConfig) -> DoctorCheck:
    agent = config.agent
    value = os.environ.get(agent.api_key_environment)
    # Match application assembly: Redactor.from_values protects exact
    # credential values from four bytes onward, including short opaque
    # tokens issued by OpenAI-compatible gateways.
    if not value or len(value.encode("utf-8")) < 4:
        return DoctorCheck(
            check="model_authentication",
            status="fail",
            summary="configured API credential environment is absent",
        )
    if agent.openai_base_url_environment is not None and not os.environ.get(
        agent.openai_base_url_environment
    ):
        return DoctorCheck(
            check="model_authentication",
            status="fail",
            summary="configured API base-URL environment is absent",
        )
    return DoctorCheck(
        check="model_authentication",
        status="pass",
        summary="configured API credential and routing handles are available",
    )


def _model_catalog_check(config: FoundryConfig) -> DoctorCheck:
    """Fail fast when a configured model name is absent from the gateway catalogue.

    Some OpenAI-compatible gateways collapse an *unknown model name* into a
    generic ``5xx``/``internal_server_error`` terminal indistinguishable from a
    transient capacity blip.  Recovery then treats it as ``TRANSIENT_CAPACITY``
    and spends the whole retry+fallback budget before reporting a misleading
    "provider unavailable".  A configured model name is deterministic control
    state, so validate it against the gateway's ``/models`` catalogue once at
    preflight and turn it into a plain configuration error.

    This probe spends no model tokens.  It is tolerant of gateways that do not
    implement ``/models`` (or transiently fail it): those are reported as
    ``skipped`` so a healthy deployment behind a minimal gateway still passes.
    Only a catalogue that is present AND is missing a configured name fails.
    """

    agent = config.agent
    base_url_environment = agent.openai_base_url_environment
    if base_url_environment is None:
        return DoctorCheck(
            check="model_catalog",
            status="skipped",
            summary="no OpenAI-compatible base URL configured; model catalogue not applicable",
        )
    base_url = os.environ.get(base_url_environment)
    api_key = os.environ.get(agent.api_key_environment)
    if not base_url or not api_key:
        return DoctorCheck(
            check="model_catalog",
            status="skipped",
            summary="base URL or credential environment absent; catalogue probe skipped",
        )

    catalogue = _fetch_model_catalogue(base_url, api_key)
    if catalogue is None:
        return DoctorCheck(
            check="model_catalog",
            status="skipped",
            summary="gateway did not expose a usable /models catalogue; probe skipped",
        )

    required = (agent.model, *agent.fallback_models)
    missing = tuple(name for name in required if name not in catalogue)
    if missing:
        # Never echo the raw catalogue (it can name unrelated deployments); only
        # report the configured names the deployment itself already owns.
        return DoctorCheck(
            check="model_catalog",
            status="fail",
            summary=(
                "configured model name(s) absent from the gateway catalogue: "
                + ", ".join(missing)
                + " -- fix the configured model/fallback_models rather than retrying"
            ),
        )
    return DoctorCheck(
        check="model_catalog",
        status="pass",
        summary=f"all {len(required)} configured model name(s) present in the gateway catalogue",
    )


def _fetch_model_catalogue(base_url: str, api_key: str) -> frozenset[str] | None:
    """Return the gateway's advertised model ids, or ``None`` when unavailable.

    The credential is sent only to the exact configured base URL over the
    standard bearer header; the response is parsed for ``data[].id`` and nothing
    is persisted.  Any transport, status, or shape problem yields ``None`` so
    the caller degrades to ``skipped`` rather than failing a healthy gateway.
    """

    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(  # noqa: S310 - fixed https gateway control probe
        url,
        method="GET",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            if getattr(response, "status", 200) != 200:
                return None
            body = response.read(1_000_000)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    entries = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(entries, list):
        return None
    ids = {
        entry["id"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    return frozenset(ids) if ids else None


def _research_credential_check(config: FoundryConfig) -> DoctorCheck:
    name = config.research.jina_api_key_environment
    if config.research.provider == "jina" and (name is None or not os.environ.get(name)):
        return DoctorCheck(
            check="research_configuration",
            status="fail",
            summary="Jina Search credential handle is unavailable",
        )
    return DoctorCheck(
        check="research_configuration",
        status="pass",
        summary=f"real {config.research.provider} search provider configured",
    )


def _executable_check(name: str, executable: str | None) -> DoctorCheck:
    return DoctorCheck(
        check=f"executable_{name}",
        status="pass" if executable else "fail",
        summary=f"{name} executable available" if executable else f"{name} executable missing",
    )


def _standalone_python_check(uv_executable: str | None) -> DoctorCheck:
    """Confirm uv can locate a relocatable standalone Python 3.12 offline.

    Candidate builds no longer copy the framework interpreter; the
    profile resolver asks uv for a relocatable standalone distribution whose
    stdlib stays valid when referenced in place.  If no such distribution is
    installed, ``uv venv`` inside a workspace fails, so surface the gap here
    rather than deep inside a build node.
    """

    if uv_executable is None:
        return DoctorCheck(
            check="standalone_python",
            status="fail",
            summary="uv is unavailable to locate a standalone Python 3.12",
        )
    try:
        # Resolve exactly as a candidate build does: from a neutral working
        # directory (so uv does not discover this framework's own project
        # ``.venv``, whose interpreter is a symlink without a co-located
        # stdlib) and requiring a uv-managed standalone distribution. Probing
        # from the framework cwd would resolve the local venv and report a
        # false negative even when a valid standalone is installed.
        with tempfile.TemporaryDirectory() as neutral_cwd:
            found = subprocess.run(  # noqa: S603 -- host uv, fixed args, discovery only.
                [uv_executable, "python", "find", "--managed-python", "3.12"],
                check=True,
                capture_output=True,
                text=True,
                cwd=neutral_cwd,
                env={
                    "PATH": "/usr/bin:/bin",
                    "UV_PYTHON_DOWNLOADS": "never",
                    "UV_NO_PROGRESS": "1",
                    "UV_NO_PROJECT": "1",
                },
            )
    except (OSError, subprocess.CalledProcessError):
        return DoctorCheck(
            check="standalone_python",
            status="fail",
            summary="no relocatable standalone Python 3.12 is installed for uv "
            "(install one with: uv python install 3.12)",
        )
    interpreter = Path(found.stdout.strip())
    root = interpreter.parent.parent
    if not (root / "lib" / "python3.12" / "encodings" / "__init__.py").is_file():
        return DoctorCheck(
            check="standalone_python",
            status="fail",
            summary="uv resolved a Python 3.12 without a co-located stdlib "
            "(install a standalone build with: uv python install 3.12)",
        )
    return DoctorCheck(
        check="standalone_python",
        status="pass",
        summary="relocatable standalone Python 3.12 available to uv",
    )


async def _codex_runtime_check(config: FoundryConfig) -> DoctorCheck:
    try:
        runtime = resolve_codex_runtime(config.agent.codex_bin)
    except CodexRuntimeUnavailable as exc:
        return DoctorCheck(
            check="codex_runtime",
            status="fail",
            summary=f"SDK-bundled Codex runtime unavailable: {exc}",
        )
    binary = runtime.path
    runtime_source = "explicit" if runtime.source == "configured" else "SDK-bundled"
    try:
        if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise OSError("configured Codex runtime is not a real executable file")
        with tempfile.TemporaryDirectory(
            prefix="doctor-codex-runtime-",
            dir=config.state_root,
        ) as temporary:
            runtime_environment = {
                name: value
                for name in ("PATH", "LANG", "LC_ALL", "TERM", "WSLENV")
                if (value := os.environ.get(name)) is not None
            }
            runtime_environment.update(
                {
                    "HOME": temporary,
                    "CODEX_HOME": temporary,
                }
            )
            version_process = await asyncio.create_subprocess_exec(
                str(binary),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=runtime_environment,
            )
            stdout, _stderr = await asyncio.wait_for(
                version_process.communicate(),
                timeout=15,
            )
            version = stdout.decode("utf-8", errors="replace").strip()
            if version_process.returncode != 0 or not version.startswith("codex-cli "):
                raise OSError("configured executable did not report a Codex CLI version")

            capability_process = await asyncio.create_subprocess_exec(
                str(binary),
                "-c",
                "features.rollout_budget.enabled=true",
                "-c",
                "features.rollout_budget.limit_tokens=2",
                "-c",
                "features.rollout_budget.reminder_at_remaining_tokens=[1]",
                "-c",
                "features.rollout_budget.sampling_token_weight=1.0",
                "-c",
                "features.rollout_budget.prefill_token_weight=1.0",
                "features",
                "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=runtime_environment,
            )
            capability_stdout, _capability_stderr = await asyncio.wait_for(
                capability_process.communicate(),
                timeout=15,
            )
            capability_text = capability_stdout.decode("utf-8", errors="replace")
            if capability_process.returncode != 0 or "rollout_budget" not in capability_text:
                raise OSError(
                    "configured Codex runtime does not support the required rollout-budget schema"
                )
        return DoctorCheck(
            check="codex_runtime",
            status="pass",
            summary=(f"{runtime_source} {version} executable and rollout-budget schema ready"),
        )
    except (OSError, TimeoutError) as exc:
        return DoctorCheck(check="codex_runtime", status="fail", summary=str(exc))


async def _clean_build_readiness_check(config: FoundryConfig) -> DoctorCheck:
    """Exercise the exact production clean-build and direct-host runtime path."""

    judge = config.judge
    cache = judge.uv_cache_dir
    if cache is None:
        return DoctorCheck(
            check="clean_build",
            status="fail",
            summary=(
                "offline clean builds require an explicit judge.uv_cache_dir; "
                "Doctor will not treat an empty ephemeral cache as production-ready"
            ),
        )
    try:
        _validate_configured_uv_cache(cache)
    except OSError as exc:
        return DoctorCheck(check="clean_build", status="fail", summary=str(exc))

    uv_text = shutil.which("uv")
    if uv_text is None:
        return DoctorCheck(
            check="clean_build",
            status="fail",
            summary="real uv executable is unavailable for the clean-build probe",
        )

    try:
        uv_path = Path(uv_text).resolve(  # noqa: ASYNC240 - bounded preflight lookup
            strict=True
        )
        if not uv_path.is_file() or not os.access(uv_path, os.X_OK):
            raise OSError("resolved uv path is not an executable file")
        with tempfile.TemporaryDirectory(
            prefix="doctor-clean-build-",
            dir=config.state_root,
        ) as temporary:
            probe_root = Path(temporary)
            source = probe_root / "source"
            source.mkdir(mode=0o700)
            (source / "pyproject.toml").write_text(
                _CLEAN_BUILD_PROBE_SOURCE,
                encoding="utf-8",
            )

            lock_cache = probe_root / "lock-uv-cache"
            lock_cache.mkdir(mode=0o700)
            await _create_probe_lock(
                source=source,
                uv_path=uv_path,
                cache=lock_cache,
                timeout_seconds=judge.clean_build_timeout_seconds,
            )

            builder = CleanCandidateBuilder(
                build_execution=HostExecutionPolicy(purpose="build"),
                uv_path=uv_path,
                uv_cache_dir=cache,
                timeout_seconds=judge.clean_build_timeout_seconds,
            )
            async with builder.materialize(source) as candidate:
                if candidate.install.network_policy != "disabled":
                    raise RuntimeError(
                        "clean build used a network policy different from Judge configuration"
                    )
                runtime_result = await CandidateProcessRunner(
                    execution=HostExecutionPolicy(purpose="runtime"),
                    timeout_seconds=min(judge.clean_build_timeout_seconds, 30.0),
                    max_output_bytes=16 * 1024,
                ).run(
                    candidate.root,
                    argv=(".venv/bin/python", "-I", "-c", _RUNTIME_PYTHON_PROBE),
                    visible_workspace_paths=(),
                    failure_prefix="doctor_runtime_python",
                )
                if not runtime_result.succeeded:
                    raise RuntimeError(
                        "installed interpreter failed in host execution "
                        f"({runtime_result.failure_class or runtime_result.exit_code})"
                    )
                try:
                    version = json.loads(runtime_result.stdout)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "runtime Python probe did not return its exact version"
                    ) from exc
                if version != {"major": 3, "minor": 12}:
                    raise RuntimeError(
                        "runtime host execution did not use the required Python 3.12 interpreter"
                    )

        return DoctorCheck(
            check="clean_build",
            status="pass",
            summary=(
                "real uv lock + frozen clean sync + runtime host execution passed on exact "
                "Python 3.12 (offline/no-network with the configured read-only uv cache)"
            ),
        )
    except Exception as exc:
        return DoctorCheck(
            check="clean_build",
            status="fail",
            summary=f"{type(exc).__name__}: {exc}",
        )


def _validate_configured_uv_cache(cache: Path) -> None:
    if cache.is_symlink() or not cache.is_dir():
        raise OSError("configured offline judge.uv_cache_dir is not a real directory")
    if not os.access(cache, os.R_OK | os.X_OK):
        raise OSError("configured offline judge.uv_cache_dir is not readable/searchable")
    try:
        with os.scandir(cache) as entries:
            next(entries, None)
    except OSError as exc:
        raise OSError("configured offline judge.uv_cache_dir cannot be opened") from exc


async def _create_probe_lock(
    *,
    source: Path,
    uv_path: Path,
    cache: Path,
    timeout_seconds: float,
) -> None:
    argv = [
        str(uv_path),
        "lock",
        "--python",
        sys.executable,
        "--offline",
    ]
    home = source.parent / "lock-home"
    home.mkdir(mode=0o700)
    environment = {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": str(source.parent),
        "UV_CACHE_DIR": str(cache),
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=source,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("real uv lock probe timed out") from exc
    if process.returncode != 0:
        diagnostic = (stderr or stdout)[:16_384].decode("utf-8", errors="replace").strip()
        raise RuntimeError("real uv lock probe failed" + (f": {diagnostic}" if diagnostic else ""))
    if not (source / "uv.lock").is_file():
        raise RuntimeError("real uv lock probe returned success without creating uv.lock")


__all__ = ["DoctorCheck", "DoctorReport", "run_doctor"]
