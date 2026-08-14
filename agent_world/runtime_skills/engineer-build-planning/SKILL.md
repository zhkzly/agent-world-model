---
name: engineer-build-planning
description: Decompose a frozen environment design into an ordered, bounded implementation plan (1..12 steps plus risks) before any candidate source is written. Used by the build_plan node.
---

You are given a frozen environment design and its implementation contract. Read
both, then return one advisory build plan. This plan guides the candidate
engineer; it is not source, not a manifest, and carries no admission, hash,
Judge, or release authority.

## 1. Inputs (read-only, in the workspace)

- `design.json` — the compiled public World/Tool closure in a **name-based**
  format: `boundary` (name, purpose, actors), `entities`, `fields` (semantic
  field rows by NAME), `tools` (each tool's argument/result fields and its
  preconditions/transitions/postconditions/errors as name-based
  `{field, operator, value}` / `{field, operation, value}` dicts), shared tool
  contracts, world rules, and `task_families` (each by `task_family_id`, with
  named actor/tools and difficulty dimensions). No positional indexes, no
  observation schemas, no namespaces.
- `implementation-contract.json` — the frozen implementation closure. It
  contains a top-level `sections` array naming every valid contract section
  (the only legal values for each step's `contract_sections`): `source_closure`,
  `materializer`, `runtime`, `tool_obligations`, `tool_semantics`, `difficulty`,
  `idempotency`, `shutdown`, `dependency_policy`. It also freezes the Runtime
  ABI, the Task Materializer v3 response, `tool_semantics`, and the source
  size/file limits.

Read both before planning. Do not assume a singleton family or tool, and do not
infer surfaces the contract does not declare.

## 2. What to produce

A closed `BuildPlanDraft` object: an ordered decomposition of 1..12 steps that
walks the contract from materializer/runtime scaffolding through per-tool
obligations to shutdown, plus 0..8 risks. Steps are advisory ordering — they do
not grant source or validation authority. Each step's `contract_sections` must
reference the parts of `implementation-contract.json` that step realizes, and
each `self_check` must be a single deterministic, runnable assertion you could
execute against the candidate (for example, "uv run runtime.py handshake exposes
exactly the declared tool IDs"), not a vague goal.

Validator-enforced bounds (the framework rejects anything outside these):

- Top object: exactly `{steps, risks}`.
- `steps`: 1..12 items. Each step is exactly
  `{goal, suggested_paths, contract_sections, self_check}`:
  - `goal`: nonempty text, ≤500 chars.
  - `self_check`: nonempty text, ≤500 chars.
  - `suggested_paths`: 1..8 items, unique within the step. Each is a nonempty
    string ≤160 chars and a safe relative path: no leading `/`, no `\`, and no
    `/`-split part that is empty, `.`, `..`, or starts with `.`.
  - `contract_sections`: 1..9 items, unique within the step; every item is a
    string present in `implementation-contract.json` `sections`.
- `risks`: 0..8 items; each is nonempty text ≤500 chars.

## 3. Self-verify (required before returning)

For every step confirm:

- every `contract_sections` value is spelled exactly as a member of
  `sections` — typos or invented sections are rejected;
- every `suggested_paths` entry is a safe relative path and `suggested_paths`
  has no duplicates; `contract_sections` has no duplicates;
- steps are ordered so each step's dependencies precede it;
- each `self_check` is deterministic and runnable, not an aspiration.

If a check fails, fix the plan; do not return it broken.

## 4. Deliverable

Return exactly this shape (bounds annotated inline). Do not write candidate
source or any other file.

```json
{
  "steps": [
    {
      "goal": "Implement the five-operation Runtime handshake/reset/invoke/snapshot/close shell. (<=500 chars)",
      "suggested_paths": ["runtime.py"],
      "contract_sections": ["runtime", "shutdown"],
      "self_check": "echo handshake JSONL to runtime.py and it replies with the operations list. (<=500 chars)"
    }
  ],
  "risks": ["tool_semantics may require per-tool permission gating beyond the shared rules. (<=500 chars)"]
}
```
