# AGENTS.md

## Project Intent

This repository should evolve from the original AWM environment generator into a maintainable Agent World framework.

The target system is not just environment synthesis. It should cover:

- scenario and task generation
- executable environment construction
- environment and task checks
- environment release and registry
- agent rollout and trajectory sampling
- verifier-driven reward extraction
- feedback that can guide training, harness changes, and future task generation

## Core Principles

- Prefer code-first workflows. LLMs may draft plans or workflow specs, but stable execution must be represented as checked code, typed config, or explicit DAGs.
- Treat MCP, CLI, Python functions, HTTP APIs, and external agents as adapters over the same abstract tool/environment interface.
- Use verifiers over judge-only scoring whenever possible. Prefer database state checks, file checks, command exit codes, unit tests, and deterministic scripts.
- Make every run observable. Persist inputs, configs, prompts, commands, tool calls, observations, verifier outputs, rewards, and failure reasons.
- Make every run replayable. A trajectory should include enough artifact pointers to rerun or audit the episode.
- Keep generation, checking, rollout, verification, training export, and release as separate stages with explicit artifacts between them.
- Do not make the training loop depend on a single agent implementation. Codex SDK, mini-swe-agent, deep search agents, CLI tools, and MCP agents should be swappable runners.
- Do not put a full agent implementation inside `harness/`. Keep `harness/` as a thin control seam for context, permissions, trace, gates, review, and replay. Reuse existing AWM environment management, MCP surfaces, and verifier logic whenever they fit. Put mini-swe-agent, Codex SDK, deep-search, scripted execution, and AWM/MCP interaction behind adapter/rollout runner interfaces only when a workflow node actually needs that backend.
- Avoid prompt-only state. Long-running state belongs in files, databases, manifests, or trace records.
- Start narrow and executable before scaling. One reliable environment family with strong checks is more valuable than many weak generated environments.

## Architecture Bias

Use this layer split when adding new code:

1. `world`: scenarios, tasks, environment specs, state backends, tool surfaces.
2. `adapters`: CLI, MCP, Python, HTTP, Codex SDK, mini-swe-agent, search agents.
3. `workflow`: explicit DAG or staged pipeline definitions.
4. `harness`: permissions, sandboxing, context assembly, logging, replay, failure attribution.
5. `rollout`: agent execution, trajectory capture, retries, budgets, termination.
6. `verification`: deterministic checks, LLM-assisted judges only where deterministic checks are insufficient.
7. `training`: data export first, online RL integration second.
8. `evolution`: failure analysis, targeted task generation, harness edits, environment expansion.

## Work Loop For Codex

When changing this repo:

1. Inspect existing AWM CLI and artifact formats before adding abstractions.
2. Preserve existing `awm gen`, `awm env`, `awm agent`, and `awm verify` behavior unless the user explicitly asks for a breaking change.
3. Add new framework pieces behind new modules, docs, or commands.
4. Write down artifact contracts before implementing broad orchestration.
5. Use TDD for new behavior: write schema, config, dry-run, trace, verifier, or export tests before implementing the corresponding slice.
6. Prefer small vertical slices: one scenario, one task, one environment, one runner, one verifier, one trace.
7. Verify with the narrowest runnable command available.
8. Use `uv` for Python environment management and command execution. Prefer `uv run ...`, `uv sync`, and `uv add ...`; do not introduce ad-hoc virtualenv or bare `python` commands in docs, tests, or scripts.
9. Do not commit API keys. If a lightweight LLM smoke test is needed, read `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and model names from the environment; prefer `gpt-5.4-mini` or `gpt-5.3-codex` for cheap tests.
10. Use an independent read-only review before considering a slice complete.
11. Keep stable config under `configs/agent_world/` and run artifacts under `outputs/agent_world/`.
12. Every workflow run must write `events.jsonl`; every rollout must write `trace.jsonl`; every verification must write `reward.json`.
13. Before implementing contracts, workflow, rollout, verification, or evolution, reread `docs/loop-engineering.md` and the Agent World notes under `research/notes/`; open the local AWM and Agent-World PDFs when the design depends on paper details.

## Goal Mode Usage

For long tasks, use Codex Goal mode with a short objective that points to the detailed plan:

```text
/goal Implement the first vertical slice described in docs/agent-world-framework-plan.zh.md. Stop when one generated or existing AWM environment can be checked, sampled by one runner, verified, and exported as a trace/reward artifact.
```

If the goal needs more constraints, edit the plan document instead of placing a long prompt directly in the goal.

For the full program, use `docs/agent-world-loop-program.zh.md` and `docs/goals.zh.md` as the source of truth.
