# AGENTS.md

## Project Intent

Build an Agent-World-like environment generation system.

The system is a loop-engineering framework: code owns the workflow, artifacts, gates, repair budget, and release decisions; agent SDK backends execute search, extraction, synthesis, code generation, review, and repair nodes; humans are asked only when permission, ambiguity, risk, credentials, or release policy requires confirmation.

Canonical example: the user provides only a text need for a local business workflow environment; the pipeline should then automatically research requirements, discover MCP/CLI/API/SDK/tool surfaces, generate tasks and verifiers, generate runtime code, validate every key node, repair failures, and package a publishable environment.

Source of truth:

- `docs/agent-world-environment-generation.zh.md`

Background only:

- `docs/loop-engineering.md`
- raw sample data under `research/data/awm_1k_samples/`

## Working Rules

- Read the source-of-truth document before changing code.
- Keep implementation under the current `agent_world/` slice unless the user explicitly expands scope.
- Use real llm/agent invocation through `InvocationBackend`; do not fake codegen with templates or generic shell runners.
- Codex SDK integration should be a real backend adapter, not scattered SDK calls in pipeline core.
- Do not reintroduce fixed environments, fixed task ids, fixed replay cases, fixture registries, or environment-id verifier branches as normal success paths.
- Do not write secrets into artifacts, traces, manifests, or release packages.
- For any failed run, read `observe scene` before acting.
- Use `uv` for Python commands.
- Do not preserve the old `awm` CLI, runtime ABI v1, or replay compatibility path; the user explicitly approved a clean-break redesign.

## Trellis

Trellis task/workflow/journal documents are not project source of truth. `.trellis/spec/` may contain concise coding guidance only.
