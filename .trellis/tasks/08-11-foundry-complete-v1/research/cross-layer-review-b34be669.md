# Cross-layer review — release-public-handoff R1

- Decision: `allow`
- Lineage: `release-public-handoff`
- Plan revision: R1
- Plan digest: `b34be66905d2e1f1690278da03aeddcd1d24191581ff44a6c24619c67462fd69`
- Review model: `gpt-5.6-terra`
- Scope classification: larger slice — coordinated release/public handoffs
  across DesignGraph, CandidateGraph, bounded Repair, ExpandCampaign, Registry,
  Consumer/Episode, and Observe
- Revision count: 1 in this new lineage; predecessor complete-v1 R2 ended at
  `needs_human` and does not authorize implementation
- Trigger: requested architecture-plan review, not a runtime failure. No
  Diagnosis Record or failed Observe scene applies.
- Affected trust boundaries: immutable Registry package identity versus current
  eligibility at Campaign/Episode use; CandidateOutcome execution-versus-quality
  meaning; and the private Materializer-to-Runtime reset handoff.

## Digest reproduction

I independently SHA-256 hashed the raw bytes of the 16 prescribed inputs in
the prescribed order, emitted standard newline-terminated `sha256sum` lines,
and SHA-256 hashed their concatenation. Every line and the aggregate match the
claimed R1 identity:

```text
2f4b2df8b249d3532a38479cb7d40adc8417b5bc358f1b621b83c9faf7c5c973  .trellis/tasks/08-11-foundry-complete-v1/prd.md
9736b6854a0a858826c3d1575e05fac24ec41a14308f7107e301735ac60e12e2  .trellis/tasks/08-11-foundry-complete-v1/design.md
d090e08349444b6a6024b0adde0b653d722ec62b8ed05e4f3e8f630c88303817  .trellis/tasks/08-11-foundry-complete-v1/implement.md
eb375b4b8ecc26964301f449647ddbb78237f98d7be4f4a05ff94b502e6c7932  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
b27f003fdd040b5539a04cbefea4d0792950201cfcf92f52059d227dee01c77e  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
35821202337bf46e8e98bf5eb48a512c1b5d6a1ea80e1c12e26e869133ad983b  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
7145915fd5ad0d828f302c76260e7edebc2846e39163213a460283082842c5c2  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
95fa444c3e8519df90cac7680a1ce9c256100dd47a84b493462d28d843b57149  .trellis/tasks/08-11-foundry-bounded-repair/prd.md
cbfee29d2392182eb908495e6d23652a508a1c33dea4f2c0cacff3659a1b1af5  .trellis/tasks/08-11-foundry-bounded-repair/design.md
d0a5fe43ae96412dded179792cfa0b1b31f9a8932b85b0fd019d84be183d2344  .trellis/tasks/08-11-foundry-bounded-repair/implement.md
d4fe8cd03700d7866e499d8ba1ff0f43cdf66bcdaefbb7816c3361b7e2a22482  .trellis/tasks/08-11-foundry-expand-multiparent/prd.md
77e68fc18e3d5213c0effacbd9938a7a484e6fa2720cf9070f0f4e177ff3d816  .trellis/tasks/08-11-foundry-expand-multiparent/design.md
c3a3e2b99abb817a43bfed0f6deb6b512f4eee4682796e1071980db8243eb082  .trellis/tasks/08-11-foundry-expand-multiparent/implement.md
a0f05fbe7ecfc11c1e5f88f39478d65048b1a0fcd211df05c71f7d641b40c318  .trellis/tasks/08-11-foundry-consumer-sft-rl/prd.md
528d10a7b02b14f63dd8bd307c06a4926dae6da40e5887fdf7009064be789ed5  .trellis/tasks/08-11-foundry-consumer-sft-rl/design.md
3dec3490e627f37b0aae02ec54c8f30516b14cee08289a8a6b81ab302d285067  .trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md
```

Aggregate: `b34be66905d2e1f1690278da03aeddcd1d24191581ff44a6c24619c67462fd69`.

## Product target

Turn an arbitrary natural-language `EnvironmentRequest` into an
evidence-grounded executable environment, independently verify it in a real
isolated boundary, publish an immutable Registry `EnvironmentPackage`, and
expose only safe facts through Observe. Complete v1 additionally requires
bounded repair, evidence-grounded single- and multi-parent evolution, and
removable, public-only SFT/RL consumption of exact released packages. A graph
commit, model JSON, deterministic test, provider preflight, or package-shaped
file is not that product proof.

## Review basis and impact chains

### 1. Registry identity, current eligibility, and immutable snapshots

`EnvironmentPackageRef` remains the exact historical identity: package and
manifest digests, receipt, passed Design/Candidate/Integration/Judge closure,
and separate semantic/implementation lineage. Registry alone emits the ref and
owns the mutable release status. Neither Campaign nor Consumer has an alternate
status store or publication path.

`CampaignSnapshot` and `SuiteSnapshot` retain those exact historical refs and
their frozen policy/selection facts. A framework-owned, append-only
`PackageUseAdmission` is the distinct current-use fact:

```text
exact package ref + exact current Registry record
  -> PackageUseAdmission(admitted|blocked, safe reason, Registry revision)
  -> Campaign parent consumption or Episode startup
  -> safe Observe projection
```

Campaign Policy sees only frozen context and proposes selection; it does not
read current Registry state, write an admission, merge source, or decide a
release. Campaign framework records an admission before each actual selected
parent consumption. This includes the post-Design parent-source materialization
boundary: the task's inherited Expand input/output contract requires the
framework to resolve the exact package again and verify current release status,
receipt, and source-tree digest before giving a read-only root to
CandidateBuild. A blocked admission prevents the affected use before Design or
Build, leaves the snapshot bytes unchanged, and is the honest terminal fact for
Observe; it is not a low-fitness candidate or a second Registry.

Consumer makes the same separation before materialization. It must validate
that the requested exact `package_ref` is a member of the immutable Suite, cold
revalidate package/manifest/receipt, read the current Registry record, append
the episode-purpose admission, and start no Runtime on a blocked result. These
are semantically consumable facts rather than structural package-shaped fields.

### 2. CandidateOutcome remains unambiguous

The split fields have one compatible meaning for Campaign framework, Policy,
Registry, and Observe:

| Execution status | Hard-gate status | Release status | Meaning |
| --- | --- | --- | --- |
| `completed` | factual terminal gate state | `released` or `not_released` | Candidate execution completed; Registry release is independently factual. |
| `infrastructure_error` | last factual state, including `passed` after an earlier gate passed | `not_released` | A non-quality infrastructure terminal with a required evidence ref. |

`hard_gate_status` is never silently rewritten to `failed` merely because a
later infrastructure operation fails. `needs_human` and `budget_exhausted`
remain Campaign `StopDecision`s rather than release values. CandidateGraph and
Registry create the factual outcome inputs; Campaign framework persists them;
`directed@1` excludes infrastructure-error outcomes from candidate-quality
ranking; Policy cannot manufacture a verdict or evidence. The closed decoding
and mandatory infrastructure-evidence checks make an unavailable boundary
distinguishable from both hard-gate failure and non-release.

### 3. Public selection and the private reset chain

The handoff is now one-way and has one framework owner:

```text
public EpisodeRequest(selection only)
  -> exact MaterializerResult validation
  -> private MaterializedEpisodeInput
  -> Runtime.reset(seed, actor, initial_config)
  -> PublicTask / EpisodeStep / EpisodeResult
  -> SFT exporter, RL adapter, safe Observe
```

The caller cannot supply `initial_config`. `MaterializedEpisodeInput` binds the
Episode request and exact Materializer result, keeps `initial_config` and
EvaluatorGoal private, and is not a public Artifact/serialization surface.
Consumer, not Runtime, Materializer, SFT, or RL, owns the materialization
handoff and framework-owned reward/termination computation. Candidate Runtime
remains untrusted and isolated. The public serializers, SFT exporter, RL
adapter, logs, and Observe receive only the documented public fields, avoiding
a duplicate state or reward authority.

### 4. Frozen Direct/Repair compatibility

The Direct child already plans the parent ABI without dormant later control
behavior:

- `WorkRecord` has closed execution kinds, exact ordered input and causal
  dependency refs, framework validation/assurance/Finding refs, and immutable
  `invalidated_by=null`; `CANDIDATE_PROCESS` does not transfer commit authority.
- A route-free framework `Finding` retains failed claim, subject, nonempty
  evidence, expected condition, framework-derived owner, blocking effect, and
  fingerprint while excluding targets, retry, budget, invalidation, jump, and
  release actions.
- Registry emits the released `EnvironmentPackageRef` only after cold-reading
  the exact passed closure and receipt; package bytes do not contain the
  post-publication receipt.

Repair consumes and re-verifies those fields from immutable provenance, then
appends `RepairDecision` and `WorkInvalidation` rather than rewriting Direct
history. Its dependency closure and bounded re-entry remain compatible with
CandidateGraph, Registry, and Observe. Thus the current lineage does not
retrofit a new owner, Artifact authority, or compatibility path into Direct or
Repair.

## Smallest allowed implementation and proof plan

The coherent scope remains the existing two static graphs, one deterministic
RepairController, one `directed@1` Campaign, the minimum ToolSurface/Composite
operators, one framework Consumer/Episode service, one SFT exporter, one thin
RL adapter, and read-only Observe. It must not add a runtime Critic, second
Judge/Registry/ReleaseKernel, generic scheduler, policy platform, source merger,
trainer, profile system, or legacy compatibility route.

Smallest deterministic regressions, kept distinct from real proof, are:

1. Round-trip/cold-read Direct `WorkRecord`, route-free `Finding`, and
   `EnvironmentPackageRef`; reject reordered causal refs, model authority,
   invalidator mutation, mismatched receipt/package/manifest/closure, and
   candidate-process commit transfer.
2. Freeze/restart a Campaign and a Suite; mutate Registry status after freeze;
   prove historical snapshot bytes and frozen Policy inputs are unchanged while
   an admitted-use check appends a blocked fact and reaches neither parent
   semantic/source consumption nor Episode materialization/Runtime startup.
3. Exercise the outcome truth table, including an infrastructure terminal after
   an earlier passed hard gate; require exact infrastructure evidence, retain
   the passed gate fact, set `not_released`, and prove `directed@1` cannot score
   it as failed or low-quality.
4. Reject an Episode package outside the Suite, a caller `initial_config`, and
   private canaries in every public API, SFT row, RL reset/step input, log, and
   Observe scene. Verify that only Consumer computes reward/termination.
5. Preserve no-feedback Campaign release semantics and prove that removing
   training adapters leaves Direct/Expand entry points and tests unaffected.

The true-boundary proof order remains:

1. A fresh non-fixture Direct request using real research and model/Agent
   invocation, isolated candidate execution, passed Integration, independent
   Judge, Registry publication, and safe Observe; a required unavailable
   backend must fail closed.
2. A separate real negative-to-repaired lineage with a genuine Finding, bounded
   revision, retained unrelated Artifacts, a fresh verdict, and Observe at both
   terminals.
3. A documentation-grounded single-parent Campaign through the shared graphs,
   with non-empty framework-computed semantic delta and fresh release result.
4. A useful real two-parent child with two exact released parents, one proven
   capability from each, an unknown-seed integrated task, a self-contained
   source closure, fresh Integration/Judge/Registry evidence, and no inherited
   verdict.
5. An exact released Expand package in an isolated unknown-seed Episode, one
   leak-free SFT export, and one online RL reset/step completion through the
   same public protocol.

## Compatibility facts, non-claims, and next gate

This allow is planning authorization only. It does not prove a Direct package,
repair result, Campaign, parent admission implementation, multi-parent
behavior, Episode, SFT row, RL result, model reliability, broad diversity, or
training improvement. No graph test or model response may be reported as the
natural-language-need-to-Registry-package product outcome.

The allow expires if any of the 16 input bytes, these release/public trust
boundaries, or a relevant real Observe scene changes.

Next permitted gate: perform only P0's minimal development-document
calibration—generalize the development critic Skill to complete-v1 scope and
synchronize the derived execution map without changing their taxonomy or
creating a runtime authority—then verify that bounded change. Before any child
implementation or checking dispatch, the main planner must place this current
allow in that child's `implement.jsonl` and `check.jsonl`, obtain the required
fresh child-specific critic allow against the exact upstream commit/contracts,
and retain Product Alignment Checkpoints at the prescribed child/proof/release
boundaries.
