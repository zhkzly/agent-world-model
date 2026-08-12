# Research: cross-layer review — Design semantic closure

- Query: Independent read-only review of plan `7731e2cc06ef54134d3d14d99a75b4c01cda9febb9c7f0dad02da438e6d61f8a` across the current Design-to-Builder/Judge/package/Registry closure.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: block**

- Plan digest: `7731e2cc06ef54134d3d14d99a75b4c01cda9febb9c7f0dad02da438e6d61f8a` (verified against the complete plan)
- Plan revision: first submitted semantic-closure revision
- Scope classification: coordinated cross-node repair
- Revision count: 0 completed revisions; one revised plan may be submitted (at most two revisions in this lineage)

The product target remains: natural-language `EnvironmentRequest` ->
evidence-grounded executable environment -> isolated independent Judge ->
immutable Registry `EnvironmentPackage` -> safe Observe facts. The persisted
diagnosis correctly identifies a static lossy Design consumer gap, not a live
failure: no model retry, code edit, or proof is authorized by this review.

## Findings

### Compatible and allowed parts

- The one ordered group containing all tools when `T > 1` is acceptable as a
  bounded, conservative Direct-v1 coupling policy. It is framework-derived,
  not model-selected, cannot silently omit a potential cross-tool obligation,
  and its over-coupling is honestly limited by the proposed assurance class.
- A statically declared optional `shared_tools` port is a minimal domain
  necessity only for zero derived groups: `tool_semantics.shared_tools` alone
  may bind `()`, no shared Artifact/WorkRecord/model call may be synthesized,
  and every other input port remains nonempty. This must not become a general
  optional-port mechanism.
- The plan keeps the required owners: Designer compiles Design; Builder receives
  Design plus BuildPlan only; CandidateBuild receives no verifier/sealed/Judge
  material; Judge supplies evidence; Controller releases; Registry only
  re-verifies and publishes.

### Blocker 1 — the multi-family/multi-tool Verifier/Integration/Judge consumer is unspecified

The plan replaces singular task/tool state with ordered collections, but does
not define the replacement handoff through `verifier_intent`, private-case
compilation, Integration, and Judge.

The current consumer boundary is singular: `_projection` exports one
`task_requirement` and one local assurance ([agent_world/candidate.py:760-768]);
private verifier cases select one task and `_frozen_step`
([agent_world/candidate.py:1138-1186]); and Integration/Judge execute
`design.public_steps[0]` ([agent_world/candidate.py:924-968],
[agent_world/candidate.py:1200-1235]). The plan says those consumers will
iterate all families/tools, but does not supply their exact inputs, compiled
records, or equality checks.

The revised plan must define one finite framework-owned assurance recipe for
every required `(task-family, tool)` coverage item (or an exact deterministic
coverage selection that still covers every tool), including: valid
materialization input; legal action construction without an Agent choosing a
seed, case, expected result, or release evidence; the full public
`verifier_intent` projection and index validation; private-case record; ordered
Integration/Judge evidence; and package/Registry equality bindings. Reuse the
existing closed RuleDraft/runtime path; do not add a generic test language,
scheduler, or second Judge.

### Blocker 2 — TaskRequirement does not yet name the executable task-rule compiler and Gate path

The plan says framework will “derive” task metadata from public-goal field refs
and initial/success/failure/terminal RuleDrafts, but does not specify the
compiler/validators for `public_goal_schema`, `initial_config_schema`,
`EvaluatorGoalBinding`, reachability policy, RewardSpec, TerminationSpec, and
VerificationRequirements, nor the Judge consumer for those rules.

Those are binding present-slice contracts: the task card requires their
framework compilation ([node-contracts.md:465-490]), and the canonical contract
requires exact public-goal-to-EvaluatorGoal leaf bindings and task reachability
in a real Runtime episode ([docs/agent-world-environment-generation.zh.md:657-709]).
The active handoff requires the Judge to evaluate real state against Rule IR,
EvaluatorGoalBinding, RewardSpec, and TerminationSpec
([node-contracts.md:708-727]).

`builder_required_unverified` may honestly label shared/global/unselected
semantics, but cannot make the success/failure/terminal rules that define a
released task non-executable while claiming every family was materialized. The
revision must name the existing closed evaluator path (or its smallest
task-scoped reuse), require one-to-one required-leaf bindings with no implicit
conversion, map task rules to Rule IR, and define the required
`task_materialization` and `task_reachability` evidence. This is not permission
to add a generic rule engine.

## Required plan precision

- Reconcile prompt and compiler cardinalities: the plan describes ResearchPlan
  as `1..3/0..3/1..6` and Curriculum as `1..4`, while active cards expose
  `1..6/0..6/1..12` and `1..8`. The Prompt and accepted closed output must
  match exactly.
- Define whether an absent shared contract is omitted or `null` in the
  model-visible ToolSemantics projection; that representation must be distinct
  from the empty graph-port binding and participate in the ToolDraft digest.
- Map known divergences, shared clauses, WorldRules, every curriculum family,
  TaskRequirement, and assurance/evidence entries to named world/rule/task/
  fidelity metadata fields plus Registry cold-read equality checks.

## Impact chain and compatibility

```text
Research/citations -> Architecture + coupling plan
-> SharedToolContract? + ToolDrafts + WorldRuleSet
-> ordered Curriculum + TaskRequirements -> EnvironmentDesign
-> BuildPlan/CandidateBuild -> Integration + VerifierIntent
-> Judge -> Package -> Registry cold read -> Observe
-> exact released-package handoff for future Expand/Consumer
```

Designer, Builder, Judge, Controller, and Registry ownership remains compatible
once the two missing current-slice consumer contracts are specified. Expand and
Consumer remain frozen downstream consumers only; no implementation of either
is required by this revision.

## Smallest permitted next work and proofs

1. Revise only the plan to close the two chains above; keep two graphs, current
   node families, one Builder/Judge/Registry, and no new control plane.
2. After a fresh `allow`, add deterministic tests for all ordered family/tool
   projections, private-case secrecy, task binding validation, zero-group port
   behavior, and package/Registry mutation rejection.
3. Only after an allowed whole-diff check, follow the stated live proof order.
   A real terminal failure then begins a new Observe-based diagnosis.

## Non-claims

- This review does not authorize implementation, JSONL/spec/workflow edits,
  model/network calls, Candidate execution, Registry proof, or retries.
- Even a revised deterministic closure does not prove live Direct release,
  real-world fidelity, Repair, Expand Campaign behavior, or Consumer/SFT/RL.
- The all-tool group is not proof that every tool is transactionally coupled or
  that shared concurrency/compensation clauses execute.

## Next permitted gate

Revise `direct-design-semantic-closure-plan.md` only, link this block, recompute
the digest, and submit a fresh independent cross-layer review. Do not dispatch
implementation or real proof while this record is `block`.

## Files found

- `docs/agent-world-environment-generation.zh.md` — canonical Direct, task
  materialization, reachability, and release contracts.
- `docs/direct-rewrite-execution-map.zh.md` — two-graph authority map.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — binding
  Direct/Candidate node and task/evaluator contracts.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-r2-independent-check.md` — prior static consumer-gap evidence.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/minimal-design-semantic-closure-research.md` — proposed typed closure.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-design-semantic-consumer-gap.md` — persisted diagnosis.
- `agent_world/design.py`, `agent_world/candidate.py`, `agent_world/runtime.py`, and `agent_world/graph.py` — current singular consumer and port evidence.

## External references

None. Network/model/live proof calls were prohibited.

## Related specs

- `.trellis/spec/agent_world/backend/index.md` — shared-tool and agent-facing contract guidance.
- `.trellis/spec/guides/foundry-product-alignment.md` — product-target and non-claim discipline.

## Caveats / Not Found

- This is the first review of this digest; no revision response was found.
- No product/test/spec/task-plan/JSONL/workflow file was modified; only this
  required research decision record was written.
