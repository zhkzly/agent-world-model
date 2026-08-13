---
name: engineer-environment-codegen
description: Complete the small candidate project — implement the frozen Task Materializer and five-operation Runtime, self-verify them offline, and return the bounded completion.
---

You are given a frozen environment contract and a fresh writable workspace. Treat
this as one small, self-contained project: read the inputs, implement exactly the
Runtime and Task Materializer the contract freezes, run them yourself to verify,
then return the bounded completion. The framework — not you — owns scan,
admission, manifest, verifier, Judge, and release.

## 1. Inputs (read-only, in `inputs/`)

- `inputs/design.json` — the compiled World/Tool closure: declared tools, their
  ordered input/output/observation schemas, namespaces, shared/local rules, and
  per-task-family public goal fields with rule summaries.
- `inputs/implementation-contract.json` — the exact Runtime ABI operations, the
  Task Materializer v3 contract, the frozen `tool_semantics`, the required source
  files, and the dependency/size limits you must satisfy.
- `inputs/build-plan.json` — the ordered implementation steps, goals, and risks.

Read all three before writing anything. They are the only source of truth. Do not
infer tool surfaces, semantics, or lifecycles the contract does not declare, and
do not assume which family or tool comes first.

## 2. What to implement

Two source components hold authority; nothing else does.

- `runtime.py` — the Runtime. Implement exactly the operations frozen in the
  contract over stdin/stdout JSONL: `handshake` (exact WorldSpec tool IDs,
  namespaces, names, input/output/observation schemas — six fields each, optional
  `description` only), `reset(seed, actor, initial_config)` (deterministic init,
  bind actor, return visible observation and state digest), `invoke(tool_id,
  arguments, idempotency_key)` (execute the declared transition, enforce
  permissions, return result, actor-visible observation, empty untyped channels,
  digest, and diagnostic lifecycle fields), private `snapshot` (full program state
  and digest for Judge use), and `close` (release episode resources). After reset,
  every snapshot state is
  `{"tools": {tool_name: {result_field: json_value}}}` for every declared tool and
  result field; preserve it across reset -> pre-snapshot -> invoke -> result ->
  post-snapshot. The snapshot is framework-private: never place its values in
  completion text or any public response.
- `materializer.py` — the Task Materializer v3. It proposes public task parameters
  and exact-echoes the contract's ordered response for every declared family and
  difficulty schema; it does not evaluate success. Validate each task type, actor,
  and difficulty against the frozen curriculum and return the closed v3 object
  with no extra fields. The contract's `public_goal_example_shape` /
  `initial_config_example_shape` show the **required nested structure** for those
  two fields: each JSON-pointer path is successive dict keys (so `/tools/1/status`
  means `{"tools":{"1":{"status":...}}}`), sibling paths share parents, and each
  leaf string is the **value category** — replace every leaf with a real value of
  that category. The materialized `public_goal` / `initial_config` must have
  exactly these leaf paths, no more, no fewer. Crucially, those values must
  **depend on the `difficulty` selection**: the framework materializes the same
  task with two different difficulties and rejects the candidate if the
  `public_goal` (and `initial_config`) come out identical. So each materialization
  must embed the chosen difficulty levels into the goal/config values — e.g. a
  goal leaf that holds `f"{level_name}-{seed}"` (level drawn from the request's
  difficulty selection, seed from the request), so different difficulties yield
  different `public_goal` values. Do NOT return fixed goal/config values that
  ignore `difficulty`.

Prefer the standard library for the first proof. Ordinary registry-wheel
dependencies are allowed only when represented exactly in both `pyproject.toml`
and `uv.lock`; the framework decides whether their bytes exist. Never install,
download, select an index, choose a hash, or claim a wheel is available. Build
backends, indexes, URLs, paths, editables, Git, and source distributions are
forbidden. `errors` and `reject` are design/package facts only in Direct v1; do
not invent an error response ABI. Never write verifier, Judge, reward,
termination, package, manifest, hash, or release facts.

## 3. How to execute and self-verify (required before returning)

Run your own code offline, read-only-source, no network. Drive `runtime.py` over
stdin/stdout JSONL yourself, using only the standard library and any dependency
you have declared that is locally importable here; if a declared registry
dependency is not yet installed in this workspace, verify every check that does
not require it and record the limit in `known_limits`. Confirm, at minimum:

- import and `handshake` succeed, exposing exactly the declared tool surface;
- same-seed `reset` reproduces state and different seeds vary;
- every declared tool runs through its full ABI id, including one real
  state-changing workflow and one denied or invalid action that fails without
  mutating state;
- the Task Materializer echoes the exact difficulty schema and rejects missing,
  extra, duplicate, reordered, or unknown levels before Runtime;
- for each task type and allowed actor, trace one materialized initial state
  through each required tool and confirm the state schema, materialized values,
  and frozen tool precondition share a common valid state — if they do not,
  report the frozen paths as a blocked input conflict rather than inventing an
  undeclared lifecycle to satisfy a local test.

If any self-check fails, fix the implementation; do not declare completion. These
self-checks are candidate diagnostics, not release authority.

## 4. Deliverable

Write the candidate source into the workspace root. The framework ALREADY
provides `pyproject.toml`, `uv.lock`, AND `runtime.py`:
- `pyproject.toml` + `uv.lock`: admission-correct, stdlib-only boilerplate — do
  NOT create, modify, or delete them, and do NOT declare dependencies.
- `runtime.py`: a **scaffold** with the correct JSONL protocol loop (`main`) and
  operation stubs (`do_reset`, `do_invoke`, `do_snapshot`, `do_close`). Fill the
  `TODO` sections in those functions with your environment's actual logic —
  state initialization, tool dispatch, snapshot values. DO NOT modify `main` or
  the function signatures; the protocol loop is correct.

You ALSO write `materializer.py` and a non-empty `LICENSE` from scratch. The
framework enumerates your files, installs dependencies offline, then runs your
Runtime + Materializer through the full ABI — that live run verifies correctness.
Keep the closure minimal; do not write inputs back or scratch files.

After writing source, return only this bounded JSON completion:

```json
{"summary":"...","self_checks":[{"name":"...","observed":"passed","note":"..."}],"known_limits":["..."]}
```
