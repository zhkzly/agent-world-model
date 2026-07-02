import pytest


@pytest.fixture(autouse=True)
def isolate_agent_world_backend_env(monkeypatch):
    """Keep local tests independent from a developer's live agent shell."""
    for name in [
        "AGENT_WORLD_CONFIG",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "JINA_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
