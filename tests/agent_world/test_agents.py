import json
import os
import types
import sys
from pathlib import Path
import textwrap

import agent_world.agents as agents_module
from agent_world.agents import (
    AgentBackendRegistry,
    AgentRequest,
    MockAgentBackend,
    default_agent_backend_registry,
    invoke_agent,
    load_agent_backend_config_from_env,
    load_implementation_agent_backend_config_from_env,
)
from agent_world.config import load_agent_world_config


def _config_env(tmp_path, *, semantic: str, implementation: str = "", stages: str = "", research: str = "") -> dict[str, str]:
    text = "agent_profiles:\n  semantic:\n"
    text += textwrap.indent(textwrap.dedent(semantic).strip() + "\n", "    ")
    text += "  implementation:\n"
    implementation_text = "inherits: semantic\n" + textwrap.dedent(implementation).strip()
    text += textwrap.indent(implementation_text.strip() + "\n", "    ")
    if stages:
        text += "stages:\n" + textwrap.indent(textwrap.dedent(stages).strip() + "\n", "  ")
    if research:
        text += "research:\n" + textwrap.indent(textwrap.dedent(research).strip() + "\n", "  ")
    config_path = tmp_path / "agent-world.yaml"
    config_path.write_text(text, encoding="utf-8")
    return {"AGENT_WORLD_CONFIG": str(config_path)}


def test_agent_backend_config_uses_env_refs_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value-must-not-be-written")

    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: llm
            base_url: https://api.example.test/v1
            api_key_env: OPENAI_API_KEY
            model: configured-model
            smoke_model: cheap-smoke-model
            """,
        )
    )
    encoded = json.dumps(config)

    assert config["backend_kind"] == "llm"
    assert config["auth"]["api_key_env"] == "OPENAI_API_KEY"
    assert "secret-value-must-not-be-written" not in encoded
    assert config["model"] == "configured-model"
    assert config["smoke_model"] == "cheap-smoke-model"


def test_empty_env_mapping_uses_project_agent_defaults_without_secret_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret")
    world_config = load_agent_world_config({})
    config = load_agent_backend_config_from_env({})

    assert config["backend_kind"] == "llm"
    assert world_config.config_path.endswith("config/agent-world.default.yaml")
    assert config["base_url"] == "https://blog.r78xoaxrk.nyat.app:50903/v1"
    assert config["model"] == "gpt-5.4-mini"
    assert config["smoke_model"] == "gpt-5.4-mini"
    assert config["model_candidates"] == ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"]
    assert config["permissions"]["network"] is True
    assert config["budgets"]["max_tokens"] == 4096
    assert config["timeouts"]["run_ms"] == 60000
    assert config["auth"]["api_key_env"] == "OPENAI_API_KEY"
    assert world_config.research.backend == "jina"
    assert world_config.research.jina_api_key_env == "JINA_API_KEY"


def test_agent_world_config_resolves_semantic_and_implementation_profiles_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "semantic-secret")
    config = load_agent_world_config(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: llm
            api_key_env: OPENAI_API_KEY
            """,
            implementation="""
            backend_kind: codex_sdk
            model: implementation-model
            code_repair_thread_mode: continue
            """,
        )
    )
    encoded = json.dumps(config.to_redacted_dict(), sort_keys=True)

    assert config.stage_agent_profiles["PLAN"] == "semantic"
    assert config.stage_agent_profiles["IMPLEMENT"] == "implementation"
    assert config.agent_profiles["semantic"].backend_kind == "llm"
    assert config.agent_profiles["semantic"].api_key_env == "OPENAI_API_KEY"
    assert config.agent_profiles["implementation"].backend_kind == "codex_sdk"
    assert config.agent_profiles["implementation"].model == "implementation-model"
    assert config.agent_profiles["implementation"].api_key_env == "OPENAI_API_KEY"
    assert config.agent_profiles["implementation"].code_repair_thread_mode == "continue"
    assert "semantic-secret" not in encoded


def test_implementation_backend_config_uses_yaml_profile_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "implementation-secret")
    config = load_implementation_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: llm
            api_key_env: OPENAI_API_KEY
            model: semantic-model
            """,
            implementation="""
            backend_kind: codex_sdk
            base_url: https://impl.example/v1
            model: implementation-model
            code_repair_thread_mode: continue
            """,
        )
    )
    encoded = json.dumps(config, sort_keys=True)

    assert config["id"] == "agent-backend-config-implementation"
    assert config["profile_id"] == "implementation"
    assert config["backend_id"] == "implementation-agent-backend"
    assert config["backend_kind"] == "codex_sdk"
    assert config["model"] == "implementation-model"
    assert config["base_url"] == "https://impl.example/v1"
    assert config["auth"]["api_key_env"] == "OPENAI_API_KEY"
    assert config["code_repair"]["thread_mode"] == "continue"
    assert "implementation-secret" not in encoded


def test_implementation_command_comes_from_yaml_profile(tmp_path):
    config = load_implementation_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="backend_kind: llm",
            implementation="""
            backend_kind: code_agent_runner
            command_value: implementation-runner
            allowlist_value: implementation-runner
            """,
        )
    )

    assert config["command"]["argv"] == ["implementation-runner"]
    assert config["command"]["allowlist_executables"] == ["implementation-runner"]


def test_agent_world_config_file_can_bind_stage_profiles(tmp_path):
    config_path = tmp_path / "agent-world.yaml"
    config_path.write_text(
        """
agent_profiles:
  semantic:
    backend_kind: llm
    model: semantic-file-model
  implementation:
    inherits: semantic
    backend_kind: llm_file_codegen
    model: implementation-file-model
stages:
  default_agent_profile: semantic
  agent_profiles:
    S1: semantic
    IMPLEMENT: implementation
research:
  backend: jina
  max_results: 4
""",
        encoding="utf-8",
    )

    config = load_agent_world_config({"AGENT_WORLD_CONFIG": str(config_path)})

    assert config.config_path == str(config_path)
    assert config.agent_profiles["semantic"].model == "semantic-file-model"
    assert config.agent_profiles["implementation"].backend_kind == "llm_file_codegen"
    assert config.agent_profiles["implementation"].model == "implementation-file-model"
    assert config.stage_agent_profiles["IMPLEMENT"] == "implementation"
    assert config.research.backend == "jina"
    assert config.research.max_results == 4


def test_agent_world_config_file_default_stage_profile_is_not_overwritten(tmp_path):
    config_path = tmp_path / "agent-world.yaml"
    config_path.write_text(
        """
agent_profiles:
  semantic:
    backend_kind: llm
  implementation:
    backend_kind: codex_sdk
  reviewer:
    inherits: semantic
    model: reviewer-model
stages:
  default_agent_profile: reviewer
  agent_profiles:
    IMPLEMENT: implementation
""",
        encoding="utf-8",
    )

    config = load_agent_world_config({"AGENT_WORLD_CONFIG": str(config_path)})

    assert config.stage_agent_profiles["PLAN"] == "reviewer"
    assert config.stage_agent_profiles["S1"] == "reviewer"
    assert config.stage_agent_profiles["IMPLEMENT"] == "implementation"


def test_llm_config_infers_v1_api_version_from_base_url(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: llm
            base_url: https://api.example.test/v1
            """,
        )
    )

    assert config["api_version"] == "v1"


def test_llm_backend_requires_network_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: llm
            api_key_env: OPENAI_API_KEY
            model: model
            network: false
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="live", input_artifact_ids=["need"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "network_permission_denied"
    assert record["status"] == "fail"


def test_llm_file_codegen_requests_json_object_response_format(tmp_path, monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def read(self):
            content = json.dumps(
                {
                    "files": [
                        {
                            "path": "generated/contract.json",
                            "content": json.dumps({"environment_id": "env-test"}),
                        }
                    ],
                    "evidence_refs": ["test://codegen"],
                }
            )
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(agents_module.urllib.request, "urlopen", fake_urlopen)
    config = load_implementation_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: llm
            api_key_env: OPENAI_API_KEY
            """,
            implementation="""
            backend_kind: llm_file_codegen
            model: codegen-model
            network: true
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction="write generated bundle",
        input_artifact_ids=["impl-1"],
        permissions={"network": True, "filesystem": "isolated_workdir", "filesystem_root": str(tmp_path.resolve()), "auth": True, "sandbox": False},
    )

    _, result = invoke_agent(registry, request, config)

    assert result.status == "pass"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    manifest = json.loads(result.text)
    assert manifest["candidate_dir"] == "generated"
    assert manifest["contract_ref"] == "contract.json"


def test_process_agent_backend_records_invocation(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "echo_agent.py"
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic=f"""
            backend_kind: process_agent
            command_value: {sys.executable} {helper}
            allowlist_value: {sys.executable}
            """,
        )
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


def test_process_agent_rejects_shell_control_arguments(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic=f"""
            backend_kind: process_agent
            command_value: {sys.executable} -c 'print(1); print(2)'
            allowlist_value: {sys.executable}
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="discover sources", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "invalid_process_agent_config"
    assert record["status"] == "fail"


def test_process_agent_scrubs_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "env_probe_agent.py"
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic=f"""
            backend_kind: process_agent
            api_key_env: OPENAI_API_KEY
            command_value: {sys.executable} {helper}
            allowlist_value: {sys.executable}
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe env", input_artifact_ids=["need-1"])

    _, result = invoke_agent(registry, request, config)

    assert json.loads(result.text)["has_secret"] is False


def test_invocation_record_redacts_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: mock
            api_key_env: OPENAI_API_KEY
            """,
        )
    )
    registry = AgentBackendRegistry()
    registry.register(MockAgentBackend({"S1:search": "result contains secret-value"}))
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.text == "result contains secret-value"
    assert "secret-value" not in json.dumps(record)
    assert "[REDACTED_SECRET]" in record["result_preview"]


def test_codex_cli_backend_rejects_unsafe_approval_flags(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_cli
            command_value: codex --approval-mode=never
            allowlist_value: codex
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "invalid_codex_cli_config"
    assert record["status"] == "fail"


def test_codex_cli_backend_requires_safe_approval_and_sandbox(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_cli
            command_value: codex exec
            allowlist_value: codex
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="probe", input_artifact_ids=["need-1"])

    _, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert "safe approval" in result.text


def test_codex_cli_backend_rejects_config_override(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_cli
            command_value: codex exec --approval-mode=on-request --sandbox=workspace-write -c approval_policy=never
            allowlist_value: codex
            """,
        )
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
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")

    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic=f"""
            backend_kind: codex_cli_runner
            base_url: https://router.example.test/v1
            api_key_env: OPENAI_API_KEY
            model: configured-model
            smoke_model: smoke-model
            network: true
            command_value: {codex_probe} --ask-for-approval on-request --sandbox workspace-write exec --json --skip-git-repo-check -
            allowlist_value: {codex_probe}
            """,
        )
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


def test_codex_sdk_config_declares_codex_provider_and_workspace_sandbox(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            network: true
            """,
        )
    )

    assert config["backend_kind"] == "codex_sdk"
    assert config["provider"] == "codex"
    assert config["command"]["argv"] == []
    assert config["permissions"]["filesystem"] == "isolated_agent_workspace"
    assert config["permissions"]["network"] is True
    assert config["permissions"]["sandbox"] is True
    assert config["auth"]["requires_auth"] is True
    assert config["code_repair"]["thread_mode"] == "stateless"


def test_codex_sdk_config_accepts_implementation_repair_continuation(tmp_path):
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            code_repair_thread_mode: continue
            """,
        )
    )

    assert config["code_repair"]["thread_mode"] == "continue"


def test_codex_sdk_backend_invokes_official_python_sdk(tmp_path, monkeypatch):
    calls = {}

    class FakeSandbox:
        read_only = "read-only"
        workspace_write = "workspace-write"
        full_access = "full-access"

    class FakeThread:
        def run(self, instruction, **kwargs):
            calls["instruction"] = instruction
            calls["run_kwargs"] = kwargs
            calls["codex_home"] = os.environ.get("CODEX_HOME")
            return types.SimpleNamespace(final_response="codex final", usage=types.SimpleNamespace(total_tokens=9))

    class FakeCodex:
        def __enter__(self):
            calls["entered"] = True
            return self

        def __exit__(self, exc_type, exc, tb):
            calls["exited"] = True

        def thread_start(self, **kwargs):
            calls["thread_start"] = kwargs
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=FakeCodex, Sandbox=FakeSandbox))
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            network: true
            codex_sandbox: workspace-write
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="S1",
        node_purpose="search",
        instruction="discover sources",
        input_artifact_ids=["need-1"],
        permissions={"network": True, "filesystem": "artifact_context", "filesystem_root": str(tmp_path), "auth": False, "sandbox": True},
    )

    record, result = invoke_agent(registry, request, config)
    config_text = (tmp_path / "agent-output" / "codex-home" / "config.toml").read_text(encoding="utf-8")

    assert result.status == "pass"
    assert result.text == "codex final"
    assert result.evidence_refs == ["codex-sdk://thread"]
    assert result.trace_ref == "codex-sdk://thread"
    assert result.usage["tokens"] == {"total_tokens": 9}
    assert result.usage["duration_ms"] is not None
    assert record["backend_kind"] == "codex_sdk"
    assert record["model_or_runtime"] == "gpt-test"
    assert calls["entered"] is True
    assert calls["exited"] is True
    assert calls["thread_start"] == {
        "model": "gpt-test",
        "sandbox": FakeSandbox.workspace_write,
        "cwd": str(tmp_path.resolve()),
        "model_provider": "agent_world_openai",
    }
    assert calls["instruction"] == "discover sources"
    assert calls["run_kwargs"] == {"sandbox": FakeSandbox.workspace_write, "cwd": str(tmp_path.resolve())}
    assert calls["codex_home"] == str((tmp_path / "agent-output" / "codex-home").resolve())
    assert 'model = "gpt-test"' in config_text


def test_codex_sdk_implementation_can_continue_same_thread(tmp_path, monkeypatch):
    calls = {"thread_start": 0, "instructions": []}

    class FakeSandbox:
        read_only = "read-only"
        workspace_write = "workspace-write"
        full_access = "full-access"

    class FakeThread:
        id = "thread-1"

        def run(self, instruction, **kwargs):
            calls["instructions"].append(instruction)
            output_dir = Path("agent-output")
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "candidate_manifest.json").write_text(
                json.dumps({"generated_files": []}, sort_keys=True),
                encoding="utf-8",
            )
            return types.SimpleNamespace(final_response="done")

    class FakeCodex:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def thread_start(self, **kwargs):
            calls["thread_start"] += 1
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=FakeCodex, Sandbox=FakeSandbox))
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            code_repair_thread_mode: continue
            """,
        )
    )
    registry = default_agent_backend_registry()
    first = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction="initial implementation",
        input_artifact_ids=["impl-1"],
        invocation_id="invoke-implement-attempt-1",
        permissions={"network": False, "filesystem": "isolated_agent_workspace", "filesystem_root": str(tmp_path), "auth": False, "sandbox": True},
        continuation_mode="continue",
    )

    first_record, first_result = invoke_agent(registry, first, config)
    second = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction="repair from framework failure packet",
        input_artifact_ids=["impl-1", "failure-packet-1"],
        invocation_id="invoke-implement-attempt-2",
        permissions={"network": False, "filesystem": "isolated_agent_workspace", "filesystem_root": str(tmp_path), "auth": False, "sandbox": True},
        parent_invocation_id=first_record["id"],
        conversation_ref=first_record["conversation_ref"],
        continuation_mode="continue",
    )
    second_record, second_result = invoke_agent(registry, second, config)

    assert first_result.status == "pass"
    assert second_result.status == "pass"
    assert calls["thread_start"] == 1
    assert calls["instructions"] == ["initial implementation", "repair from framework failure packet"]
    assert first_record["conversation_ref"] == "thread-1"
    assert second_record["conversation_ref"] == "thread-1"
    assert second_record["parent_invocation_id"] == first_record["id"]
    assert second_record["continuation_mode"] == "continue"


def test_codex_sdk_backend_writes_isolated_provider_config(tmp_path, monkeypatch):
    calls = {}

    class FakeSandbox:
        read_only = "read-only"
        workspace_write = "workspace-write"
        full_access = "full-access"

    class FakeThread:
        def run(self, instruction, **kwargs):
            calls["codex_home"] = os.environ.get("CODEX_HOME")
            calls["api_key_visible"] = os.environ.get("OPENAI_API_KEY")
            return types.SimpleNamespace(final_response="codex final")

    class FakeCodex:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def thread_start(self, **kwargs):
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=FakeCodex, Sandbox=FakeSandbox))
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            base_url: https://router.example.test/v1
            api_key_env: OPENAI_API_KEY
            model: configured-model
            smoke_model: smoke-model
            network: true
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="S1",
        node_purpose="search",
        instruction="discover sources",
        input_artifact_ids=["need-1"],
        permissions={"network": True, "filesystem": "artifact_context", "filesystem_root": str(tmp_path), "auth": True, "sandbox": True},
    )

    record, result = invoke_agent(registry, request, config)
    config_text = (tmp_path / "agent-output" / "codex-home" / "config.toml").read_text(encoding="utf-8")

    assert result.status == "pass"
    assert record["backend_kind"] == "codex_sdk"
    assert calls["codex_home"] == str((tmp_path / "agent-output" / "codex-home").resolve())
    assert calls["api_key_visible"] == "secret-value"
    assert 'model = "smoke-model"' in config_text
    assert 'model_provider = "agent_world_openai"' in config_text
    assert 'base_url = "https://router.example.test/v1"' in config_text
    assert 'env_key = "OPENAI_API_KEY"' in config_text
    assert "secret-value" not in config_text


def test_codex_sdk_backend_configures_temp_home_without_workspace(tmp_path, monkeypatch):
    calls = {}

    class FakeSandbox:
        read_only = "read-only"
        workspace_write = "workspace-write"
        full_access = "full-access"

    class FakeThread:
        def run(self, instruction, **kwargs):
            codex_home = Path(os.environ["CODEX_HOME"])
            calls["codex_home"] = codex_home
            calls["api_key_visible"] = os.environ.get("OPENAI_API_KEY")
            calls["config_text"] = (codex_home / "config.toml").read_text(encoding="utf-8")
            calls["run_kwargs"] = kwargs
            return types.SimpleNamespace(final_response="codex final")

    class FakeCodex:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def thread_start(self, **kwargs):
            calls["thread_start"] = kwargs
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=FakeCodex, Sandbox=FakeSandbox))
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            base_url: https://router.example.test/v1
            api_key_env: OPENAI_API_KEY
            model: configured-model
            network: true
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="S1",
        node_purpose="search",
        instruction="discover sources",
        input_artifact_ids=["need-1"],
        permissions={"network": True, "filesystem": "artifact_context", "auth": True, "sandbox": True},
    )

    record, result = invoke_agent(registry, request, config)

    assert result.status == "pass"
    assert record["backend_kind"] == "codex_sdk"
    assert calls["api_key_visible"] == "secret-value"
    assert calls["thread_start"] == {
        "model": "configured-model",
        "sandbox": FakeSandbox.workspace_write,
        "model_provider": "agent_world_openai",
    }
    assert calls["run_kwargs"] == {"sandbox": FakeSandbox.workspace_write}
    assert 'base_url = "https://router.example.test/v1"' in calls["config_text"]
    assert 'env_key = "OPENAI_API_KEY"' in calls["config_text"]
    assert "secret-value" not in calls["config_text"]
    assert not calls["codex_home"].exists()


def test_codex_sdk_backend_missing_sdk_needs_human(tmp_path, monkeypatch):
    import importlib

    real_import_module = importlib.import_module

    def stub_import_module(name, package=None):
        if name == "openai_codex":
            raise ModuleNotFoundError("No module named openai_codex")
        return real_import_module(name, package)

    monkeypatch.delitem(sys.modules, "openai_codex", raising=False)
    monkeypatch.setattr(importlib, "import_module", stub_import_module)
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(stage="S1", node_purpose="search", instruction="discover sources", input_artifact_ids=["need-1"])

    record, result = invoke_agent(registry, request, config)

    assert result.status == "needs_human"
    assert result.failure_class == "missing_codex_sdk"
    assert "openai-codex" in result.recovery_suggestion
    assert record["status"] == "needs_human"


def test_codex_sdk_implementation_returns_candidate_manifest_ref(tmp_path, monkeypatch):
    calls = {}

    class FakeSandbox:
        read_only = "read-only"
        workspace_write = "workspace-write"
        full_access = "full-access"

    class FakeThread:
        def run(self, instruction, **kwargs):
            calls["cwd"] = Path.cwd()
            output_dir = Path("agent-output")
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "candidate_manifest.json").write_text(
                json.dumps({"generated_files": []}, sort_keys=True),
                encoding="utf-8",
            )
            return types.SimpleNamespace(final_response="done")

    class FakeCodex:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def thread_start(self, **kwargs):
            calls["thread_start"] = kwargs
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=FakeCodex, Sandbox=FakeSandbox))
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction="write generated bundle",
        input_artifact_ids=["impl-1"],
        permissions={"network": False, "filesystem": "isolated_agent_workspace", "filesystem_root": str(tmp_path), "auth": False, "sandbox": True},
    )

    _, result = invoke_agent(registry, request, config)

    assert result.status == "pass"
    assert json.loads(result.text) == {"candidate_manifest_ref": "agent-output/candidate_manifest.json"}
    assert "agent-workspace://agent-output/candidate_manifest.json" in result.evidence_refs
    assert calls["cwd"] == tmp_path.resolve()


def test_codex_sdk_implementation_requires_candidate_manifest(tmp_path, monkeypatch):
    class FakeSandbox:
        read_only = "read-only"
        workspace_write = "workspace-write"
        full_access = "full-access"

    class FakeThread:
        def run(self, instruction, **kwargs):
            return types.SimpleNamespace(final_response="done without manifest")

    class FakeCodex:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def thread_start(self, **kwargs):
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=FakeCodex, Sandbox=FakeSandbox))
    config = load_agent_backend_config_from_env(
        _config_env(
            tmp_path,
            semantic="""
            backend_kind: codex_sdk
            model: gpt-test
            """,
        )
    )
    registry = default_agent_backend_registry()
    request = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction="write generated bundle",
        input_artifact_ids=["impl-1"],
        permissions={"network": False, "filesystem": "isolated_agent_workspace", "filesystem_root": str(tmp_path), "auth": False, "sandbox": True},
    )

    _, result = invoke_agent(registry, request, config)

    assert result.status == "fail"
    assert result.failure_class == "missing_runner_manifest"
    assert result.trace_ref == "agent-workspace://agent-output/codex-sdk-result.json"
