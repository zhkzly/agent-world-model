import pytest


@pytest.fixture(autouse=True)
def isolate_agent_world_backend_env(monkeypatch):
    """Keep deterministic tests independent from a developer's live agent shell."""
    for name in [
        "AGENT_WORLD_OPENAI_BASE_URL",
        "AGENT_WORLD_OPENAI_API_KEY",
        "AGENT_WORLD_OPENAI_MODEL",
        "AGENT_WORLD_SMOKE_OPENAI_MODEL",
        "AGENT_WORLD_OPENAI_API_VERSION",
        "AGENT_WORLD_CODE_AGENT_CMD",
        "AGENT_WORLD_CODEX_CMD",
        "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST",
        "AGENT_WORLD_CODEX_ALLOWLIST",
        "AGENT_WORLD_PROCESS_AGENT_CWD",
        "AGENT_WORLD_AGENT_NETWORK",
        "AGENT_WORLD_AGENT_TIMEOUT_MS",
        "AGENT_WORLD_AGENT_MAX_TOKENS",
        "AGENT_WORLD_AGENT_MAX_ATTEMPTS",
        "AGENT_WORLD_LIVE_CODEGEN_SMOKE",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENT_WORLD_AGENT_BACKEND", "mock")
