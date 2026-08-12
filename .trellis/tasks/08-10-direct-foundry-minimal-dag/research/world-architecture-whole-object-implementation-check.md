# WorldArchitecture whole-object implementation check

- Decision: **allow** for the bounded deterministic implementation check.
- Reviewed plan: `world-architecture-whole-object-check-plan.md`, SHA-256 `9e2c17c8ca5979d1493b22c405d20dbe034717e21b8d373110e3f1e866cfa8be` (recomputed from the target worktree).
- Matching critic record: `cross-layer-review-9e2c17c8-world-architecture-whole-object-r2.md`, `Decision: allow`; it is referenced by `check.jsonl` entries 66-67.

## Evidence

- `agent_world/design.py:928-1207` retains the existing compiler and typed construction: entity-field `entity_ref` closure remains at lines 1056-1067, while tool `argument_fields` and `result_fields` both reuse the generic field parser without declared-entity closure (lines 1068-1124). The only repaired model-visible contract is the inline complete-object shape at lines 1201-1207.
- The shape requires a coherent 1..8 tool array, complete-object recheck on initial and correction calls, entity-name closure only for `entities[*].fields[*]`, and optional external snake-name relations in both tool-field locations.
- `_direct_commit` still passes the frozen projection, shape, and prompt identity as semantic material (`design.py:581-624`). The focused test proves that changing the output-shape wording changes `semantic_revision_digest` while the actual `world_architecture` node remains `direct_llm`, route `direct`, with one local correction (`tests/test_design_semantics.py:451-553`).
- The compiler still rejects the ninth tool through the unchanged 1..8 bound; the deterministic regression proves eight tools commit and nine tools reject (`tests/test_design_semantics.py:645-663`). The two-proposal regression proves one correction followed by a terminal second invalid proposal, with exactly two calls and no third (`tests/test_design_semantics.py:611-643`).
- External relation labels are exercised independently in both `argument_fields` and `result_fields`, while an undeclared entity-owned relation still rejects (`tests/test_design_semantics.py:557-609`).
- The WorldArchitecture task contract accurately mirrors the sparse source draft and location-qualified relation semantics (`node-contracts.md:309-353`). It does not become runtime input.
- Authority remains correctly split: the Direct LLM receives a frozen projection plus an optional safe correction and explicitly has no tools, Skills, workspace, or release authority (`design.py:545-565`); framework code owns parsing, compiler validation, IDs, schema/type construction, semantic identity, and commit. No Agent or candidate-process authority, route, graph node, helper/prompt framework, retry path, or business-specific production semantic was introduced in the named repair files.
- Production Python LOC is exactly `10,296` across the 13 `agent_world/**/*.py` files, meeting the `<= 10,296` cap.

## Findings (fixed)

- None. This review made no source, test, plan, or node-contract edits.

## Findings (not fixed)

- None.

## Verification

- Focused: `uv run pytest tests/test_design_semantics.py` — **pass** (`28 passed`).
- Full: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider` — **pass** (`186 passed`).
- Ruff format: `uv run ruff format --check .` — **pass** (`22 files already formatted`).
- Ruff check: `uv run ruff check .` — **pass**.
- TypeCheck: `uv run mypy --no-incremental agent_world` — **pass** (`13 source files`).
- Compileall: `PYTHONDONTWRITEBYTECODE=1 uv run python -B -m compileall -q agent_world` — **pass**.
- Diff whitespace: `git diff --check` — **pass**; the three named untracked files also have no trailing whitespace.
- No provider or live Agent/LLM invocation was run.

## Scope note and non-claims

The three named implementation artifacts are currently untracked at `HEAD` `9562c05`, so Git cannot produce a predecessor line diff for them. This review therefore establishes present-code and deterministic-behavior compliance with the exact allow, not a historical line-by-line delta claim. All other dirty worktree content was left untouched.

This check validates only the Direct LLM-to-WorldArchitecture producer contract. It does not prove model compliance in a real call, repair the prior E2E, produce a Candidate/Judge/Registry result, publish an `EnvironmentPackage`, or prove Repair, Expand, multi-parent, Consumer, SFT, or RL behavior. The next allowed proof remains the plan's one frozen-evidence WorldArchitecture invocation, followed only on success by a fresh public Direct request and terminal Observe inspection.
