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

- `public-design.json`:
  - `families` — the declared curriculum task families.
  - `tools` — each tool carries `tool_index`, its `surface` (input/output/
    observation schemas and ordered `argument_fields`, where each field has a
    `category`), and `local_rules_digest`.
  - `assurance_recipes` — the only legal `(task_family_index, tool_index)`
    pairs a check may target. A pair not listed here is rejected.
  - `task_rule_summaries` — per-family public goal fields and rule summaries.

Do not assume any singleton family or tool; enumerate the catalog.

## 2. What to produce

A closed `VerifierIntentDraft`: `{checks: [...]}` with 1..8 checks. Each check
is exactly `{task_family_index, tool_index, family, argument_index, risk}`.

Validator-enforced bounds (the framework rejects anything outside these):

- `checks`: 1..8 items. Every check is exactly the five keys above — no extra
  or missing keys.
- `task_family_index` and `tool_index`: ints (booleans are rejected), and the
  `(task_family_index, tool_index)` pair must exist in `assurance_recipes`.
- `family`: one of `unknown_seed`, `alternate_difficulty`,
  `idempotency_key_variation`, `argument_variation`.
- `argument_index`:
  - `null` for `unknown_seed`, `alternate_difficulty`, and
    `idempotency_key_variation` — these families do not vary a single argument.
  - For `argument_variation` only: an int, one-based position of a scalar
    argument field in that tool's `argument_fields` (1..N). The selected
    field's `category` must not be `list`; any scalar category
    (`text`, `integer`, `number`, `boolean`, `timestamp`, `identifier`,
    `enum`) is valid. Out-of-range indexes or a `list`-category field are
    rejected.
- `risk`: nonempty text ≤280 chars describing the public semantic risk this
  check exposes.
- Each check should target a distinct `(task_family_index, tool_index, family,
  argument_index)` intent — duplicate intents waste a release-gating slot.

What the four families test:

- `unknown_seed` — run the materializer/runtime under an unseen uint64 seed to
  verify reset determinism and that initial state varies with seed.
- `alternate_difficulty` — change a difficulty dimension and verify the public
  goal or initial state changes materially.
- `idempotency_key_variation` — issue the same tool call under a different
  idempotency key and verify an independent result.
- `argument_variation` — vary one scalar argument field (named by
  `argument_index`) and verify an observable difference.

## 3. Self-verify (required before returning)

- 1..8 checks; each has exactly the five keys;
- every `(task_family_index, tool_index)` is present in `assurance_recipes`,
  and both indexes are ints;
- `argument_index` is `null` for every family except `argument_variation`;
- for each `argument_variation` check, `argument_index` is in range and selects
  a non-`list` field of the right tool;
- each `risk` is nonempty, ≤280 chars, and states public semantic risk with no
  seed/key/value/verdict leakage;
- no two checks repeat the same `(family, argument_index)` for the same recipe.

If a check fails this, drop or rewrite it before returning.

## 4. Deliverable

Return exactly this shape. Do not write any other file.

```json
{
  "checks": [
    {
      "task_family_index": 0,
      "tool_index": 1,
      "family": "unknown_seed",
      "argument_index": null,
      "risk": "An unseen seed must produce a distinct, deterministic initial state. (<=280 chars)"
    },
    {
      "task_family_index": 0,
      "tool_index": 1,
      "family": "argument_variation",
      "argument_index": 2,
      "risk": "Changing a scalar argument must observably change the tool result. (<=280 chars)"
    }
  ]
}
```
