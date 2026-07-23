"""Preflight the real dependencies and isolation boundaries of a Foundry run."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import FoundryConfig
from agent_world.contracts import PermissionScope
from agent_world.invocation import (
    CodexSdkBackend,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    NodeCapabilityRequirement,
)
from agent_world.judge import (
    CandidateSandboxRunner,
    CleanCandidateBuilder,
    IsolationPolicy,
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
    checks.append(_executable_check("uv", shutil.which("uv")))

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
        await IsolationPolicy(purpose="runtime").ensure_available()
        await IsolationPolicy(purpose="build").ensure_available()
        checks.append(
            DoctorCheck(
                check="judge_isolation",
                status="pass",
                summary="runtime and configured clean-build bubblewrap probes passed",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck(check="judge_isolation", status="fail", summary=str(exc)))

    checks.append(await _clean_build_readiness_check(config))

    try:
        provider = IsolatedAgentProfileProvider(config.agent)
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
            if profile.authentication_kind not in {"api_key", "chatgpt"}:
                raise ValueError("profile authentication kind is invalid")
        checks.append(
            DoctorCheck(
                check="profile_isolation",
                status="pass",
                summary="isolated Researcher profile materialized and removed",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck(check="profile_isolation", status="fail", summary=str(exc)))

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

    local_names = {
        "state_root",
        "executable_uv",
        "codex_sdk",
        "codex_runtime",
        "judge_isolation",
        "clean_build",
        "profile_isolation",
    }
    local_execution_ready = all(
        item.status == "pass" for item in checks if item.check in local_names
    )
    configuration_ready = local_execution_ready and all(
        item.status == "pass"
        for item in checks
        if item.check in {"model_authentication", "research_configuration"}
    )
    live_agent_verified = live_agent_check.status == "pass"
    live_research_check = next(item for item in checks if item.check == "live_research")
    live_research_verified = live_research_check.status == "pass"
    production_ready = (
        configuration_ready and live_agent_verified and live_research_verified
    )
    requested_level: Literal[
        "configured", "live-agent", "live-research", "production"
    ]
    if live_agent and live_research:
        requested_level = "production"
    elif live_agent:
        requested_level = "live-agent"
    elif live_research:
        requested_level = "live-research"
    else:
        requested_level = "configured"
    requested_checks_pass = configuration_ready and (
        (not live_agent or live_agent_verified)
        and (not live_research or live_research_verified)
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
    """Spend one real backend turn without persisting prompt, response, or credentials."""

    try:
        with tempfile.TemporaryDirectory(
            prefix="doctor-live-agent-",
            dir=config.state_root,
        ) as temporary:
            provider = IsolatedAgentProfileProvider(config.agent)
            profile = provider.resolve(
                role="researcher",
                lineage_id="doctor.live-agent",
                workspace=Path(temporary) / "logical",
                output_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["ok"]}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
                permissions=PermissionScope(),
                requirement=NodeCapabilityRequirement.structured_read(
                    node_id="researcher.doctor-live-agent",
                    role="researcher",
                ),
                # A real Codex turn carries several thousand non-cached input
                # tokens before this tiny probe prompt is added.  The budget
                # feature accounts both non-cached input and sampled output.
                rollout_token_limit=16_384,
            )
            result = await CodexSdkBackend().invoke(
                InvocationRequest(
                    invocation_id="doctor-live-agent-round-trip",
                    prompt=(
                        "This is a production InvocationBackend readiness probe. "
                        "Do not call tools. Return exactly the structured object "
                        '{"status":"ok"}.'
                    ),
                    profile=profile,
                )
            )
        failure_code = _live_agent_failure_code(result)
        if failure_code is not None:
            return DoctorCheck(
                check="live_agent",
                status="fail",
                summary=f"real Codex SDK turn failed ({failure_code})",
            )
        return DoctorCheck(
            check="live_agent",
            status="pass",
            summary="real Codex SDK structured-output turn completed",
        )
    except Exception as exc:
        return DoctorCheck(
            check="live_agent",
            status="fail",
            summary=f"real Codex SDK turn failed ({type(exc).__name__})",
        )


def _live_agent_failure_code(result: InvocationResult) -> str | None:
    """Classify a live probe result without disclosing provider diagnostics."""

    if result.status is not InvocationStatus.COMPLETED:
        return result.error.code if result.error is not None else result.status.value
    if result.structured_output != {"status": "ok"}:
        return "structured_output_mismatch"
    if result.session is None:
        return "missing_session"
    if result.backend_version is None:
        return "missing_backend_version"
    return None


def _authentication_check(config: FoundryConfig) -> DoctorCheck:
    agent = config.agent
    if agent.api_key_environment is not None:
        value = os.environ.get(agent.api_key_environment)
        # Match application assembly: Redactor.from_values protects exact
        # credential values from four bytes onward, including short opaque
        # tokens issued by OpenAI-compatible gateways.
        if value and len(value.encode("utf-8")) >= 4:
            return DoctorCheck(
                check="model_authentication",
                status="pass",
                summary="configured API credential handle is available",
            )
        return DoctorCheck(
            check="model_authentication",
            status="fail",
            summary="configured API credential environment is absent",
        )
    assert agent.chatgpt_auth_file is not None
    path = agent.chatgpt_auth_file
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("authorized Codex login file is unavailable")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise OSError("authorized Codex login file must not be group/world accessible")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not value:
            raise ValueError("authorized Codex login file is not a non-empty JSON object")
        return DoctorCheck(
            check="model_authentication",
            status="pass",
            summary="explicit Codex login handle is valid",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return DoctorCheck(check="model_authentication", status="fail", summary=str(exc))


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


async def _codex_runtime_check(config: FoundryConfig) -> DoctorCheck:
    binary = config.agent.codex_bin
    runtime_source = "explicit"
    if binary is None:
        try:
            from codex_cli_bin import bundled_codex_path  # type: ignore[import-untyped]

            sdk_version = importlib.metadata.version("openai-codex")
            runtime_version = importlib.metadata.version("openai-codex-cli-bin")
            if sdk_version != runtime_version:
                raise OSError(
                    "SDK-bundled Codex runtime version does not match openai-codex"
                )
            binary = bundled_codex_path()
            runtime_source = "SDK-bundled"
        except (ImportError, importlib.metadata.PackageNotFoundError, OSError) as exc:
            return DoctorCheck(
                check="codex_runtime",
                status="fail",
                summary=f"SDK-bundled Codex runtime unavailable: {exc}",
            )
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
            summary=(
                f"{runtime_source} {version} executable and rollout-budget schema ready"
            ),
        )
    except (OSError, TimeoutError) as exc:
        return DoctorCheck(check="codex_runtime", status="fail", summary=str(exc))


async def _clean_build_readiness_check(config: FoundryConfig) -> DoctorCheck:
    """Exercise the exact production clean-build and runtime isolation path."""

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
                build_isolation=IsolationPolicy(purpose="build"),
                uv_path=uv_path,
                uv_cache_dir=cache,
                timeout_seconds=judge.clean_build_timeout_seconds,
            )
            async with builder.materialize(source) as candidate:
                if candidate.install.network_policy != "disabled":
                    raise RuntimeError(
                        "clean build used a network policy different from Judge configuration"
                    )
                runtime_result = await CandidateSandboxRunner(
                    isolation=IsolationPolicy(purpose="runtime"),
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
                        "installed interpreter failed in runtime isolation "
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
                        "runtime isolation did not execute the required Python 3.12 interpreter"
                    )

        return DoctorCheck(
            check="clean_build",
            status="pass",
            summary=(
                "real uv lock + frozen clean sync + runtime sandbox passed on exact "
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
