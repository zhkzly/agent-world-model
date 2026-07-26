# World Rules E2E Diagnostic Fidelity — Implementation Plan

## Preconditions

- Keep the task in planning until these artifacts are reviewed.
- Preserve existing working-tree changes; do not reset, checkout, or rewrite
  files owned by prior work.
- Use `uv run` for Python/test commands and keep live credentials in the
  existing environment only; never print or write their values.

## Ordered Execution

### 1. Reconfirm the single-node baseline

- Read only safe telemetry columns and the frontier for the captured
  `world_rules` coordinate.
- Recount `raise ValueError` inside the seven target validators and record
  their actual line locations.
- Record the four-way decision: the current blocker is feedback fidelity,
  because the proposal ran and its only issue is the generic fallback.
- Do not run `test-node` yet: no causal code/prompt/Skill change exists.

### 2. Establish direct failing regressions

- Extend `test_designer_world_composition.py` using the existing portable
  counter fixture or a complete constructed `WorldSemanticSourceIRDraft`.
- Add one parametrized or individually named case per stable diagnostic code.
  Each case starts valid and poisons exactly one source condition.
- Add an integration test for the compiler path and retain the existing
  one-shot bare-`ValueError` non-actionability guard.
- Run only the newly added/directly affected tests. They must fail for the
  expected missing typed diagnostic before an implementation change is made.
- After the first case proves the mechanism, complete the whole seven-validator
  same-boundary inventory before any compiler or E2E rerun. A passing first
  example is not evidence that the remaining homologous bare-error sites are
  safe.
- Treat only the explicit `initial_state_rule_family` check as proposal-owned.
  Treat `initial_state_rule_id_prefix`,
  `initial_state_rule_id_duplicate`, and the other 23 direct sites as
  frozen-input/framework invariants unless a constructed call proves a
  different provenance; they must be typed but `retryable=False`.

### 3. Migrate one validator boundary at a time

For each group below, classify every site by actual proposal versus framework
ownership, implement the typed issue collection, register safe contracts, run
the group's direct tests, and only then proceed to the next group:

1. `_validate_world_state_shape_draft`
2. `_validate_initial_state_rules_draft`
3. `_validate_world_tool_plan_inventory_draft`
4. `_validate_tool_schema_draft`
5. `_validate_tool_surface_schemas_draft`
6. `_validate_world_tool_inventory_draft`
7. `_validate_world_skeleton`

No group may be merged into a later E2E test while its direct test is failing.
If a migration reveals an architectural ownership mismatch, refactor the local
boundary rather than encoding a misleading diagnostic.

### 4. Complete compiler and safety regressions

- Add/update `_DESIGNER_SEMANTIC_CONTRACTS` for every new code and derive
  condition/category from that table.
- Verify proposal-owned conditions are actionable and framework invariants are
  explicitly `retryable=False`.
- Verify every direct targeted validator is free of bare `raise ValueError`,
  while unrelated catch-all behavior remains fail-closed.
- Run focused tests, then:

```bash
UV_CACHE_DIR=/tmp/agent-world-uv-cache uv run pytest \
  tests/agent_world/test_designer_world_composition.py \
  tests/agent_world/test_feedback_contracts.py \
  tests/agent_world/test_designer_structured_rework.py -q
```

If a failure is not localized, stop and classify it before modifying another
area.

### 5. Perform one isolated live E2E confirmation

- Check isolation availability and the configured nontracked live profile
  without exposing its values.
- Run only the captured `world_rules` `test-node` coordinate against its
  copied state root. It must remain `diagnostic_only=true` and
  non-releasable.
- Inspect only safe span status/error/duration, frontier code/path/condition,
  and observability scene.

The run is allowed only because steps 1–4 produce a deterministic causal
change. It is not a retry lottery.

### 6. Decide the next action from the new E2E result

- **Passed/committed:** record the progress and hand the staged parent the
  next downstream coordinate; do not claim Registry release.
- **Typed `failed`:** test the reported node in isolation and choose prompt,
  Skill, or code from the four-way gate before another live run.
- **Generic `failed`:** repair that feedback boundary first.
- **`error` / transport / isolation:** stop this semantic task and record the
  infrastructure owner; do not mutate WorldSpec.
- **No-progress or oscillation:** stop, write a causal report, and request a
  new design decision if the smallest owner must expand.

## Validation Matrix

| Level | Proof | Required before next level |
|---|---|---|
| Direct validator | Stable code/path/actionability and no value disclosure | Yes |
| Compiler integration | No target failure reaches generic one-shot fallback | Yes |
| Focused regression suite | Designer/rework/feedback contracts pass | Yes |
| Live test-node | Fresh real Agent result for the one coordinate | Last only |

## Execution Record Before Fresh Live Confirmation

- The seven-validator inventory was migrated to typed safe diagnostics and
  covered by constructed inputs.
- A first real isolated WorldRules result exposed a second, distinct
  mechanics-only issue: two optional Agent-authored IDs did not match a
  framework-required prefix.
- The full WorldRules prompt/Skill/compiler/persistence audit completed before
  changing it. The repair makes IDs code-derived, strengthens the active and
  legacy prompts plus durable Skill guidance, and leaves semantic family
  validation Agent-actionable.
- Direct compiler integration, prompt/Skill injection, work-graph revision,
  Scheduler, and `test-node` regressions pass (128 tests); Ruff and mypy pass.
- A broad `pytest tests/agent_world -x -vv` supplementary run passed through
  51% but produced no terminal diagnostic while inside a verifier
  cancellation/straggler test, so it was interrupted rather than reported as
  green. This is not evidence against the WorldRules node and is not folded
  into its owner decision; a future test-suite investigation must isolate that
  test/harness separately.
- The next permitted action is exactly one fresh isolated `world_rules`
  `test-node` invocation. It is causally different because arbitrary model IDs
  are now canonicalized away before validation/persistence and the active
  prompt/Skill have a stable semantic ownership contract.

## Fresh Live Result

- The permitted isolated `world_rules` `test-node` was run once after the
  deterministic gate.
- Its safe terminal evidence is `committed` / `passed`, with a resolved empty
  frontier and no failure code.
- It is explicitly diagnostic-only and non-releasable. No downstream node was
  started from this task.

## Rollback / Stop Rules

- Do not use destructive Git commands.
- If an implementation attempt violates the validation matrix, revert only
  that uncommitted local change through a reviewed patch, retain the failing
  regression, and revise the owner decision.
- If live prerequisites or provider availability are absent, record a bounded
  infrastructure blocker and stop. Do not emulate a live success.
