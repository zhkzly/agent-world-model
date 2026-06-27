# AGENTS.md

## Project Intent

This repository should evolve into an Agent-World-like environment generation system.

The user wants a loop-engineering style framework that can take an environment need, capability gap, domain seed, tool ecosystem, PRD, repo, MCP server, CLI, API docs, SDK docs, or other source material, then generate reproducible executable environments with tasks, tools, verifiers, release metadata, and training/evaluation consumer outputs.

AWM is background knowledge and a possible source of examples. It is not the target architecture, not the required data format, and not the system boundary.

The current task source is:

- `docs/agent-world-environment-generation.zh.md`

The next hardcoded full-chain Goal is:

- `docs/goal-02-hardcoded-full-chain.zh.md`

Keep `docs/loop-engineering.md` and `research/notes/` as background references only.

## Current Priority

The first vertical slice is implemented under `agent_world/`.

Maintain and extend that slice without drifting from the task source:

- artifact contracts and validators
- deterministic S0-S11 workflow
- gate and review records
- backend-neutral agent invocation records and backend config
- source discovery and knowledge extraction through explicit agent nodes when needed
- support-desk-lite fixture, Python callable surface, deterministic verifier, replay, and release package
- existing `awm` CLI compatibility

Next, when explicitly working on Goal 02, extend only the hardcoded `support-desk-lite` chain from release package into rollout/eval records, deterministic reward records, training export records, and a dataset-only trainer consumer. This is still not generic environment generation.

## Core Principles

- Build an Agent-World-style environment generator, not an AWM reproduction.
- Do not assume there are exactly two loops. Prefer a deterministic staged workflow with explicit feedback edges where useful.
- Treat MCP, CLI, Python callable, HTTP, local services, databases, repos, PRDs, docs, and AWM samples as possible sources or surfaces.
- Keep logical tools separate from concrete surfaces.
- Prefer deterministic verifiers: state checks, file checks, database checks, commands, tests, and API checks.
- LLM/agent nodes may search, extract, synthesize, draft, judge, or implement, but only as explicit workflow nodes with inputs, outputs, budgets, logs, gates, and backend-neutral invocation records.
- Agent backend config belongs to the new framework contract. Prefer `AGENT_WORLD_AGENT_BACKEND`, `AGENT_WORLD_OPENAI_BASE_URL`, `AGENT_WORLD_OPENAI_API_KEY`, `AGENT_WORLD_OPENAI_MODEL`, `AGENT_WORLD_SMOKE_OPENAI_MODEL`, `AGENT_WORLD_OPENAI_API_VERSION`, and `AGENT_WORLD_CODEX_CMD`; treat old AWM LLM variables only as legacy fallbacks.
- If Goal mode, CI, or local smoke tests need a real model, prefer cheap configured models such as `gpt-5.4-mini` or `gpt-3-codex-spark`. Do not hardcode these names in core code; read them from config/env and skip live smoke tests when credentials, network, base URL, or model access are unavailable.
- Stable state belongs in artifacts, manifests, typed config, databases, or trace records, not prompt-only memory.
- Training frameworks such as verl, LLaMA-Factory, OpenRLHF, and TRL are consumers, not core dependencies.

## What Not To Do Now

- Do not create or continue an `awmx` demo.
- Do not implement scripted rollout, reward export, or training loops as the first step.
- Do not bind the design to AWM JSONL or AWM MCP.
- Do not make every environment MCP-only.
- Do not treat a generic CLI command executor as the environment CLI surface.
- Do not bind Codex SDK, mini-swe-agent, deep-search, or any single agent runner directly into the core. If a workflow node needs one of them, use a pluggable agent backend adapter with explicit invocation records.
- Do not download the full AWM 1K dataset into the repository.
- Do not introduce unrelated runtime code outside the frozen first-slice contracts.

## Work Rules

When changing this repo:

1. Read `docs/agent-world-environment-generation.zh.md` first.
2. Use AWM material only as background or source evidence.
3. Remove or rewrite documents that conflict with the current task source.
4. Keep new implementation scoped to the frozen first-slice contracts unless the user explicitly asks to expand the scope.
5. Use `uv` for Python commands.
6. Preserve existing `awm` CLI behavior unless explicitly asked otherwise.
