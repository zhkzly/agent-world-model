---
name: engineer-environment-codegen
description: Complete the small candidate project — implement the frozen Task Materializer (the Runtime is framework-provided and design-driven), self-verify offline, and return the bounded completion.
---

You are given a frozen environment contract and a fresh writable workspace. Your
ONLY coding job is `materializer.py` (plus a non-empty `LICENSE`). The framework
already provides `runtime.py` — complete and correct by construction — plus
`pyproject.toml` and `uv.lock`. Read the inputs, implement the Materializer, run
it offline to verify, then return the bounded completion. The framework owns
runtime, scan, admission, manifest, verifier, Judge, and release.

## 1. Inputs (read-only, in `inputs/`)

- `inputs/design.json` — the compiled World/Tool closure in a **name-based**
  format: `boundary`, `entities`, `fields`, `tools` (each tool's argument/result
  fields and its name-based preconditions/transitions/postconditions/errors as
  `{field, operator, value}` / `{field, operation, value}`), shared tool
  contracts, world rules, and `task_families` (each by `task_family_id`, with
  named actor/tools and difficulty dimensions).
- `inputs/implementation-contract.json` — the Task Materializer v3 response
  contract, the difficulty schemas, the snapshot projection obligation, and the
  source size/file limits. Design context lives only in `design.json`.
- `inputs/build-plan.json` — the ordered implementation steps, goals, and risks.

Read all three before writing anything. Reference tools and task families by
their declared names/ids, never by positional index.

## 2. What you implement

- `runtime.py` — **framework-provided and complete; do NOT create, modify, or
  delete it.** The framework generates a design-driven runtime that implements
  the full JSONL protocol (`handshake`/`reset`/`invoke`/`snapshot`/`close`) and
  applies each tool's declared transitions to produce its declared `result_fields`.
  Its state is correct by construction; it passes integration without any work
  from you. Writing or editing `runtime.py` is wasted effort (the framework
  overwrites it with the correct version).

- `materializer.py` — the Task Materializer v3. THIS is your job. It proposes
  public task parameters and exact-echoes the contract's ordered response for
  every declared family and difficulty schema; it does not evaluate success.
  Validate each task type, actor, and difficulty against the frozen curriculum
  and return the closed v3 object with no extra fields. The contract's
  `public_goal_example_shape` / `initial_config_example_shape` show the
  **required nested structure** for those two fields: each JSON-pointer path is
  successive dict keys (so `/tools/1/status` means `{"tools":{"1":{"status":...}}}`),
  sibling paths share parents, and each leaf string is the **value category** —
  replace every leaf with a real value of that category. The materialized
  `public_goal` / `initial_config` must have exactly these leaf paths, no more,
  no fewer. Map every `public_goal` leaf to its declared field through the design’s `task.public_goal_leaf_map` rows (index -> name/source/category): generate each leaf’s value from the mapped field semantics and the SCHEMA category of that leaf. Never infer a leaf’s meaning from its path suffix or its numeric index. Crucially, those values must **depend on the `difficulty` selection**:
  the framework materializes the same task with two different difficulties and
  rejects the candidate if the `public_goal` (and `initial_config`) come out
  identical. So each materialization must embed the chosen difficulty levels into
  the goal/config values — e.g. a goal leaf that holds `f"{level_name}-{seed}"`
  (level from the request's difficulty, seed from the request), so different
  difficulties yield different `public_goal` values. Do NOT return fixed
  goal/config values that ignore `difficulty`.

Prefer the standard library. Never install, download, select an index, choose a
hash, or claim a wheel is available. Never write verifier, Judge, reward,
termination, package, manifest, hash, or release facts.

## 3. How to execute and self-verify (required before returning)

Run your own code offline, read-only-source, no network. Drive `materializer.py`
over its contract and `runtime.py` over stdin/stdout JSONL yourself (the runtime
is already complete - just exercise it). Your materializer MUST flush stdout
after every response (print(..., flush=True) or an explicit
sys.stdout.flush()): pipes are block-buffered and an unflushed response can
stall the protocol. Implement the idempotency contract: the same `idempotency_key` must return an IDENTICAL response with no repeated side effects (cache per key, clear on reset). Confirm, at minimum: — just exercise it). Confirm, at minimum:

- `runtime.py` `handshake` returns the operations list, `reset` returns
  `{"status":"ok"}`, each tool `invoke` returns `{"status":"ok","result":{...}}`,
  and `snapshot` returns `{"state":{"tools":{...}}}`;
- the Task Materializer echoes the exact difficulty schema and rejects missing,
  extra, duplicate, reordered, or unknown levels;
- for each task type and allowed actor, the materialized `public_goal` differs
  across two different difficulties (the framework rejects identical goals).

If a self-check fails, fix `materializer.py` (NOT `runtime.py`); do not declare
completion. These self-checks are candidate diagnostics, not release authority.

## 4. Deliverable

Write `materializer.py` and a non-empty `LICENSE` into the workspace root. The
framework ALREADY provides `pyproject.toml`, `uv.lock`, AND `runtime.py` — do NOT
create, modify, or delete any of them, and do NOT declare dependencies. The
framework enumerates your files, then runs the (framework-provided) Runtime +
your Materializer through the full ABI — that live run verifies correctness.

After writing source, return only this bounded JSON completion:

```json
{"summary":"...","self_checks":[{"name":"...","observed":"passed","note":"..."}],"known_limits":["..."]}
```
