# Diagnosis Record + Repair Plan — TaskRequirement structured-output failure

Date: 2026-08-12
Scope: `repair-plan revision` for a real E2E proof terminal (run_9ab2d5fe14fb4584b86d1c85d96ef744).
North star check: this is a node-local Direct repair; it must NOT break the
`EnvironmentRequest -> ... -> Task/Verifier -> Builder -> Runtime -> Judge -> Registry -> Observe` path.

## 1. Observed failure (ground truth from artifacts)

The first real E2E run passed Research -> Curriculum and failed at the
`task_requirement` node. Five task families were emitted; **4 passed, 1 failed**
(`member_record_consistency`), which rejects the whole run.

`member_record_consistency`, two attempts (`local_corrections=1`):

- **Attempt 1** — top-level object had an extra field. path=`$`,
  condition="object must contain exactly these fields and no others:
  failure_rules, initial_rules, public_goal_fields, success_rules, terminal_rules".
  Feedback was **specific** (listed the 5 fields) -> correction_requested.
- **Attempt 2** — model fixed the top-level field set, then violated
  `$.success_rules[2].effects` array cardinality (length outside 1..6, likely 0).
  Feedback was **abstract** ("array must use the declared cardinality") with no
  numbers. `local_corrections` exhausted -> terminal `failed`.

Control: `register_member_identity` hit `$.initial_rules[0].effects` cardinality
on attempt 1, then **passed on attempt 2** — proving the model CAN self-correct
an effects error when it has budget; `member_record_consistency` simply ran out
of budget after fixing a different error.

## 2. Root cause

1. **Abstract feedback** — `_array`'s `violated_condition` is the literal string
   `"array must use the declared cardinality"`. The model must map "declared
   cardinality" back to the `[1..6]` in the output shape; it did not.
2. **Correction budget too low** — `local_corrections=1` sits on the low side of
   the evidence-based sweet spot. The model fixed error A then introduced error B
   with no attempt left.

## 3. Evidence (fresh 2026-08-12 web research, stored in OpenViking)

- Specific feedback >> abstract: Self-Refine +20% abs, Self-Debugging +12%.
  Best wording = current value + allowed range + field/JSON pointer. Returning
  only "invalid" is a known anti-pattern.
- Correction returns are concave: first 3-4 rounds capture most of the gain
  (round 1 largest, up to +266%; round 4 mostly <=1.9%; 5-7 -> ~0). No observed
  regression, only diminishing returns. -> 3-4 rounds is a robust budget.
- A stale project memory claimed "R9 contract = at most one local revision"; the
  CODE contradicts it: `NodeSpec.__post_init__` permits `local_corrections=2` for
  `direct_llm+direct`, and the sibling node `curriculum_plan` already uses 2.
  Fresh evidence sides with the code; the stale memory should be retired.

## 4. Repair (two minimal, complementary changes)

### Fix A — make `_array` feedback carry real numbers (`agent_world/design.py:179-187`)

```python
def _array(value, minimum, maximum, code, *, path="$"):
    actual = len(value) if isinstance(value, list) else None
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        detail = (
            f"; the rejected value had {actual} items"
            if isinstance(value, list)
            else "; the rejected value was not an array"
        )
        raise DesignError(
            code, path=path,
            violated_condition=f"array must contain between {minimum} and {maximum} items inclusive{detail}",
            expected_category="array",
        )
    return value
```

Effect: attempt 2 on effects now receives "array must contain between 1 and 6
items inclusive; the rejected value had 0 items" — a decidable predicate.
Benefits ALL direct nodes (every rule array). Zero test breakage (the old string
is referenced nowhere outside its own definition; the 3 `expected_category:array`
assertion sites use different, custom conditions).

### Fix B — `task_requirement` `local_corrections` 1 -> 2 (`agent_world/graph.py`, the task_requirement NodeSpec)

One-line change on the existing `NodeSpec("task_requirement", ...)`, adding
`local_corrections=2`. Code-legal for `direct_llm+direct`; consistent with
`curriculum_plan`. Captures one more round of the concave gain.

## 5. Trust boundary / blast radius

- Fix A changes **only the text of a DesignError message string** produced by a
  validator shared by all 6 design direct nodes. No validation LOGIC changes
  (same `_array` reject condition, same `expected_category`). The message is
  consumed by `_direct_feedback` and shown to the model; it is not parsed by any
  downstream code (feedback is rendered as opaque text). Downstream contract
  (`RuleDraft`, `TaskRequirement`, Judge IR) is untouched.
- Fix B changes the retry budget for ONE node within the range the code already
  allows. No new retry platform, no second control plane, no loop unbounded.
- Neither touches model input projection, Artifact ABI, routing, persistence,
  public entry, Judge, Package, Registry, or Observe.

## 6. Non-goals (avoid over-design)

- No full strict JSON Schema now: probe proved luna supports it and reliability
  jumps (99.7% vs 15%), but constrained decoding can degrade reasoning-dense
  output accuracy (DCCD) and our rule IR is reasoning-dense; plus it needs 6
  schemas + backend threading + drift maintenance. Held as a single-node backstop
  ONLY if A+B still fails after a re-run.
- No input slimming now (separate, evidence-supported change; do after A+B).

## 7. Validation plan

1. Unit tests: `uv run pytest` — expect green, zero regressions (message text is
   not asserted; `local_corrections=2` is within `__post_init__` allowed range).
2. Real proof: re-run the same E2E need with luna on localhost:8317; confirm
   `task_requirement` commits and the run advances past it.
3. Read Observe after the terminal, success or failure.

## 8. Rollback

Revert the two edits (one block in `design.py`, one `local_corrections=2` kwarg
in `graph.py`). No schema/migration/data to undo.
