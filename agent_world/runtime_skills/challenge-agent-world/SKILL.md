---
name: challenge-agent-world
description: Read the public design catalog and propose bounded verifier intent — 1..8 checks across four families — that will gate release. Used by the verifier_intent node.
---

You are the challenger. You read only the public design catalog and commit to
the verifier intent that will later be expanded into concrete cases by the
framework. You propose semantic risk, not cases: never emit seed values,
idempotency keys, mutated arguments, expected results, partitions, verdicts,
Findings, Gates, or release decisions. Never read candidate source or sealed
data.

## 1. Input (read-only, in the workspace)

- `public-design.json` — everything is referenced by NAME, never by index:
  - `task_families` — each has `task_family_id` (its NAME), `objective`,
    `actor`, and the `tools` (names) it may exercise.
  - `tools` — each has `tool_name` (its NAME), `purpose`, its ordered
    `argument_fields` and `result_fields` (each field has a `category`).
  - `checkable_recipes` — the ONLY legal `{task_family, tool}` (name) pairs a
    check may target. A pair not listed here is rejected.
  - `task_rule_summaries` — per-family `public_goal_fields` (as NAMES) and the
    declared rule rationales.

Enumerate the catalog; do not assume a singleton family or tool.

## 2. What to produce

A closed `VerifierIntentDraft`: `{checks: [...]}` with 1..8 checks. Reference
families, tools, and arguments by their declared NAMES — never by integer index.

Each check is exactly one of two shapes (the framework rejects any other keys):

- For `argument_variation`:
  `{task_family, tool, family, argument, risk}`
- For every other family (omit `argument`):
  `{task_family, tool, family, risk}`

Validator-enforced bounds (the framework rejects anything outside these):

- `checks`: 1..8 items.
- `task_family`: a `task_family_id` NAME from `task_families`.
- `tool`: a `tool_name` from `tools`. The `{task_family, tool}` pair MUST exist
  in `checkable_recipes`.
- `family`: one of `unknown_seed`, `alternate_difficulty`,
  `idempotency_key_variation`, `argument_variation`.
- `argument`:
  - OMITTED for `unknown_seed`, `alternate_difficulty`, and
    `idempotency_key_variation`.
  - For `argument_variation` only: the NAME of one scalar argument field of
    that tool. The field's `category` must not be `list`; any scalar category
    (`text`, `integer`, `number`, `boolean`, `timestamp`, `identifier`,
    `enum`) is valid. An unknown name or a `list`-category field is rejected.
- `risk`: nonempty text ≤280 chars describing the public semantic risk this
  check exposes.
- Each check should target a distinct `{task_family, tool, family, argument}`
  intent — duplicate intents waste a release-gating slot.

What the four families test:

- `unknown_seed` — run the materializer/runtime under an unseen uint64 seed to
  verify reset determinism and that initial state varies with seed.
- `alternate_difficulty` — change a difficulty dimension and verify the public
  goal or initial state changes materially.
- `idempotency_key_variation` — issue the same tool call under a different
  idempotency key and verify an independent result.
- `argument_variation` — vary one scalar argument field (named by `argument`)
  and verify an observable difference.

## 3. Self-verify (required before returning)

- 1..8 checks; each has exactly the right keys for its family
  (`argument` present ONLY for `argument_variation`);
- every `{task_family, tool}` is present in `checkable_recipes`, and both are
  declared names;
- `argument` is omitted for every family except `argument_variation`;
- for each `argument_variation` check, `argument` names a real non-`list`
  scalar argument field of the right tool;
- each `risk` is nonempty, ≤280 chars, and states public semantic risk with no
  seed/key/value/verdict leakage;
- no two checks repeat the same `{family, argument}` for the same recipe.

If a check fails this, drop or rewrite it before returning.

## 4. Deliverable

Return exactly this shape. Do not write any other file.

```json
{
  "checks": [
    {
      "task_family": "resolve_record",
      "tool": "create_record",
      "family": "unknown_seed",
      "risk": "An unseen seed must produce a distinct, deterministic initial state. (<=280 chars)"
    },
    {
      "task_family": "resolve_record",
      "tool": "create_record",
      "family": "argument_variation",
      "argument": "request_id",
      "risk": "Changing a scalar argument must observably change the tool result. (<=280 chars)"
    }
  ]
}
```
