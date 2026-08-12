# Agent World Foundry complete v1 — execution plan

## Parent role

This parent owns contract convergence, the task map and final integration
acceptance. It is never started as a product-code task. Start and finish one
child at a time in the order below.

## P0 — planning and development-gate calibration

1. Freeze this parent PRD/design and the four child plans.
2. Derive one digest from the complete parent/child planning revision and run a
   fresh independent review with the current critic Skill. Its stale
   Direct-only clauses are part of the affected development boundary, not an
   excuse to bypass the gate.
3. Only after that review returns `allow`, minimally generalize
   `agent-world-cross-layer-critic` so its product target covers Direct,
   Repair, Expand, Consumer and Observe and its review questions are
   scope-aware. Do not turn it into a runtime component or new framework.
4. Minimally update `docs/direct-rewrite-execution-map.zh.md` after critic
   allow so its execution taxonomy remains useful but its stale Direct-only
   implementation exclusions no longer contradict this task tree.
5. Verify both documentation changes against the approved plan. Any broader
   semantic change requires a fresh plan digest and critic review.
6. Make the approved task artifacts available in the clean implementation
   worktree before dispatch; do not rely on a subagent inheriting this root
   session or reading uncommitted files from another worktree.
7. Keep independent worker model selection explicit at dispatch time. Do not
   rely on inherited main-session model defaults.
8. If the review in step 2 is blocked, revise planning artifacts only and
   resubmit at most twice. No
   product implementation begins without an `allow` for the exact parent plan
   digest.

## Reproducible plan digest and current lineage

The first complete-v1 lineage ended at R2 with `needs_human` in
`research/cross-layer-review-42ac2771.md`. On 2026-08-11 the user confirmed its
three coordinated release/public-surface decisions. Dispatch amendment R3 was
then allowed at digest `bdb327...`. The current revision C5 preserves those
contracts, explicit Terra dispatch and the C2 shared difficulty closure while
adding the tested framework-only Direct dependency installation corrections
through C3-C5. Those corrections change no parent Artifact/package/runtime ABI
or later-child authority:

| Confirmed policy | Current-lineage owning plan changes |
| --- | --- |
| Frozen identity versus current eligibility | Parent `PackageUseAdmission`; Expand parent-use admission; Consumer new-Episode admission. Quarantine/supersession blocks use without mutating Campaign/Suite bytes. |
| Infrastructure is not candidate quality | Parent/Expand `CandidateOutcome.execution_status` plus mandatory infrastructure evidence; Campaign stop and release status remain separate. |
| Public selection versus private reset | Parent/Consumer public `EpisodeRequest` drops `initial_config`; private `MaterializedEpisodeInput` binds exact Materializer output to Runtime reset. |
| One difficulty authority | Curriculum proposes ordered finite dimensions/levels; framework compiles the schema; TaskRequirement, Materializer, Judge, package, Expand and Consumer reuse it. |

Repair, Expand and Consumer contracts remain unchanged. The current Direct
installer compiles one finite admitted lock closure and runs fixed uv commands
outside candidate source; later children gain no installer role. This adds no
node, Registry, Judge, graph, scheduler or public API layer.

The parent review digest excludes review records and manifests. It is derived
from these raw UTF-8 file bytes in exactly this order:

```text
.trellis/tasks/08-11-foundry-complete-v1/prd.md
.trellis/tasks/08-11-foundry-complete-v1/design.md
.trellis/tasks/08-11-foundry-complete-v1/implement.md
.trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
.trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
.trellis/tasks/08-11-foundry-bounded-repair/prd.md
.trellis/tasks/08-11-foundry-bounded-repair/design.md
.trellis/tasks/08-11-foundry-bounded-repair/implement.md
.trellis/tasks/08-11-foundry-expand-multiparent/prd.md
.trellis/tasks/08-11-foundry-expand-multiparent/design.md
.trellis/tasks/08-11-foundry-expand-multiparent/implement.md
.trellis/tasks/08-11-foundry-consumer-sft-rl/prd.md
.trellis/tasks/08-11-foundry-consumer-sft-rl/design.md
.trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md
```

For each file, compute lowercase SHA-256 of raw bytes and emit the standard
`sha256sum` line `<digest><two spaces><repo-relative path>\n`; SHA-256 the
concatenation of those 16 lines. The resulting current-lineage digest and file
hashes are stored in the latest `research/plan-digest-*.md`, which is not itself
an input. Any byte change to an input requires a new digest and expires its
review. Earlier digests/reviews remain immutable history and authorize no
implementation.

## P1 — child 1: Direct graph foundation

Task: `08-10-direct-foundry-minimal-dag`.

1. Update the child to bind this parent contract and remove the expired
   Direct-only critic authorization from dispatch manifests.
2. Implement the parent compatibility table exactly in the Direct contracts:
   execution kind/dependencies/invalidation baseline, route-free owned Finding,
   released `EnvironmentPackageRef`, and the one framework-compiled difficulty
   schema reused by TaskRequirement/Materializer/Judge/package/Consumer. Do not
   add later control behavior.
3. Obtain a fresh child-specific independent critic allow.
4. Implement only the two static graphs and required Direct behavior in the
   clean worktree, replacing equivalent monolithic orchestration.
5. Run deterministic checks, real Agent preflight and one fresh Direct release.
6. Check with an explicitly model-pinned Trellis check worker; append Product
   Alignment Checkpoints and freeze the exact output commit for dependants.

## P1A — Direct C6 contract closure

The first full Direct implementation review blocked before live proofs. The
exact feedback and smallest correction plan are
`../08-10-direct-foundry-minimal-dag/research/direct-c5-check-block.md` and
`../08-10-direct-foundry-minimal-dag/research/direct-c6-contract-closure-plan.md`.
P1 remains incomplete until Direct enforces its fixed graph ports/edges,
bounded local correction, self-sufficient Builder protocol, executable private
Verifier cases, evidence-derived telemetry, package/SBOM/Registry closure and
secret-free candidate process boundary, then passes a new independent check
and all four real proofs.

These corrections strengthen the existing shared Artifact/Work,
EnvironmentPackageRef, Runtime/Materializer and Registry handoffs; they add no
Repair, Campaign, Consumer, third graph or alternate release route. P2-P5 stay
ordered and blocked on the exact completed Direct C6 commit.

## P1B — Direct C7 exact-boundary closure

The independent C6 recheck blocks only two unfinished parts of the same Direct
contract. The child must implement
`../08-10-direct-foundry-minimal-dag/research/direct-c7-final-contract-plan.md`:
exact local correction delivery for declared model/Agent nodes and exact closed
responses for the existing five-operation Runtime. This is not a new feedback
system, protocol framework or child feature. P2-P5 remain unchanged and wait
for the exact completed Direct C7 commit and real proof handoff.

## P1C — Direct C8 exact provenance closure

The independent C7 check leaves one static graph-contract defect. Child 1 must
implement
`../08-10-direct-foundry-minimal-dag/research/direct-c8-port-provenance-plan.md`:
commit and validate exact source ports and bind every Artifact actually consumed
by the five named Direct boundaries. This is provenance closure only; it adds no
node, graph, scheduler, Repair, Expand, Consumer or release behavior. P2-P5
remain unchanged and wait for the exact completed Direct C8 commit plus real
proof handoff.

## P2 — child 2: bounded repair

Task: `08-11-foundry-bounded-repair`.

1. Verify the exact completed Direct commit and contract digests.
2. Close `RepairDecision`, budget, invalidation and Observe revision schemas.
3. Obtain a fresh repair-scope critic allow.
4. Implement deterministic routing and bounded graph re-entry without an LLM
   Router or scheduler platform.
5. Prove one real negative CandidateBuild/Integration/Judge Finding reaches a
   corrected revision while retaining unrelated Artifacts.
6. Freeze the repair commit and evidence; do not require every normal success
   run to manufacture a failure.

## P3 — child 3: Expand and multi-parent

Task: `08-11-foundry-expand-multiparent`.

1. Verify the Direct contract/commit; record whether the optional Repair child
   is present without making Campaign semantics depend on repair.
2. Close Campaign, source, intent, semantic delta, parent closure, policy
   checkpoint, package-use admission, execution/hard-gate/release outcome and
   lineage schemas plus Node cards.
3. Obtain a fresh Campaign/Release-boundary critic allow.
4. Implement one `directed@1` policy, bounded source research and only the
   semantic operators needed by the accepted proofs.
5. Prove a post-freeze quarantine/supersession leaves snapshot bytes unchanged,
   records a blocked admission before Design/Build, and that infrastructure
   error is evidenced without entering candidate-quality scoring.
6. Run one real single-parent Campaign to a fresh package.
7. Run one real useful multi-parent Campaign using two exact released parents;
   prove one capability from each plus an integrated task, full isolation and a
   fresh verdict.
8. Check Campaign Observe and freeze exact package/commit refs for Consumer.

## P4 — child 4: Consumer, SFT and RL

Task: `08-11-foundry-consumer-sft-rl`.

1. Verify exact Registry/package/Runtime contract digests and select an exact
   released Expand package for final acceptance.
2. Close Suite, PublicTask, Episode, public trajectory, SFT row and RL adapter
   schemas, current package-use admission and private Materializer-to-Runtime
   handoff plus secrecy checks. `EpisodeRequest` must consume the selected
   package's exact difficulty schema rather than define another one.
3. Obtain a fresh Consumer/public-boundary critic allow.
4. Implement the framework-owned Consumer/Episode service, one SFT exporter and
   one thin online RL adapter; do not add a trainer.
5. Prove a caller cannot supply `initial_config`; post-freeze quarantine or
   supersession leaves Suite bytes unchanged and blocks a new Episode with a
   safe admission fact.
6. Prove unknown-seed isolated Episodes, one leak-free SFT trajectory and one
   online RL Episode through the same public protocol.
7. Prove deleting training adapters does not affect Direct/Expand and deleting
   optional capability feedback does not affect Campaign release semantics.

## P5 — parent integration acceptance

1. Assemble an immutable evidence dossier linking:
   - a real Direct package;
   - one bounded repair lineage;
   - a documentation-grounded single-parent child;
   - a useful real multi-parent child;
   - one Suite/Episode, SFT row and online RL result;
   - safe Observe scenes and exact Registry receipts.
2. Run repository lint, type checking, deterministic tests, package-relative
   execution, offline installation checks, secret scan and legacy-reference
   firewall in the clean worktree.
3. Run an independent final cross-child review. It verifies exact child commits
   and contracts; it does not reroute or rewrite the implementation.
4. Publish only if all parent acceptance criteria are evidenced. Otherwise
   record the failing child boundary and return to that child's
   Observe -> diagnosis -> plan -> critic flow.

## Dispatch rules

- Every dispatch starts with `Active task: <exact child path>` and injects only
  that child's curated manifest plus parent source requirements.
- Critic: fresh `trellis-research`, read-only, `--provider codex --model
  gpt-5.6-terra`.
- Implement: explicit `--provider codex --model gpt-5.6-terra`.
- Check: explicit `--provider codex --model gpt-5.6-terra`.
- Failure diagnosis or further read-only research: explicit
  `--provider codex --model gpt-5.6-terra`; there is no ambient inheritance or
  hidden development-worker fallback.
- Each child maintains independent `implement.jsonl` and `check.jsonl` entries,
  including the current exact-digest critic allow before dispatch.

## Global stop conditions

- Stop before code if a shared contract is incomplete, parent/child digest is
  stale, critic is not `allow`, or the clean worktree is dirty from unrelated
  changes.
- Stop before dispatch if any parent/child development-worker instruction
  omits explicit Codex `gpt-5.6-terra` or if this development-only change also
  changes the runtime product route table.
- Stop a real run on missing credentials, permission/risk ambiguity, exhausted
  budget or unavailable required backend; do not fabricate a success route.
- Any newly discovered producer/consumer impact requires a plan revision and
  fresh critic before implementation continues.
