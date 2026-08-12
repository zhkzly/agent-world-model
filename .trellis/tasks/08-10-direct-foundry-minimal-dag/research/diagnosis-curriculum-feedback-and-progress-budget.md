# Diagnosis — Curriculum Feedback and strict-progress budget

- Date: 2026-08-12
- Run: `run_fb7f87b4307346b3ae2e6843b27f650a`
- Terminal: `curriculum_plan_invalid`
- Boundary: Direct `gpt-5.6-luna` -> CurriculumPlan compiler

## Expected behavior

The Curriculum node receives the frozen Architecture, WorldRules and citation
catalog, proposes only bounded task-family and difficulty semantics, receives
one actionable next-user Feedback when its uncommitted proposal is locally
correctable, and commits only after strict framework compilation. A distinct
A-to-B validator frontier may use one second correction when code proves
progress; no fourth proposal or release authority is model-owned. Sources:
the canonical environment-generation document, task `design.md`, and
`node-contracts.md`.

## Chronology

1. The public cleanroom route passed Research, Architecture, SharedTools, all
   eight ToolSemantics shards and WorldRules. No legacy authority was loaded.
2. Luna proposal 1 used 12,777 tokens and reached the Curriculum compiler.
3. The compiler rejected `$.families[0].dimensions[0]`: its object fields did
   not exactly match the declared closed shape.
4. Framework appended the safe correction as the next user turn, preserving
   the original input and output contract.
5. Luna proposal 2 used 10,529 tokens. It passed the earlier family-0
   dimension frontier and reached family 6, proving useful A-to-B progress.
6. The compiler rejected `$.families[6]` with the combined condition “family
   id and actor must be frozen valid identifiers.” That diagnostic cannot tell
   the recipient whether to change `task_family_id`, `actor_index`, or both.
7. `curriculum_plan` declares only one local correction, so the second distinct
   semantic issue terminated the Work. No Curriculum Artifact or release was
   committed.

## Five lenses

1. **Project Agent view — supported.** Observe names the exact node, terminal,
   Finding and evidence IDs without broad legacy search.
2. **Effective Prompt/input — supported for the observed rules.** The visible
   output shape declares the exact family/dimension fields, task-family grammar
   and frozen actor-index requirement. Both provider calls completed normally;
   token usage does not support a capacity or truncation diagnosis.
3. **Direct no-Skill invariant — supported.** Operation evidence is
   `direct_llm`, model `gpt-5.6-luna`, `skill_digest=null`; no tool/workspace or
   Runtime Skill participated.
4. **Code/execution boundary — supported until Feedback.** Official-SDK
   transport returned both proposals; strict compiler correctly rejected
   uncommitted source data; Registry remained closed. The current runner's
   second-correction rule is arbitrarily restricted to ToolSemantics even
   though the canonical rule is strict semantic progress, not node identity.
5. **Feedback/observability — weakened at attempt 2.** Attempt 1 Feedback was
   useful and caused observable progress. Attempt 2 combines two independently
   repairable fields at a parent path and is not actionable; moreover it is not
   delivered because the declared correction limit is exhausted.

## Causal hypothesis

The first causal framework deviation is not an SDK, model, Skill, input-size or
node-handoff failure. It is the combination of (a) a validator diagnostic that
merges two field conditions and (b) a runner policy that cannot spend the
already-specified second correction after proven A-to-B semantic progress for
CurriculumPlan. The model's first correction demonstrably worked.

## Smallest coherent repair

- Split task-family ID and actor checks into exact field paths and conditions.
- Declare at most two local corrections for CurriculumPlan and let the existing
  generic runner admit proposal 3 only after a distinct parsed semantic issue;
  format/no-progress failures remain capped at proposal 2 and no proposal 4 is
  possible.
- Keep Prompt, input projection, output contract, graph edges, model route,
  Artifact schema and downstream nodes unchanged.
- Add focused tests for exact diagnostics, A-to-B-to-pass, repeated/no-progress
  stop, format stop and no fourth call.

Do not split the node, add a retry subsystem, increase token limits, switch
models, weaken validation, persist raw proposals, or rerun the public E2E
before the frozen Curriculum boundary passes.

## Smallest proof

Replay only `curriculum_plan` with the exact committed Architecture,
WorldRules and EvidenceGraph parents from this run. Before the change the
second distinct issue terminated. After the change, a precise correction may
reach one third and final proposal; the leaf must either commit or stop safely.
This proves only Curriculum local correction, not TaskRequirement, Candidate,
Judge, Registry or E2E.
