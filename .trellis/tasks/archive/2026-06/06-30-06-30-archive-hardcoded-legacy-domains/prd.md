# Archive hardcoded legacy domains

## Goal

Delete or archive hardcoded legacy domain paths so the core project structure centers on generic request-driven environment generation, generic replay contracts, agent-backed code generation, and framework-owned verification.

## Requirements

- Remove executable legacy domain fixtures from the current core path:
  - fixture runtime/package/rollout/training/online modules
  - fixture registries, codegen templates, and generated-bundle shortcuts
  - environment-id keyed verifier/task branches and helper modules
- Keep the `awm` CLI compatibility surface unless it is explicitly unrelated to the legacy generated-environment path.
- Keep the request-driven S0-S11 pipeline as the main vertical slice.
- The normal success path must derive domain id, source evidence, knowledge, tools, tasks, replay cases, implementation request, generated bundle, independent verification, and release/package artifacts from upstream artifacts.
- The framework-owned independent verifier must be contract-driven, not keyed by environment id or task id constants.
- Remove or rewrite tests and current docs that encode old hardcoded domains as expected behavior.
- Do not introduce a new smoke domain as a replacement fixture.
- Use `uv` for Python validation commands.

## Acceptance Criteria

- [x] `agent_world/` has no executable legacy hardcoded modules, registries, default tasks, or verifier dispatch branches.
- [x] Request-driven generated-environment tests still cover agent candidate generation, generated check rejection, independent verifier positive/negative records, bounded repair success, repair exhaustion, package release, and artifact lineage.
- [x] `awm` CLI compatibility tests still pass.
- [x] Current project docs and progress log describe the generic request-driven path as the active slice and do not present old fixture goals as current required behavior.
- [x] Project validation passes with `uv run --offline pytest tests/agent_world -q`, `uv run --offline python -m compileall agent_world tests`, and a grep audit for legacy hardcoded terms in executable code.

## Notes

- Archival is allowed for documentation if it improves traceability, but archived material must not remain on the executable import path.
- If a legacy test only proves a deleted fixture, remove it instead of renaming it to a generic test.
