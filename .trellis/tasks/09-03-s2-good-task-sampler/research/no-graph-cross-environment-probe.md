# No-Graph Cross-Environment Sampling Probe

Date: 2026-09-03

## Question

Can one generic execution-first Sampling Agent construct coherent Task drafts
across unrelated `EnvironmentRelease/3` implementations, and is a static Tool
Graph a sound prerequisite?

## Exact inputs

Frozen S1 campaign:

```text
486dd2349f1eccb2f2ee096447a7c2325e811ecd92b6189722a69ed49a09ad7d
```

Selected releases:

| Environment | Release ID | Tools |
|---|---|---:|
| inventory reservation | `a2ec57a9124c4d1f127d1a3b579898dc0278134083e830f11484b49d30da0dae` | 6 |
| support SLA | `86989f98c5d6c9300b12a7660d38a9959742fe5bc18da1885d4c030ee2661f02` | 9 |
| Git release workspace | `6411e0a811fc52d7eb2c613c884f7766ecfdf339e60c19cc0fe75d1244804db7` | 7 |
| laboratory custody | `e31e0882a7cbc7b17fd9eea4fa68f7e49039793edfe10768d94f2a80cd0d2764` | 12 |

All probes opened the real released actor through
`prepare_release_v3_internal`, used fresh temporary instances and invoked only
the public `reset/tools/invoke` interface. Protected state was read separately
only to inspect actual effects.

## Physical execution results

All four environments supported coherent public multi-step flows:

```text
inventory: list-items -> reserve -> inspect-reservation -> release
support:   list-tickets -> assign-ticket -> add-public-note -> resolve -> inspect
Git:       list/read/status/history -> update-release -> commit -> verify
lab:       inspect request/sample/location -> start-test -> record-result -> verify
```

Every listed call returned a schema-valid `ToolObservation` with `ok=true`.

## Static schema-edge counterexample

A deliberately simple candidate Graph joined a tool output to another tool's
required input when leaf field names matched. It produced:

| Environment | Tools | Candidate edges |
|---|---:|---:|
| inventory | 6 | 18 |
| support | 9 | 40 |
| Git | 7 | 4 |
| laboratory | 12 | 26 |

This was neither sound nor complete:

- support `list_tickets -> open_ticket` matched many fields but suggested an
  often decorative duplicate-ticket workflow;
- Git `update_release -> commit` was a real required state dependency with no
  output-to-input value edge and was missed;
- laboratory `sample_id -> inspect_sample(id)` was a real public binding with
  different field names and was missed;
- inventory reserve/release cycles executed but could cancel the meaningful
  business state, so executable adjacency did not imply a coherent Task.

## Live generic Sampling-Agent probes

The existing Responses proposal loop was then used without environment source
changes.

### Git

- model: `gpt-5.6-luna` through the configured local Responses route;
- provider turns: 5;
- public calls: 11;
- result: updated only `CHANGELOG.md` to `v1.1.0`, committed it, verified
  history, release marker and clean status, then emitted a coherent structured
  answer.

### Laboratory

- model: `gpt-5.6-luna` through the configured local Responses route;
- provider turns: 4;
- public calls: 9;
- result: publicly discovered the unique collected sample, a previously
  evidenced receiving custodian and an available receiving location; performed
  `receive_sample`; inspected the sample and custody events; emitted the
  selected IDs and resulting state.

The laboratory probe also exposed an evaluator requirement: when an instruction
does not name a target, the target must be uniquely determined from public
evidence or be a complete ForEach set. The proposal's arbitrary selected ID
cannot become hidden Task truth.

## Full no-Graph S2 simulation

A temporary planning harness then constrained the same real Sampling loop with
a required Goal shape, required focus tools and required outcome. The current
`checker_brief` transport slot was used only to carry temporary structured
TaskDraft JSON; no Checker was authored or executed. For every accepted draft,
the Host:

1. validated objective event references, focus-tool participation, public
   argument provenance and shape-specific sources;
2. replayed the exact public solution from a fresh reset;
3. required equal reset, before state, per-call observations and after state;
4. ran five fresh public solver sessions;
5. conservatively required each solver's canonical final state and structured
   answer to equal the frozen reference result.

Final corrected results:

| Environment | Goal | Sampling turns/calls | Replay | Fresh solvers |
|---|---|---:|---|---|
| inventory | ForEach release initial reservations | 5 / 8 | exact PASS | 5/5 PASS |
| support SLA | If public scalar assignee is null, assign | 5 / 4 | exact PASS | 5/5 PASS |
| Git | All update release + commit | 6 / 12 | exact PASS | 5/5 PASS |
| laboratory | Atom receive unique collected sample | 5 / 8 | exact PASS | 5/5 PASS |

Solver traces were not identical. For example laboratory solvers used 9–11
public calls, yet all reached the same state and answer. This supports outcome
evaluation without sampling-trace equality.

Three deterministic negative drafts were also exercised against the same
temporary validator:

```text
off-target Goal shape                 -> goal_shape_mismatch
collection pointer used as If scalar  -> if_condition_not_scalar
one execution for two ForEach members -> foreach member/coverage failures
```

### Defects found before the corrected runs

- Responses rejected `uniqueItems` in the temporary strict structured-output
  schema. Uniqueness belongs in deterministic Host validation.
- The first ForEach draft omitted mutation steps from its answer-source list.
  Exhaustive answer-source copying is a mechanical Host obligation, not useful
  Agent work.
- A Git draft told the solver to choose any new semantic version but froze the
  proposal's arbitrary `v1.1.0`; public provenance rejected it. Truth-affecting
  free literals must be exact in the instruction or uniquely public.
- One If draft pointed its condition at the whole ticket array. A collection is
  not a scalar condition. After this was made explicit, the next draft used the
  prior public `/data/assignee_id` scalar and passed 5/5.
- ForEach initially checked only that two objective calls existed. The
  corrected contract requires a member-key pointer and a bijection between the
  initial complete set and objective executions.
- The Sampling Agent's rich Git answer schema produced
  `final_answer_invalid` in 5/5 solver runs despite correct environment
  execution. Replacing it in the planning harness with a Host-derived
  type-only schema made the same class of Task pass 5/5. Semantic constants
  belong in evaluator truth, not the public transport schema.
- Running two local 8317 solver requests concurrently produced five
  unattributed request failures; serial execution produced valid semantic
  results. Concurrency is route scheduling, not a five-run semantic property.

### Plan corrections derived from the simulation

- SamplingTarget fields are required obligations. An Agent may return
  unsupported but cannot silently miss the shape, focus tool or outcome.
- TaskDraft carries an AnswerProjection over public sources; Framework resolves
  it and derives the final answer schema. The Agent does not author that schema.
- AnswerProjection copies/assembles public JSON only; it is not a computation
  or free semantic assertion language.
- If requires a prior public scalar. ForEach requires a complete initial
  collection, member-key pointer and exactly one objective execution per key.
- Provider concurrency defaults to the empirically safe route value; all five
  semantic runs remain independent even when executed serially.
- These 20/20 solver passes establish cross-environment feasibility, not final
  corpus diversity or difficulty. Those remain campaign measurements.

## Checkpoint B implementation canaries

The production `sample_task_draft` path was then exercised against two
non-Git releases, with no Checker or Agent-authored answer schema:

| Release | Required target | Result |
|---|---|---|
| support SLA | If / assign_ticket / transition | 4 provider turns; business condition `/data/tickets/1/assignee_id == null`; valid TaskDraft and Host answer schema |
| inventory reservation | ForEach / release / transition | 5 provider turns; complete initial reservation set; two member executions; valid empty-array schema from ToolSpec |

The first support attempt had already completed
`list_tickets -> assign_ticket -> inspect_ticket`, but the terminal repeatedly
used an invented `shape/steps` JSON format because the opaque `goal_json`
contract had not been disclosed. Generic feedback contained only
`DraftGoal has unsupported kind`, so continuation grew from about 24 KB to
78 KB over repeated rewrites and looked like a provider hang.

Single-turn ablations using the same support input showed:

```text
old prompt + old schema  3.63 s
new prompt + old schema  3.44 s
old prompt + new schema  2.74 s
new prompt + new schema  4.26 s
```

The fix was context/feedback ownership, not model or environment changes:
Framework now supplies the exact legal template for the requested shape,
returns rejected output + exact condition + template together, and stops on a
repeated terminal error. It also rejects ToolObservation `/ok` as an If
business condition. The next support attempt emitted the correct business
scalar in one terminal turn.

Checkpoint C1 then ran the new Host materializer and fresh replay:

- support If produced Candidate
  `b800bf22622465b3ee9eb3e189e531656ef081715ab52f9f6da12c053e44f7f5`;
  its condition was public `overdue == true`, all seven argument leaves were
  sourced from reset IDs, and all six evaluator obligations passed;
- inventory ForEach produced Candidate
  `123dec12330e3cc39c69801347da5d623e2fb9e36de6b4b385b289262deb0e00`;
  replay step mutations were
  `[false,false,true,true,false,false]`, so exactly the two member release
  objectives mutated state while discovery/verification calls remained
  non-authoritative.

One independent support attempt was correctly rejected before replay because
its DraftGoal omitted the required focus tool. Sampling rejection did not
trigger an environment, prompt or evaluator repair.

## Decision

- Execution-first generic Agent sampling is physically plausible across
  database, state-machine and filesystem/Git environments.
- A Tool Graph is not authoritative enough to justify its complexity and is
  removed from the production plan.
- Diversity uses simple Goal/tool/outcome counters and semantic structure
  deduplication.
- The Agent owns domain understanding and objective selection; Framework owns
  public dispatch, provenance, state/answer evidence, fresh replay, common
  evaluation and identity.
- These probes are planning evidence only. They are not TaskPacks and do not
  count toward final S2 campaign acceptance.
