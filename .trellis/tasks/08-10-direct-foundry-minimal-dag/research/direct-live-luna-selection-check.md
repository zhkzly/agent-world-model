# Direct live Luna-selection deterministic check

Date: 2026-08-11
Reviewer: independent `trellis-check`

## Decision

Decision: allow

The current plan file hashes to
`2fa178fb5725aaad7b09806cbea1066a809617a1ed13b3847dcd667a459950d5`, exactly
matching the current cross-layer `allow` record. The diagnosis for
`run_9b004e18777140cc8cdfded98a6933cc` is consistent with this bounded repair:
Spark exhausted the unchanged one local semantic correction and committed an
honest rejected WorkRecord/Finding; it was not a transport retry or a prompt,
schema, or provenance failure.

The checked-in Direct selection is now exactly Luna primary and Spark fallback
with the established localhost chat-completions endpoint and
`OPENAI_API_KEY`. The execution map and complete-v1 parent route table match
that Direct order. The Agent route remains Luna primary and Spark fallback.
`load_settings` still produces the same immutable `ChatRoute` values, and
`DirectChatBackend` still calls primary once, uses fallback only when
`InvocationError.failure.retryable` is true, and propagates non-retryable
semantic rejection. No route schema, adapter call shape, retry/correction
budget, usage normalization, graph/provenance, package/Observe, Repair, Expand
or Consumer behavior changed in this selection slice.

The focused checked-in-example assertion covers both Direct route values. The
existing cleanroom edits outside this authorized configuration/documentation/
parent-design/test slice were preserved. No mechanical defect within the four
authorized files was found, so no implementation edit was made.

## Verification

- `uv run pytest`: pass (97 passed).
- `uv run ruff format --check .`: pass (21 files already formatted).
- `uv run ruff check .`: pass.
- `uv run mypy agent_world`: pass (13 source files).
- `uv run python -m compileall -q agent_world`: pass.
- `uv run pytest tests/test_legacy_firewall.py`: pass (2 passed).
- `git diff --check`: pass.

## Non-claims

This deterministic check made no live provider or Agent call and did not mutate
a run. It does not claim that Luna satisfies `world_architecture`, that a fresh
WorkRecord or Observe terminal exists, or that CandidateBuild, Integration,
Judge, Registry publication, Repair, Expand, Consumer/SFT/RL, or end-to-end
EnvironmentPackage generation has been proven. A Luna semantic rejection is a
new observed failure requiring a new diagnosis and reviewed plan; it does not
authorize Prompt, contract, normalization, correction-budget, adapter, retry,
or fallback-policy changes.
