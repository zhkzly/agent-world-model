# Design

## Scope

This is a documentation and Trellis alignment task. It should make the written project state match what the code and tests can prove today.

The work should not invent a new architecture. Existing source documents remain authoritative:

- Primary task source: `docs/agent-world-environment-generation.zh.md`
- Living drift log: `docs/project-progress-and-corrections.zh.md`
- Public summary: `README.md`
- Goal-specific records: `docs/goal-02-*.zh.md` through `docs/goal-12-*.zh.md`

## Product Frame

The project should be documented as a loop-engineering system for environment construction.

The target workflow is:

```text
raw environment need / capability gap
  -> deterministic workflow trigger
  -> source discovery / search when needed
  -> source-grounded knowledge extraction
  -> environment and task construction
  -> surface and verifier planning
  -> feasibility gates
  -> code-agent or deterministic implementation
  -> executable backend/runtime code plus state fixtures
  -> build/check/replay and independent verification
  -> package/release artifacts
  -> rollout/training/eval consumers
```

This is different from a prompt-only agent:

- Workflow code owns stage order, retries, stop conditions, state records, artifact lineage, and release decisions.
- LLMs/agents appear as explicit worker/evaluator/codegen nodes with budgets, permissions, inputs, outputs, traces, and gates.
- The system may use database/file-backed state transitions and expose MCP, CLI, Python, or HTTP surfaces, but none of those should be documented as the only acceptable architecture.
- Training is downstream consumption of a verified release, not the current core dependency.
- The environment output is backend/runtime code: state transition logic, tool/surface handlers, seed/state fixtures, task set, deterministic verifier, checks, and release metadata.
- Code agents such as Codex should implement or repair that backend/runtime code from source evidence and generated specs; the framework validates executability and correctness before release.
- Later loops may deploy the environment, drive SFT/verl-style sampling, and use training outcomes to propose new environment iterations. That feedback loop is explicitly future scope for this task.
- Python environment management and validation should be documented with `uv`, matching project work rules and `pyproject.toml`.

## Documentation Model

Use three layers:

1. Source of truth:
   `docs/agent-world-environment-generation.zh.md` defines long-term intent, first-slice contracts, stage/gate expectations, and boundaries.

2. Current-state log:
   `docs/project-progress-and-corrections.zh.md` records what has actually been implemented, what was corrected, and what remains untrue.

3. Reader-facing summary and staged Goal docs:
   `README.md` and Goal docs should point readers to the right state without overstating implementation completeness.

## Evidence Rules

Documentation may say "implemented" only when backed by inspected code and/or tests.

Strong evidence includes:

- A public entrypoint or function in `agent_world/`.
- A generated artifact/package contract in code.
- A test that demonstrates the claimed path.
- A source document that explicitly declares historical scope or non-goals.

Weak evidence must be described as a plan, staged goal, default skipped smoke, or future work.

## Expected Corrections

Likely edits are small and textual:

- Emphasize the loop-engineering purpose: replace repeated prompt tweaking with fixed, testable, replayable generation loops.
- Make clear that specs are intermediate artifacts; the desired release must contain executable backend/runtime code or a packaged generated runtime path.
- Clarify that Goal 12 currently has registered request-driven probe paths, not arbitrary-domain generation.
- Clarify that booking/library are strategy probes and still use domain-specific synthesis/codegen/verifier strategy code.
- Clarify that `openai_codegen` is file-content model codegen, while `code_agent_runner` / `codex_cli_runner` are runner contracts.
- Clarify that live model/runner smoke tests are opt-in and skipped without credentials/config.
- Clarify that generated runtime is package-callable through `generated-runtime-index.yaml`, but not yet a universal rollout/online adapter.
- Preserve the distinction among runtime control CLI, environment CLI surface, and agent backend CLI.

## Compatibility

- Do not remove references to existing staged Goal docs.
- Do not remove existing `awm` CLI compatibility statements unless they conflict with current code.
- Do not mark old fixture paths as generic generator paths.
- Do not claim `project_board_lite_node_registry()` is request-driven.

## Validation Strategy

Run text searches for outdated claims and targeted tests for the states that the docs describe.

Minimum validation:

- Re-read `docs/loop-engineering.md` before final documentation edits.
- Search docs for stale "current state" contradictions.
- Run Goal 12 request-driven tests.
- Run generated bundle/package or independent verifier tests if touched documentation makes those claims.
- Run a broader `uv run pytest tests/agent_world` if feasible.

If full tests are too slow or fail due unrelated dirty worktree state, record exactly what was run and what remains unverified.
