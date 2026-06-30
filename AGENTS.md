# AGENTS.md

## Project Intent

This repository should evolve into an Agent-World-like environment generation system.

The user wants a loop-engineering style framework that can take an environment need, capability gap, domain seed, tool ecosystem, PRD, repo, MCP server, CLI, API docs, SDK docs, or other source material, then generate reproducible executable environments with tasks, tools, verifiers, release metadata, and training/evaluation consumer outputs.

AWM is background knowledge and a possible source of examples. It is not the target architecture, not the required data format, and not the system boundary.

The current task source is:

- `docs/agent-world-environment-generation.zh.md`

Keep `docs/loop-engineering.md` and `research/notes/` as background references only.
Use `docs/project-progress-and-corrections.zh.md` as the living progress and drift log; update it when a Goal changes the project's true state or corrects a misunderstanding.

## Current Priority

The active vertical slice is implemented under `agent_world/`.

Maintain and extend that slice without drifting from the task source:

- artifact contracts and validators
- request-driven S0-S11 pipeline structure
- gate and review records
- backend-neutral agent invocation records and backend config
- source discovery and knowledge extraction through explicit artifact-producing nodes
- agent-backed generated environment bundle implementation
- generated self-check plus framework-owned independent verification
- bounded repair records controlled by framework config
- package-relative generated runtime consumer check
- existing `awm` CLI compatibility

The current active path must not rely on registered smoke domains, fixed environment ids, fixed task ids, or environment-id keyed verifier/replay cases. Domain examples may appear as raw request text, but core behavior must be artifact-driven.

## Core Principles

- Build an Agent-World-style environment generator, not an AWM reproduction.
- Do not assume there are exactly two loops. Prefer a deterministic staged workflow with explicit feedback edges where useful.
- Treat MCP, CLI, Python callable, HTTP, local services, databases, repos, PRDs, docs, and AWM samples as possible sources or surfaces.
- Keep logical tools separate from concrete surfaces.
- Distinguish environment CLI surface from runtime control CLI and agent backend CLI. Environment CLI means tools like `lark doc create`, `gh issue create`, `kubectl apply`; runtime control CLI means harness commands like health/reset/step/finalize; agent backend CLI means process adapters such as Codex CLI.
- Prefer deterministic verifiers: state checks, file checks, database checks, commands, tests, and API checks.
- LLM/agent nodes may search, extract, synthesize, draft, judge, or implement, but only as explicit workflow nodes with inputs, outputs, budgets, logs, gates, and backend-neutral invocation records.
- Agent backend config belongs to the new framework contract. Prefer `AGENT_WORLD_AGENT_BACKEND=openai_codegen` for OpenAI-compatible file-content codegen smoke, or `AGENT_WORLD_AGENT_BACKEND=code_agent_runner` / `codex_cli_runner` for real code-agent runner smoke. Use `AGENT_WORLD_CODE_AGENT_CMD`, `AGENT_WORLD_OPENAI_BASE_URL`, `AGENT_WORLD_OPENAI_API_KEY`, `AGENT_WORLD_OPENAI_MODEL`, `AGENT_WORLD_SMOKE_OPENAI_MODEL`, `AGENT_WORLD_OPENAI_API_VERSION`, and `AGENT_WORLD_CODEX_CMD`; treat old AWM LLM variables only as legacy fallbacks.
- If Goal mode, CI, or local smoke tests need a real model, prefer cheap configured models such as `gpt-5.4-mini` or `gpt-3-codex-spark`. Do not hardcode these names in core code; read them from config/env and skip live smoke tests when credentials, network, base URL, or model access are unavailable.
- Stable state belongs in artifacts, manifests, typed config, databases, or trace records, not prompt-only memory.
- Training frameworks such as verl, LLaMA-Factory, OpenRLHF, and TRL are consumers, not core dependencies.

## What Not To Do Now

- Do not create or continue an `awmx` demo.
- Do not implement real trainer loops, GPU training, Ray/vLLM/SGLang workers, or framework-specific training dependencies in core.
- Do not bind the design to AWM JSONL or AWM MCP.
- Do not make every environment MCP-only.
- Do not treat a generic CLI command executor as the environment CLI surface.
- Do not bind Codex SDK, mini-swe-agent, deep-search, or any single agent runner directly into the core. If a workflow node needs one of them, use a pluggable agent backend adapter with explicit invocation records.
- Do not download the full AWM 1K dataset into the repository.
- Do not reintroduce hardcoded fixture registries or domain-specific verifier branches as the normal success path.
- Do not mark generated environment release as verified unless framework-owned build/check/replay loaded or launched the generated files themselves.
- Do not mark agent-backed implementation as complete unless the candidate bundle is written in an isolated workdir and passes manifest/path/hash/security checks, generated self-check, and independent verifier.
- Do not let generated `check_replay.py` stdout decide release by itself.
- Do not write credentials, base URLs with secrets, API keys, or auth tokens into artifacts or traces.
- Do not make live model/network credentials mandatory for normal tests.

## Work Rules

When changing this repo:

1. Read `docs/agent-world-environment-generation.zh.md` first.
2. Use AWM material only as background or source evidence.
3. Remove or rewrite documents that conflict with the current task source.
4. Keep new implementation scoped to generic request-driven generated environment contracts unless the user explicitly asks to expand the scope.
5. Use `uv` for Python commands.
6. Preserve existing `awm` CLI behavior unless explicitly asked otherwise.
<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
