# agent_world Backend Guidelines

Read `docs/agent-world-environment-generation.zh.md` first.

Rules:

- Keep success paths artifact-driven.
- Keep Codex/agent invocation behind `AgentBackend`.
- Keep release decisions framework-owned.
- Keep package paths relative and movable.
- Keep live model/network tests opt-in.
- Run `uv run pytest tests/agent_world` before claiming this slice still works.
