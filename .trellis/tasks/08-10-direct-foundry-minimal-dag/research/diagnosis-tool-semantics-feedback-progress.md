# Diagnosis — ToolSemantics semantic Feedback and strict progress

- Date: 2026-08-12
- Real terminal: `run_bb8b2474bfd34507b1b73f7856c77ee3`
- Coordinate: `design/tool_semantics[reserve_tool]`
- Safe result: `tool_semantics_invalid`, rejected, not published

## Expected Behavior Sheet

The product goal remains an arbitrary natural-language need -> evidence-backed
executable environment -> independent Judge -> immutable Registry package.
At this boundary, Direct receives one frozen tool projection and one complete
output contract, proposes the complete ToolSemantics object, and framework code
validates it. A rejected uncommitted proposal may receive Feedback as the next
`user` message in the same logical conversation. Feedback keeps the objective,
inputs and output contract unchanged, states the exact safe rejection, asks for
one complete replacement and asks the model to recheck the whole result.

The normal allowance is one correction. The source contract permits one second
correction only when code proves strict A -> B progress at the same validation
frontier. The same issue stops. Format Feedback remains first-attempt-only and
never authorizes a third call.

## Safe Observe facts

The public CLI followed the cleanroom composition root and current DesignGraph;
no forbidden legacy controller or runtime authority appears in the run.

1. ResearchPlan, ResearchAcquire, ResearchSynthesis, WorldArchitecture,
   SharedToolSemantics, `register_member` ToolSemantics and `register_tool`
   ToolSemantics passed.
2. `reserve_tool` attempt 1 used Luna and was rejected at
   `$.postconditions[0].effects[1].value`: the effect value was neither finite
   JSON nor a frozen binding reference.
3. Framework authorized the existing correction and Luna returned a second
   parsed JSON proposal.
4. Attempt 2 no longer reported the first issue. It was rejected at `$.errors`
   because the array did not use the declared cardinality.
5. Both provider calls completed normally with measured usage. There was no
   format, transport, credential, Skill, Candidate, Judge or Registry failure.
6. The run terminated `rejected`; Observe reports one blocking designer-owned
   Finding and `release=not_published`.

The raw proposals were intentionally not persisted. Therefore it is unknown
whether the second issue already existed in attempt 1, and this diagnosis does
not claim that fail-fast validation hid it.

## Time-ordered role-play trace

### Step 1 — initial Direct proposal

- Visible to Luna: the unchanged system role, frozen `reserve_tool` projection,
  complete RuleDraft shape and compact-completeness objective.
- Unavailable: Skills, tools, workspace, graph routing, Judge and release.
- Result: one completed parsed JSON proposal; framework found exact issue A.
- Edge: supported. The producer ran and the validator gave an actionable fact.

### Step 2 — first semantic correction

- Visible to Luna: a fresh system/user request whose JSON body contained a
  `correction` field with issue A.
- Missing from the actual handoff: the rejected proposal as the previous
  ephemeral assistant turn and a separate user Feedback request for a complete
  replacement.
- Result: issue A disappeared and exact issue B appeared.
- Edge: weakened. The safe fact arrived, but not through the project-defined
  same-conversation Feedback shape. The trace does not prove this caused B.

### Step 3 — framework terminal

- Visible to framework: attempt 1 issue A and attempt 2 issue B at the same
  ToolSemantics coordinate.
- Rule actually applied: `NodeSpec.local_corrections` accepts only 0 or 1 and
  `GraphRunner` executes at most two proposals.
- Result: framework correctly rejected invalid output, but could not use the
  source-authorized strict-progress second correction.
- Edge: first directly causal deviation from the expected bounded repair path.

## Five-lens attribution

1. **Project Agent view — supported.** Observe identifies the exact node,
   attempts, operation evidence and terminal Finding without broad legacy reads.
2. **Effective Prompt/input — supported for the first proposal; weakened for
   correction.** The initial output shape discloses both rejected conditions.
   The correction is data in a fresh request, not a next-user Feedback turn.
3. **Direct no-Skill invariant — supported.** Both operations are
   `direct_llm`; no Runtime Skill/tool/workspace surface exists.
4. **Code/execution boundary — weakened.** The graph has no explicit
   ToolSemantics policy or strict issue comparison for a second correction.
5. **Feedback/observability — supported for safe diagnosis, weakened for the
   recipient.** Observe preserves A -> B safely, while the model does not
   receive B because the transaction has already terminated.

## Causal hypothesis and rejected alternatives

The direct terminal cause is the hard two-proposal graph ceiling despite exact
A -> B progress. The coupled protocol defect is that parsed semantic correction
does not use the already-defined user-style Feedback handoff.

Do not loosen the validator or hard-code business semantics. Do not change the
model, route, token settings, Skill, Candidate, Judge or Registry. Do not add
multi-issue aggregation, a Feedback service, a new graph node, generic retries,
fallback chains or workflow Repair. Input size is not established as a cause:
both calls completed without truncation and the disclosed contract named both
conditions.

## Smallest next proof

For the exact immutable `reserve_tool` parents, prove that issue A followed by
different issue B yields one final ToolSemantics Feedback turn, while A -> A,
format failure, transport failure and any fourth call remain blocked. The real
leaf must then either commit within three total proposals or terminate safely.
Only a passing leaf permits another fresh public E2E. Neither deterministic
tests nor the leaf alone prove Candidate, Judge, Registry or product E2E.
