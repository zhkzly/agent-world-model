from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import load_foundry_config
from agent_world.contracts import PermissionScope
from agent_world.control import TelemetryStore
from agent_world.invocation import (
    CodexSdkBackend,
    InvocationRequest,
    InvocationStatus,
    NodeCapabilityRequirement,
)


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_codex_sdk_profile_round_trip_is_explicitly_opt_in(tmp_path: Path) -> None:
    if os.environ.get("AGENT_WORLD_RUN_LIVE") != "1":
        pytest.skip("set AGENT_WORLD_RUN_LIVE=1 to spend a real model turn")
    if "AGENT_WORLD_CONFIG" not in os.environ:
        pytest.fail("AGENT_WORLD_RUN_LIVE=1 requires an explicit AGENT_WORLD_CONFIG")

    config = load_foundry_config()
    provider = IsolatedAgentProfileProvider(config.agent)
    logical_workspace = tmp_path / "live-researcher"
    logical_workspace.mkdir()
    profile = provider.resolve(
        role="researcher",
        lineage_id="live-profile-contract",
        workspace=logical_workspace,
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
            "additionalProperties": False,
        },
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_read(
            node_id="researcher.live-contract",
            role="researcher",
        ),
    )
    request = InvocationRequest(
        invocation_id="live-codex-sdk-profile-round-trip",
        prompt=(
            "This is a live InvocationBackend contract check. Do not call tools. "
            'Return the JSON object {"status":"ok"} and no other fields.'
        ),
        profile=profile,
    )

    result = await CodexSdkBackend().invoke(request)

    assert result.status is InvocationStatus.COMPLETED, result.error
    assert result.structured_output == {"status": "ok"}
    assert result.session is not None
    assert result.backend_version is not None


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_codex_sdk_custom_runtime_can_read_isolated_workspace(
    tmp_path: Path,
) -> None:
    if os.environ.get("AGENT_WORLD_RUN_LIVE") != "1":
        pytest.skip("set AGENT_WORLD_RUN_LIVE=1 to spend a real model turn")
    if "AGENT_WORLD_CONFIG" not in os.environ:
        pytest.fail("AGENT_WORLD_RUN_LIVE=1 requires an explicit AGENT_WORLD_CONFIG")

    config = load_foundry_config()
    provider = IsolatedAgentProfileProvider(config.agent)
    logical_workspace = tmp_path / "live-shell-probe"
    logical_workspace.mkdir()
    nonce = os.urandom(12).hex()
    (logical_workspace / "probe.txt").write_text(nonce, encoding="utf-8")
    profile = provider.resolve(
        role="researcher",
        lineage_id="live-shell-profile-contract",
        workspace=logical_workspace,
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["ok"]},
                "observed": {"type": "string"},
            },
            "required": ["status", "observed"],
            "additionalProperties": False,
        },
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_read(
            node_id="researcher.live-shell-contract",
            role="researcher",
        ),
        rollout_token_limit=16_384,
    )
    request = InvocationRequest(
        invocation_id="live-codex-sdk-shell-profile-round-trip",
        prompt=(
            "This is a live isolated-workspace contract check. Use the shell to read probe.txt. "
            "Return status=ok and copy the complete file content into observed."
        ),
        profile=profile,
    )

    result = await CodexSdkBackend().invoke(request)

    assert result.status is InvocationStatus.COMPLETED, result.error
    assert result.structured_output == {"status": "ok", "observed": nonce}
    assert result.session is not None
    assert result.backend_version is not None


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_engineer_write_stays_in_resolved_workspace_and_emits_safe_activity(
    tmp_path: Path,
) -> None:
    """Exercise the real Agentic path, not a mocked filesystem adapter.

    This is intentionally a tiny, bounded Engineer turn.  It proves that the
    same workspace-write profile used by Build receives its real SDK item
    notifications as safe aggregate telemetry and writes below the resolved
    workspace.  It does not claim to prove a complete Environment Candidate.
    """

    if os.environ.get("AGENT_WORLD_RUN_LIVE") != "1":
        pytest.skip("set AGENT_WORLD_RUN_LIVE=1 to spend a real model turn")
    if "AGENT_WORLD_CONFIG" not in os.environ:
        pytest.fail("AGENT_WORLD_RUN_LIVE=1 requires an explicit AGENT_WORLD_CONFIG")

    config = load_foundry_config()
    provider = IsolatedAgentProfileProvider(config.agent)
    logical_workspace = tmp_path / "live-engineer-write"
    logical_workspace.mkdir()
    nonce = os.urandom(12).hex()
    profile = provider.resolve(
        role="environment-engineer",
        lineage_id="live-engineer-workspace-activity",
        workspace=logical_workspace,
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
            "additionalProperties": False,
        },
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.isolated_build(
            node_id="environment-engineer.live-workspace-activity",
        ),
        rollout_token_limit=16_384,
        invocation_timeout_seconds=120,
    )
    trace_id = "run:live-engineer-workspace-activity"
    request = InvocationRequest(
        invocation_id="live-codex-sdk-engineer-workspace-activity",
        prompt=(
            "This is a live isolated Engineer workspace-write contract check. "
            "Use a shell command or workspace editing tool to create exactly "
            "candidate/agent_workspace_probe.txt with this exact content: "
            f"{nonce}. Do not create files outside candidate/. Then return the "
            'JSON object {"status":"ok"} and no other fields.'
        ),
        profile=profile,
        metadata={"run_id": trace_id, "role": "environment-engineer"},
    )
    telemetry = TelemetryStore(tmp_path / "telemetry")
    try:
        result = await CodexSdkBackend(telemetry=telemetry).invoke(request)

        assert result.status is InvocationStatus.COMPLETED, result.error
        assert result.structured_output == {"status": "ok"}
        probe_path = profile.workspace / "candidate" / "agent_workspace_probe.txt"
        assert probe_path.is_relative_to(profile.workspace)
        assert probe_path.read_text(encoding="utf-8") == nonce

        inspected = telemetry.inspect_trace(trace_id)
        metrics = {
            row["name"]: row["value_integer"]
            if row["value_integer"] is not None
            else row["value_real"]
            for row in inspected["metrics"]
        }
        assert metrics["invocation.events.observed_delta"] > 0
        activity_total = sum(
            metrics.get(f"invocation.activity.{activity}_event_delta", 0)
            for activity in (
                "reasoning",
                "agent_message",
                "command",
                "file_change",
                "tool",
                "other",
                "unclassified",
            )
        )
        assert activity_total > 0
        assert (
            metrics.get("invocation.activity.command_event_delta", 0) > 0
            or metrics.get("invocation.activity.file_change_event_delta", 0) > 0
        )
        assert nonce not in json.dumps(inspected, sort_keys=True)
    finally:
        telemetry.close()
