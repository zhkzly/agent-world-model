# Research: cross-layer review d39632e8 complete v1

- Query: Fresh independent cross-layer review of the entire complete-v1 parent
  plan and its embedded Direct child, including shared architecture, every
  child handoff, ordering, authority, minimalism, and the prior C2/C3 reviews;
  this corrects the prior C3 review's narrow review scope only.
- Scope: internal
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`, model `gpt-5.6-terra`

## Decision

Decision: allow

- Parent plan digest: `d39632e88ff13a1b447e490beb379540fe22dcb839690cfdbf6138f114d1efe5`.
- Embedded Direct digest: `dec00ffe10140fb81258182347f658a0370dfdb5155f8344ed8fbc0b8751e372`.
- Plan revision: complete-v1 C3, revision 1 (trusted-wheel ingestion correction);
  Direct R9-C3, revision 1. This is a fresh scope-complete re-review, not a
  plan revision and not a third corrective revision.
- Scope classification: larger coherent product slice. It coordinates the
  parent contract and sequential Direct -> bounded Repair -> Expand -> Consumer
  deliveries across Controller, Designer, Builder, Judge, Registry, and
  Observe. It does not authorize a generic workflow/platform expansion.
- Trigger: the prior parent C3 record reviewed only the wheel-ingestion delta.
  No real proof terminal, Observe scene, Diagnosis Record, or product-code
  failure is being repaired.

This review explicitly authorizes the coordinator to execute the **written
parent sequence** at the exact parent digest above and to dispatch the Direct
child's implementation/check sequence at the exact embedded Direct digest
above, subject to the gates below. It does not collapse the child gates:
Repair, Expand, and Consumer each still require their own fresh matching
critic allow after their exact predecessor commit/contracts are recorded.

## Digest reproduction

The reviewer recomputed the sixteen raw-byte SHA-256 values in the parent
declared order, emitted ordinary newline-terminated `sha256sum` lines, and
SHA-256 hashed their exact concatenation. The result is the stated parent
digest. The component hashes are:

```text
5d54acb103f6752f2543b683201643ca7c5c0b8af802f6fb54ccce74c657a8e2  .trellis/tasks/08-11-foundry-complete-v1/prd.md
2e993c838294a0ceae24a79553caf6c0d5d74e88f097960b1cfab73f09402a9d  .trellis/tasks/08-11-foundry-complete-v1/design.md
906437a5b7eb1f3c2303c3cd536fd66a391b57ffdc3340a21cc43a4cbbb53223  .trellis/tasks/08-11-foundry-complete-v1/implement.md
743b0403360a8732f0554a6cb39379d80745da2e6a319d6dbfc7f45391e90ab7  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
99279bfa4cb038d3fc1db8e8677bdaaabd6d4c3afc6ed115a638ed2397f48121  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
ecf3990c5cca78bd5126ed22794f05f2e036e0c690546f01de3f642622bc11dc  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
ae5de1997f8b8ca72250a8883d9e0d0811c95554fea4e749887a5d16fe3d6bf1  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
95fa444c3e8519df90cac7680a1ce9c256100dd47a84b493462d28d843b57149  .trellis/tasks/08-11-foundry-bounded-repair/prd.md
cbfee29d2392182eb908495e6d23652a508a1c33dea4f2c0cacff3659a1b1af5  .trellis/tasks/08-11-foundry-bounded-repair/design.md
f6445cb6ba97b0e32280f30718f8c28bdc51d4514771cd48418dd007d50aedc1  .trellis/tasks/08-11-foundry-bounded-repair/implement.md
bf10d6b5c7d44a810e97c28499663fc150b1d3abd5f7fec5f30586605a289cca  .trellis/tasks/08-11-foundry-expand-multiparent/prd.md
fc55bb580858493222a21c0482e247faba85095bbbb5cd66a1149ef0dc41cefd  .trellis/tasks/08-11-foundry-expand-multiparent/design.md
d60a0534bb77267248605b4bedf0dcd4525b129e7e047c2d85c87440430dad9f  .trellis/tasks/08-11-foundry-expand-multiparent/implement.md
fbb3b46ca05c31047029e6a1c68e215f2fd7edd47d68bf363c4c7290324d1038  .trellis/tasks/08-11-foundry-consumer-sft-rl/prd.md
f8bd06ed66cfdcd0abf03606ff2573ae10dea51a68966e922b3602b808c6369d  .trellis/tasks/08-11-foundry-consumer-sft-rl/design.md
490d985ed2915430167722c6673ddd11fe84de2ec7686c1439e723d472265cd8  .trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md
```

The Direct five-file aggregate, using its four Direct planning files plus
`docs/direct-rewrite-execution-map.zh.md`, also exactly reproduces
`dec00ffe...e372`. The parent digest deliberately does not include the derived
execution map; the Direct digest does. Any byte change to any listed parent
input or to that execution map expires the applicable allow.

## Product target and reviewed impact chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in a
real isolated boundary, publish an immutable Registry `EnvironmentPackage`,
and expose only safe facts through Observe. Expand must create fresh packages
from real evidence and one or more exact released parents via that same
Design/Build/Judge/Release path. Consumer may turn exact released packages into
isolated public Episodes for SFT/RL without acquiring environment, reward, or
release authority. This is the canonical separation in
`docs/agent-world-environment-generation.zh.md:70-103` and `:117-129`.

```text
EnvironmentRequest
  -> Direct DesignGraph -> CandidateGraph -> Registry package -> Observe
                           | failed Work/Gate
                           v
                     Finding -> deterministic bounded Repair -> graph re-entry

exact released parents + technical evidence
  -> frozen Campaign -> admitted SemanticDelta -> same DesignGraph/CandidateGraph
  -> new Registry package -> Observe

exact released package -> immutable Suite -> current package-use admission
  -> private materialize/reset -> public Episode -> SFT / thin RL -> Observe
```

The parent design makes Direct and Expand alternate inputs to the same two
generation graphs rather than one giant loop, makes Repair deterministic
control around revisions, and keeps Consumer/Observe out of the execution
graph (`design.md:5-31`). It also requires Expand to rebuild a complete Design,
not pass a patch (`design.md:59-72`), and makes Judge wait for exact passed
Integration plus the verifier (`design.md:76-94`). This matches the source of
truth and preserves Direct as the independently required first-package path.

## Shared ABI, owners, and consumer compatibility

The full review finds each shared producer/consumer handoff explicit and
semantically consumable.

1. **Direct seed ABI.** Framework-owned immutable `ArtifactEnvelope` and
   `WorkRecord` carry producer, execution kind, ordered inputs/dependencies,
   outputs, validation/assurance/Findings, and Direct's `invalidated_by=null`.
   A `CANDIDATE_PROCESS` records the untrusted process boundary without
   transferring commit authority. `Finding` is evidence-only and contains no
   target/retry/budget/invalidation/release field. The parent compatibility
   table assigns these facts to the runner/Observe now and Repair/Registry
   later (`design.md:102-169`); the Direct contracts make the same owner matrix
   closed (`node-contracts.md:16-117`). This is sufficient for Repair to use
   provenance rather than stage names.

2. **Direct candidate and package ABI.** Designer framework compiles the
   finite ordered `DifficultySchema`; TaskRequirement consumes its exact digest;
   candidate Materializer only exact-echoes an admitted selection; Integration,
   Judge, package, Registry, Expand's rebuilt Design, and Consumer reuse the
   exact contract. The dedicated producer resolves the prior C2 block without
   a candidate-defined or Consumer-only domain (`node-contracts.md:408-483`,
   `:653-735`). CandidateBuild consumes only Design plus BuildPlan; Verifier
   is a sibling and Judge alone joins it to exact passed Integration. Package
   is the sole ReleaseKernel and Registry only cold-reads/rejects or atomically
   publishes (`node-contracts.md:487-590`, `:707-796`).

3. **Repair.** A framework Finding is re-resolved through its subject envelope,
   producer, owner table and direct dependency closure before any decision.
   Repair appends immutable `RepairDecision` and `WorkInvalidation`, retains
   unrelated Artifacts, caps same-owner and one-hop revision behavior, and
   returns ambiguity/exhaustion/no-progress as an honest non-release. It does
   not add an LLM router, a retry decorator, or scheduler platform
   (`08-11-foundry-bounded-repair/design.md:5-75`). This is compatible with the
   Direct baseline because Direct does not pre-implement the controller; it
   persists the required inert history.

4. **Expand.** `CampaignSnapshot` freezes exact parent/receipt/semantic refs,
   source/profile/policy/operator revisions, direction, seed, and budget.
   Per-use `PackageUseAdmission` reads current Registry status without changing
   frozen snapshot bytes. `CandidateOutcome` keeps infrastructure execution,
   hard-gate, and release statuses separate. `directed@1` has only
   ask/tell/should_stop; Policy selects but cannot merge code, admit evidence,
   or release. A multi-parent child gets semantic projections in Designer and,
   only after Design commit, Builder-only read-only source closures; it remains
   self-contained and gains no inherited verdict (`design.md:174-229`; child
   Expand design: `08-11-foundry-expand-multiparent/design.md:5-119`).

5. **Consumer.** `SuiteSnapshot` contains exact released refs. Before each
   Episode, Consumer revalidates current Registry status and package/receipt;
   it keeps the Suite immutable and records a safe blocked admission if needed.
   The caller cannot provide `initial_config`; framework alone carries the
   Materializer result into the private Runtime reset handoff, computes
   reward/termination, and allowlist-serializes public records. SFT is one
   public trajectory exporter and RL is a reset/step adapter, not a trainer or
   second environment authority (`design.md:231-272`; child Consumer design:
   `08-11-foundry-consumer-sft-rl/design.md:5-106`).

6. **Observe and model assignments.** Observe projects durable safe facts and
   cannot route, retry, judge, mutate, or publish. Runtime remains exactly two
   product routes: prompt-only `direct` and real-SDK/Skill/workspace `agent`;
   Search/Fetch/Extract are research tools. Development workers are separately
   and explicitly pinned to Codex/Terra, so they neither alter the runtime
   route table nor become product authorities (`design.md:274-327`). The
   execution map retains exactly this taxonomy and the four-child order
   (`docs/direct-rewrite-execution-map.zh.md:1-200`).

No unproved consumer is silently treated as compatible: Repair, Expand, and
Consumer plans each require an exact upstream Direct contract/commit and a
fresh local critic before implementation. The plan also requires Product
Alignment Checkpoints at child/proof/release boundaries; these are evidence
records, not another Gate or runtime subsystem.

## Minimalism and plan coherence

The plan is proportionate to the product boundary. It adds two static domain
graphs, one deterministic repair controller, one bounded Campaign with one
policy/two semantic operators, one local Consumer/Episode service, one SFT
exporter, one thin RL adapter, and read-only Observe projections. It expressly
rejects a generic scheduler, dynamic graph/plugin system, arbitrary source
merger, population service, trainer, profile/permission DSL, callback bus,
and compatibility path (`design.md:344-358`; Direct design
`08-10-direct-foundry-minimal-dag/design.md:449-505`).

The complete sequence is also coherent: parent P0 freezes/gates the planning
surface; Direct first freezes/proves the ABI and first Registry package;
Repair consumes that exact provenance; Expand depends on Direct and may use,
but does not require, Repair; Consumer depends on exact Registry/runtime
contracts and final acceptance consumes an Expand package. Every child
requires a commit/digest handoff, deterministic checks, a smallest true-boundary
proof, safe Observe, and an exit Product Alignment Checkpoint
(`08-11-foundry-complete-v1/implement.md:1-183`).

The prior C2 reviews correctly closed the missing difficulty producer/consumer
chain. The prior C3 Direct and parent reviews correctly changed only trusted
wheel ingestion to framework-owned hash/size verification plus a flat
`uv --no-index --find-links` directory. That correction neither changes
Repair's provenance routing, Expand's parent boundary, Consumer's package
admission, package ABI, nor runtime model authority. The present decision is
broader than the old C3 review: it confirms the unchanged shared architecture
and all four child contracts, rather than treating C3 as only a wheel delta.

## Smallest allowed implementation and proof plan

1. Add this allow to the parent implementation/check context together with the
   matching Direct allow `cross-layer-review-dec00ffe-complete-direct.md`; preserve explicit
   `--provider codex --model gpt-5.6-terra` at every worker dispatch.
2. Complete only the written Direct R9-C3 work in the clean worktree: make
   Node transactions real rather than bookkeeping around a monolith; retain
   committed-Artifact-only graph edges; implement the framework-owned exact
   offline wheel boundary; preserve candidate/verifier separation; require
   passed Integration before Judge/Registry; cold-read the complete package;
   and make Observe project the real Work/receipt closure.
3. Run the Direct deterministic suite stated in its plan: schema/owner/
   dependency closure, route/Skill surface, candidate/verifier exclusion,
   strict difficulty behavior, installer hostile/valid wheel cases,
   Integration fail-stop, Registry cold-read, Observe safety, lint/type/compile
   and legacy-reference firewall (`08-10-direct-foundry-minimal-dag/implement.md:273-333`).
4. Run the smallest real Direct proofs in order: exact Direct-LLM contract,
   Codex SDK singleton-Skill preflight, real CandidateBuild plus offline
   Integration of two admitted difficulty selections, then fresh non-fixture
   Direct-to-Registry E2E. Read Observe after every terminal
   (`08-10-direct-foundry-minimal-dag/implement.md:335-357`).
5. Only after the Direct exit handoff names the exact clean commit, contract
   digest, receipt and safe Observe scene may the coordinator request a fresh
   Repair allow. Its proof is one real negative Finding to an authorized fresh
   terminal revision while retaining unrelated Artifacts.
6. Only after the exact Direct handoff may the coordinator request a fresh
   Expand/Campaign allow. The required proofs are a documentation-grounded
   single-parent package, a useful two-parent self-contained package, immutable
   post-freeze blocked admission, and separate infrastructure outcome evidence.
7. Only after the exact Registry/runtime contracts and an Expand package are
   frozen may the coordinator request a fresh Consumer/public-boundary allow.
   Its proof is isolated unknown-seed public Episodes, private reset secrecy,
   one real SFT row, and one online RL Episode; deleting training adapters must
   leave Direct/Expand operational.

## Non-claims and critical caveats

- The inspected implementation is explicitly incomplete: its current graph
  records still wrap concentrated orchestration and it lacks the full Direct
  transaction, package/Registry cold-read, real installer, and independent
  Judge closure. The task's checkpoint audit says not to dispatch final check
  or live proof yet. This is evidence for the need to implement the approved
  plan, not a blocker to the plan itself.
- No live Direct LLM/Agent, research provider, CandidateBuild, wheel install,
  isolated Judge, Registry release, Repair, Campaign, multi-parent child,
  Suite/Episode, SFT row, RL Episode, or final product completion is proved.
- The current authorization expires if an input plan byte, the Direct execution
  map, a shared ABI/authority, or a relevant real scene changes. If P0 performs
  any additional execution-map edit, recompute the Direct digest and obtain a
  fresh Direct review before its implementation dispatch.
- A failed real proof must follow Observe -> debugging -> Diagnosis Record ->
  revised repair plan -> fresh critic -> smallest proof -> Observe. This static
  scope correction supplies no Diagnosis Record and authorizes no retry.

## Next permitted gate

The coordinator may now proceed sequentially under parent digest
`d39632e...1efe5` and Direct digest `dec00ffe...e372`: record these current
allows in the required parent/Direct contexts, dispatch the explicitly
Terra-pinned Direct implementation, then its check/proof sequence. Stop on any
new shared-contract impact or real terminal. Do not dispatch Repair, Expand,
or Consumer implementation/check until its own exact predecessor handoff and
fresh child-specific `allow` exist.

## Files found

- `08-11-foundry-complete-v1/{prd,design,implement}.md` — parent ABI,
  sequencing, model/worker rules, and final acceptance.
- `08-10-direct-foundry-minimal-dag/{prd,design,node-contracts,implement}.md`
  — Direct seed graph, exact package/runtime ABI, and Direct proof plan.
- `08-11-foundry-bounded-repair/*`, `08-11-foundry-expand-multiparent/*`, and
  `08-11-foundry-consumer-sft-rl/*` — child-specific consumers and proof gates.
- `docs/agent-world-environment-generation.zh.md` — canonical product and
  authority contract; `docs/direct-rewrite-execution-map.zh.md` — derived
  execution taxonomy and current child map.
- `research/cross-layer-review-{734a274a,d39632e8,bdb327da}.md` and Direct
  `research/cross-layer-review-{baddd746,ca1c588d,dec00ffe}.md` — prior C2/C3
  decisions and their bounded scope.
- `research/product-alignment-checkpoints.md` and
  `research/direct-checkpoint-implementation-audit.md` — current Direct
  progress/non-claim evidence.

## Caveats / Not Found

- No external reference was required; this is a plan and local-contract review.
- No code, task manifest, source document, prior review, or Registry state was
  edited by this reviewer. Only this required read-only critic record was added.
