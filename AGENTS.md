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

- Read the source-of-truth document before changing code. Then read
  `docs/direct-rewrite-execution-map.zh.md` for the binding distinction between
  component authority, logical Work, Direct LLM, tool-enabled Codex Agent, and
  untrusted candidate process. The execution map is a derived index, not a
  second source of truth; the source-of-truth document wins on any conflict.
- Before a semantic, permission, route, persistence, public-entry, validation,
  or control-plane behavior change, write/update a plan and pass it through
  .agents/skills/agent-world-cross-layer-critic/SKILL.md. For a real failure
  use Observe -> agent-world-debugging -> Diagnosis Record -> repair plan ->
  cross-layer critic -> implementation -> real-execution proof -> Observe.
  This is a development gate, not a runtime node or second Judge. A `block`
  returns actionable plan feedback and permits at most two revisions; only
  `allow` permits implementation.
- Use an independent read-only trellis-research critic for the trust-boundary
  triggers defined by that skill. Add its current matching `allow` record to
  the task JSONL context before dispatching implement/check.
- Keep implementation under the current `agent_world/` slice unless the user explicitly expands scope.
- Use real llm/agent invocation through `InvocationBackend`; do not fake codegen with templates or generic shell runners.
- Codex SDK integration should be a real backend adapter, not scattered SDK calls in pipeline core.
- Do not reintroduce fixed environments, fixed task ids, fixed replay cases, fixture registries, or environment-id verifier branches as normal success paths.
- Do not write secrets into artifacts, traces, manifests, or release packages.
- For any failed run, read `observe scene` before acting.
- At the entry and exit of every key graph node family, child-task boundary,
  real-execution proof, release decision, or legacy-disposition decision, write
  a Product Alignment Checkpoint in the active task. It must restate the
  canonical goal (natural-language need -> executable, independently verified,
  publishable EnvironmentPackage), name the affected trust boundary and
  evidence, state what is still unproven, and confirm that graph/test progress
  alone is not being claimed as product completion. See
  `.trellis/spec/guides/foundry-product-alignment.md`.
- Use `uv` for Python commands.
- Do not preserve the old `awm` CLI, runtime ABI v1, or replay compatibility path; the user explicitly approved a clean-break redesign.

## Trellis

Trellis task/workflow/journal documents are not project source of truth. `.trellis/spec/` may contain concise coding guidance only.
