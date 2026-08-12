# Research: cross-layer review — Design semantic closure r2

- Query: Final independent read-only review of revision 2, limited to whether plan `abbab652bfbd389bde56d4c9879948e0c6436faa4eb5ef2a72c8d1f220a3c219` mechanically closes the three predecessor blockers without broadening the Direct slice.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `abbab652bfbd389bde56d4c9879948e0c6436faa4eb5ef2a72c8d1f220a3c219` (SHA-256 recomputed from the complete current plan).
- Plan revision: 2.
- Scope classification: coordinated cross-node repair across Designer, Builder, Judge, Controller package, and Registry.
- Revision count: 2 of at most 2 for the static `diagnosis-design-semantic-consumer-gap.md` lineage.
- Trigger / evidence: the persisted static lossy-Design consumer diagnosis; no relevant real Observe terminal exists or is needed for this plan-only review.

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.
This allow permits only the plan's bounded implementation work; it is neither
a Judge result nor release evidence.

## Findings

### Predecessor blocker closure

1. **Exact package fields, digests, and Registry cold equality — closed.**
   `ExecutableTaskContract` owns canonical `RewardSpec`, `TerminationSpec`,
   and per-family `VerificationRequirements`, with independent canonical JSON
   hashes (`reward_digest`, `termination_digest`, `verification_digest`)
   ([direct-design-semantic-closure-plan.md:161-199](direct-design-semantic-closure-plan.md:161)).
   The plan fixes their physical locations: reward and termination values plus
   digests in `world/rule_ir.json`, and verification requirements plus digest
   in `tasks/materializer_protocol.json`; each is explicitly equal to its
   immutable Design contract ([direct-design-semantic-closure-plan.md:298-316](direct-design-semantic-closure-plan.md:298)).
   Registry must canonical-parse, recompute, and exact-compare every named
   value/digest, rejecting missing, extra, reordered, or changed fields
   ([direct-design-semantic-closure-plan.md:320-326](direct-design-semantic-closure-plan.md:320)).
   This is the smallest repair to the current package shape, whose existing
   metadata and cold reader presently omit those task semantics
   (`agent_world/candidate.py:1887-2009`, `agent_world/candidate.py:2281-2428`).

2. **Public commitment/private case/family-tool recipe binding and Judge
   rejection — closed.**  The plan derives exactly one ordered,
   framework-owned `AssuranceRecipe` for each frozen scoped
   `(task_family_index, tool_index)` pair, with deterministic materialization
   and action templates but no model/candidate choice of seed, expected result,
   witness, or verdict ([direct-design-semantic-closure-plan.md:210-230](direct-design-semantic-closure-plan.md:210)).
   A public commitment carries commitment ID, family/tool indexes, variation,
   and baseline recipe digest. Its same-run `PrivateVerifierCase` repeats
   precisely those bindings before one permitted private variation. Judge must
   reject absent, duplicate, or unequal commitment/family/tool/variation/
   recipe-digest bindings, including a digest not naming the frozen Design
   recipe ([direct-design-semantic-closure-plan.md:236-252](direct-design-semantic-closure-plan.md:236)).
   Private values remain same-run Judge memory, not an Artifact, package,
   CandidateBuild input, or Observe fact. This corrects the present
   case representation, which only binds commitment ID and family
   (`agent_world/runtime.py:60-76`) and the first-only consumer path
   (`agent_world/candidate.py:1138-1186`, `agent_world/candidate.py:1214-1235`).

3. **Deterministic mutation checks and Prompt cardinality disclosure —
   closed.**  The TaskRequirement Prompt and compiler now both disclose the
   exact ordered family shape and `public_goal_fields: 1..12`
   ([direct-design-semantic-closure-plan.md:145-159](direct-design-semantic-closure-plan.md:145)); Curriculum likewise shares its
   stated cardinalities between Prompt and compiler
   ([direct-design-semantic-closure-plan.md:147-151](direct-design-semantic-closure-plan.md:147)).
   The deterministic acceptance list requires Judge rejection of every
   commitment/recipe binding mismatch and cold-read rejection of independent
   mutations to reward, termination, verification requirements, or any of
   their digests ([direct-design-semantic-closure-plan.md:363-385](direct-design-semantic-closure-plan.md:363)).

### Impact chain and owner/consumer compatibility

```text
TaskRequirement source -> ExecutableTaskContract -> EnvironmentDesign
  -> BuildPlan/CandidateBuild (complete Design only; no verifier or sealed input)
  -> Integration (all public baseline recipes, no Verifier dependency)
  -> VerifierIntent public commitment + same-run private case -> Judge
  -> rule/task/protocol/assurance package metadata -> Registry cold read
  -> safe released ref / Observe; later Expand and Consumer consume only that ref
```

Designer remains the sole compiler/owner of the source semantics and
`EnvironmentDesign`; Builder owns candidate construction and verifier-free
Integration; Judge owns isolated recipe/case execution and hard-gate evidence;
Controller remains the sole ReleaseKernel at package; Registry only
re-verifies physical closure and atomically publishes; Observe remains
read-only. The plan explicitly retains this split
([direct-design-semantic-closure-plan.md:270-292](direct-design-semantic-closure-plan.md:270)).

The previously singular consumers are actually within the plan's named
replacement scope: the current Builder projection is one task/local assurance
(`agent_world/candidate.py:760-768`), Integration takes
`design.public_steps[0]` (`agent_world/candidate.py:933-946`), and the
implementation contract rejects any non-singleton public step
(`agent_world/candidate.py:177-191`). The plan correctly replaces those
first-only representations in existing `contracts.py`, `graph.py`,
`design.py`, `candidate.py`, and `runtime.py`, rather than treating package
metadata as a local-only fix.

### Minimality and non-claims

The plan retains the same two fixed graphs and current node families
([direct-design-semantic-closure-plan.md:15-29](direct-design-semantic-closure-plan.md:15)). It confines work to existing production files, forbids a new production
module/dependency and requires removal of obsolete first-only representations
([direct-design-semantic-closure-plan.md:344-361](direct-design-semantic-closure-plan.md:344)). It introduces neither a generic rule/test language nor a
new graph, scheduler, control plane, Repair, Expand, Consumer, second Builder,
second Judge, or Registry authority.

Unproved after this allow: a real Direct release, real-world fidelity,
complete shared concurrency/compensation semantics, execution of unselected or
global rules, Repair, Expand, and Consumer/SFT/RL. Deterministic closure and a
green graph cannot be presented as product completion.

## Smallest permitted implementation and proof gates

1. Implement only the existing-file slices in the approved plan, including the
   exact closed fields, record binding/rejection rule, all-family/tool
   consumers, metadata placement, and cold-read comparisons.
2. Run the listed deterministic tests: field/digest mutations, commitment and
   recipe-binding rejection, all family/tool baseline coverage, private-value
   non-leakage, and Prompt/projection cardinality assertions.
3. Submit the resulting whole diff to the required quality/cross-layer gate.
   Only then may the plan's real proof order run; any real terminal requires
   an Observe read and a new diagnosis before repair.

## Files found

- `AGENTS.md` — repository authority, clean-break, and critic requirements.
- `docs/agent-world-environment-generation.zh.md` — canonical task-materialization, Judge, package, Registry, and secrecy boundaries.
- `docs/direct-rewrite-execution-map.zh.md` — binding two-graph and owner/executor map.
- `.agents/skills/agent-world-cross-layer-critic/SKILL.md` — review decision and record requirements.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — binding task/evaluator, verifier, package, and Registry contracts.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-design-semantic-consumer-gap.md` — static causal diagnosis for this plan lineage.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/cross-layer-review-7731e2cc-design-semantic-closure.md` — original two-blocker review.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/cross-layer-review-53b7b1d5-design-semantic-r1.md` — revision-1 exact remaining blocker and final revision criteria.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-design-semantic-closure-plan.md` — reviewed revision 2 plan.
- `agent_world/candidate.py` and `agent_world/runtime.py` — present first-only, private-case, package, and cold-read consumers that the plan must replace.

## Code patterns

- `agent_world/candidate.py:177-191` — current Builder contract assumes exactly one public step.
- `agent_world/candidate.py:933-946` — current Integration executes only the first public step.
- `agent_world/candidate.py:1138-1186` — current private-case compiler is same-run but lacks the proposed full recipe binding.
- `agent_world/candidate.py:1887-2009` and `agent_world/candidate.py:2281-2428` — current metadata generation and Registry cold read give the precise closure boundary.
- `agent_world/runtime.py:60-76` — private case is already non-persisted, which preserves the plan's secrecy approach without a new subsystem.

## External references

None. Network, model, candidate-process, and live-proof execution were not run.

## Related specs

- `.trellis/spec/agent_world/backend/index.md` — backend and execution-boundary guidance.
- `.trellis/spec/guides/foundry-product-alignment.md` — product alignment and non-claim discipline.

## Caveats / Not Found

- This is a static plan approval only. It does not verify implementation, live model behavior, candidate execution, Registry publication, or release.
- The allow expires if this plan digest, the stated trust boundary, or the relevant real scene changes.
