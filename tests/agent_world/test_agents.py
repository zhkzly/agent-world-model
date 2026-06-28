import json
import sys
from pathlib import Path

from agent_world.agents import AgentBackendRegistry, AgentRequest, MockAgentBackend, default_agent_backend_registry, invoke_agent, load_agent_backend_config_from_env


def test_agent_backend_config_uses_env_refs_without_secret_values(monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_AGENT_BACKEND", "llm")
    monkeypatch.setenv("AGENT_WORLD_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "secret-value-must-not-be-written")
    monkeypatch.setenv("AGENT_WORLD_OPENAI_MODEL", "configured-model")
    monkeypatch.setenv("AGENT_WORLD_SMOKE_OPENAI_MODEL", "cheap-smoke-model")

    config = load_agent_backend_config_from_env()
    encoded = json.dumps(config)

    assert config["backend_kind"] == "llm"
    assert config["auth"]["api_key_env"] == "AGENT_WORLD_OPENAI_API_KEY"
    assert "secret-value-must-not-be-written" not in encoded
    assert config["model"] == "configured-model"
    assert config["smoke_model"] == "cheap-smoke-model"


def test_empty_env_mapping_does_not_read_ambient_env(monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_AGENT_BACKEND", "llm")
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "ambient-secret")
    config = load_agent_backend_config_from_env({})

    assert config["backend_kind"] == "mock"
    assert config["auth"]["api_key_env"] == ""


def test_llm_config_infers_v1_api_version_from_base_url():
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "llm",
            "AGENT_WORLD_OPENAI_BASE_URL": "https://api.example.test/v1",
        }
    )

    assert config["api_version"] == "v1"


def test_llm_backend_requires_network_permission(monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "secret")
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "llm",
            "AGENT_WORLD_OPENAI_API_KEY": "secret",
            "AGENT_WORLD_OPENAI_MODEL": "model",
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="live", input_artifact_ids=["need"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "network_permission_denied"
    assert record["status"] == "fail"


def test_process_agent_backend_records_invocation(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "echo_agent.py"
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "process_agent",
            "AGENT_WORLD_CODEX_CMD": f"{sys.executable} {helper}",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="S1",
        node_purpose="search",
        instruction="discover sources",
        input_artifact_ids=["need-1"],
    )

    record, result = invoke_agent(registry, request, config)

    assert result.status == "pass"
    assert result.text == "echo:S1:search"
    assert record["backend_kind"] == "process_agent"
    assert record["config_ref"] == config["id"]
    assert record["status"] == "pass"
    assert record["usage"]["duration_ms"] is not None
    assert config["permissions"]["filesystem"] == "controlled_process_cwd"
    assert config["permissions"]["sandbox"] is False
    assert config["permissions"]["auth"] is False


def test_process_agent_rejects_shell_control_arguments():
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "process_agent",
            "AGENT_WORLD_CODEX_CMD": f"{sys.executable} -c 'print(1); print(2)'",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="discover sources", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "invalid_process_agent_config"
    assert record["status"] == "fail"


def test_process_agent_scrubs_secret_env(monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "secret-value")
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "env_probe_agent.py"
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "process_agent",
            "AGENT_WORLD_CODEX_CMD": f"{sys.executable} {helper}",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
            "AGENT_WORLD_OPENAI_API_KEY": "secret-value",
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe env", input_artifact_ids=["need-1"])

    _, result = invoke_agent(registry, request, config)

    assert json.loads(result.text)["has_secret"] is False


def test_invocation_record_redacts_secret_values(monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "secret-value")
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "mock",
            "AGENT_WORLD_OPENAI_API_KEY": "secret-value",
        }
    )
    registry = AgentBackendRegistry()
    registry.register(MockAgentBackend({"S1:search": "result contains secret-value"}))
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.text == "result contains secret-value"
    assert "secret-value" not in json.dumps(record)
    assert "[REDACTED_SECRET]" in record["result_preview"]


def test_codex_cli_backend_rejects_unsafe_approval_flags():
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "codex_cli",
            "AGENT_WORLD_CODEX_CMD": "codex --approval-mode=never",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": "codex",
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "invalid_codex_cli_config"
    assert record["status"] == "fail"


def test_codex_cli_backend_requires_safe_approval_and_sandbox():
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "codex_cli",
            "AGENT_WORLD_CODEX_CMD": "codex exec",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": "codex",
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    _, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert "safe approval" in result.text


def test_codex_cli_backend_rejects_config_override():
    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "codex_cli",
            "AGENT_WORLD_CODEX_CMD": "codex exec --approval-mode=on-request --sandbox=workspace-write -c approval_policy=never",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": "codex",
        }
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    _, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert "overrides" in result.text


def test_codex_cli_runner_gets_isolated_codex_home_and_api_key(tmp_path, monkeypatch):
    codex_probe = tmp_path / "codex-probe"
    codex_probe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "json.loads(sys.stdin.read() or '{}')\n"
        "out = pathlib.Path(os.environ['AGENT_WORLD_CODE_AGENT_OUTPUT_DIR'])\n"
        "codex_home = pathlib.Path(os.environ['CODEX_HOME'])\n"
        "probe = {\n"
        "  'has_codex_api_key': bool(os.environ.get('CODEX_API_KEY')),\n"
        "  'codex_home_inside_workspace': str(codex_home).startswith(os.environ['AGENT_WORLD_CODE_AGENT_WORKSPACE']),\n"
        "  'config_text': (codex_home / 'config.toml').read_text(encoding='utf-8'),\n"
        "}\n"
        "(out / 'probe-env.json').write_text(json.dumps(probe, sort_keys=True), encoding='utf-8')\n",
        encoding="utf-8",
    )
    codex_probe.chmod(0o755)
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "secret-value")

    config = load_agent_backend_config_from_env(
        {
            "AGENT_WORLD_AGENT_BACKEND": "codex_cli_runner",
            "AGENT_WORLD_CODEX_CMD": f"{codex_probe} --ask-for-approval on-request --sandbox workspace-write exec --json --skip-git-repo-check -",
            "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": str(codex_probe),
            "AGENT_WORLD_OPENAI_BASE_URL": "https://router.example.test/v1",
            "AGENT_WORLD_OPENAI_API_KEY": "secret-value",
            "AGENT_WORLD_OPENAI_MODEL": "configured-model",
            "AGENT_WORLD_SMOKE_OPENAI_MODEL": "smoke-model",
            "AGENT_WORLD_AGENT_NETWORK": "1",
        }
    )
    registry = default_agent_backend_registry()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction="probe codex runner env",
        input_artifact_ids=["impl"],
        permissions={"network": True, "filesystem": "isolated_agent_workspace", "filesystem_root": str(workspace), "auth": True, "sandbox": True},
    )

    _, result = invoke_agent(registry, request, config)
    probe = json.loads((workspace / "agent-output" / "probe-env.json").read_text(encoding="utf-8"))

    assert result.status == "fail"
    assert result.failure_class == "missing_runner_manifest"
    assert probe["has_codex_api_key"] is True
    assert probe["codex_home_inside_workspace"] is True
    assert "openai_base_url" in probe["config_text"]
    assert "router.example.test" in probe["config_text"]
    assert 'model = "smoke-model"' in probe["config_text"]
    assert "secret-value" not in probe["config_text"]
