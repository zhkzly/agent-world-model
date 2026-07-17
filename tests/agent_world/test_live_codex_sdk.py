from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import load_foundry_config
from agent_world.contracts import PermissionScope
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
