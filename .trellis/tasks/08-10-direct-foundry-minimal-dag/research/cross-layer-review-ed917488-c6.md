# Research: independent cross-layer review — Direct R9-C6 contract closure

- Query: Review the R9-C6 Direct contract-closure plan before implementation against the canonical natural-language-need to Registry package path and its Repair, Expand, and Consumer handoffs.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `ed917488dc2ba845c7577a4bf7770c66ff4691a6412650fa2af8a55a9e8fe570`.
- Parent aggregate: `6e3d4c9cebc4836ce7a872cce11e7fe687e1d3d6154d0ce77460371811186f0e`.
- Plan revision: Direct R9-C6, “minimal executable contract closure”.
- Scope classification: coordinated cross-node Direct slice. It crosses the
  fixed graph runner, Designer/Builder/Judge/Controller/Registry boundaries,
  candidate-process boundary, package closure, and Observe. It does not alter
  the later Repair, Expand, or Consumer runtime paths.
- Revision count: first plan revision after the C5 whole-diff block; one
  further revision remains available only if this exact plan later receives a
  new blocking review. This allow expires if its digest, changed trust boundary,
  or relevant real execution scene changes.

I independently recomputed the two aggregates by hashing the exact
newline-terminated SHA-256 listing recorded in the two C6 digest files. Both
match the stated values above.

## Product target and trigger

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in a
real isolated boundary, publish an immutable Registry
`EnvironmentPackage`, and expose only safe durable facts through Observe.

The trigger is the independent static C5 whole-diff block, not a real proof
terminal. The blocker records that deterministic tests and static gates passed
but no real provider proof started; therefore no fictional Observe scene or
Diagnosis Record is required for this pre-implementation C6 review. PAC-22
correctly keeps C6 at the plan/critic gate.

## Findings

### Resolution audit and impact chain

| C5 boundary | C6 resolution and owner | Consumer compatibility / required proof |
| --- | --- | --- |
| Declared edges were not enforced | `GraphRunner` replaces the bare positional input tuple with an exact named-port binding, cold-reads every source envelope, and verifies each producer against the literal `EdgeSpec`; framework remains the only graph/Artifact owner. | Existing two literal graphs remain sufficient. Prove missing, wrong-source, missing-port, extra-port, multi-shard, and legitimate external-port cases; persist the deterministic flattened dependency order in both envelope and WorkRecord. |
| `local_corrections` was declarative | One framework-built `CorrectionPacket` can trigger one new physical model/Agent invocation only after a model-output compiler or semantic-validator failure; provider, framework, candidate, Integration, Judge, package, and Registry failures are excluded. | The frozen semantic projection, node owner, Prompt/Skill, and route remain unchanged; attempts are persisted and the second failure terminates. This is a local output correction, not Repair routing or an invocation retry multiplier. |
| CandidateBuild lacked the exact process contract | Builder compiles one frozen `implementation-contract.json` covering required files/limits, Materializer JSONL request plus ordered result fields, every Runtime operation request/result, idempotency, tool/result obligations, difficulty echo, dependency policy, and shutdown. | CandidateBuild receives only Design, this contract, and BuildPlan. It neither receives verifier/Judge/release data nor ambient repository knowledge. This supplies the same Materializer/Runtime protocol later used by Consumer without implementing Consumer. |
| Verifier intent was free text and replayed a public step | Challenger emits only closed public intent over four executable families; framework assigns commitments and private seed/key/value data; Judge executes every resulting case in fresh candidate processes. | The package and Observe retain public commitments/counts, never seeds, mutations, expected corpus, evaluator state, or verdict authority. Baseline exact claims remain exact; variation checks are framework-owned response/type/idempotency/restart/state checks. This is a sufficient bounded R9 subset, not a training verifier language. |
| Telemetry was invented | Framework commits secret-safe real Direct/Agent and research-acquisition operation-evidence Artifacts. Package derives `TelemetryReleaseSummary` only from those committed WorkRecord-assurance bindings and preserves unavailable usage as `unknown`. | This is evidence closure, not a telemetry platform. Registry and Observe can cold-read only attested categories; neither obtains route, Prompt, credential, or private operation content. |
| Dependency/package/Registry closure was physical only in name | Integration commits the admitted lock closure; Judge re-admits it; Package writes canonical typed closure, real SBOM, and cycle-free metadata; Registry canonical-parses, rehashes, recompiles lock/SBOM/difficulty, rejects missing or extra entries, then atomically publishes. | Direct continues to emit the one exact `EnvironmentPackageRef` with Design/Candidate/passed Integration/Judge and separate semantic/implementation lineage. This is the exact ref needed for later parent admission and Suite/Episode admission. |
| Candidate processes inherited ambient state and scanner skipped hidden entries | Candidate source rejects hidden paths, symlinks, devices, and unmanifested entries. Materializer/Runtime receive an explicit minimal environment and the existing absolute fresh-venv interpreter, fixed cwd, JSONL I/O, timeout, and teardown. | This is targeted containment; it adds no configurable sandbox, permission, capability, or profile system. It preserves package-relative execution needed by future Consumer. |

The plan therefore advances the whole Direct chain:

```text
EnvironmentRequest -> DesignGraph -> exact Builder protocol -> isolated Candidate
-> passed Integration + sealed independent Judge evidence -> cycle-free package
-> Registry cold-read/publication -> safe Observe
```

It leaves the later chains intact: Repair still consumes route-free Findings and
immutable dependency provenance; Expand still supplies a completed Design and
earns fresh CandidateGraph/Judge/Registry evidence; Consumer still accepts only
the released exact package ref and keeps Materializer-to-Runtime private state
outside its public Episode API.

### Owner and contract compatibility

- The plan keeps one framework owner for port validation, correction admission,
  private-case compilation, operation evidence, dependency admission, package
  compilation, Registry re-verification, and Observe projection. It creates no
  runtime Critic, second Judge, ReleaseKernel, scheduler, or graph framework.
- CandidateBuild stays separated from the verifier branch. The existing graph
  declaration already makes `candidate_build` consume only `design` and
  `build_plan`, while Judge consumes the verifier after passed Integration
  (`agent_world/graph.py:251-295`, `319-327`). C6 preserves that shape.
- The shared released-package handoff is already structurally closed as
  `EnvironmentPackageRef` with package/manifest digests, receipt, exact
  Design/Candidate/passed Integration/Judge, and separate lineage refs
  (`agent_world/contracts.py:249-273`). C6's package/Registry work completes
  its physical and cold-read semantics instead of adding a second reference.
- Future Repair is not pre-implemented: current Findings remain route-free and
  C6 adds only node-local output correction. Future Expand still reuses the two
  fixed graphs; future Consumer receives no source, verifier, sealed case,
  evaluator goal, or `initial_config` through the Direct change.

### Plan-quality conclusions

1. Explicit port bindings are the smallest enforcement mechanism. They make
   each literal edge a checked producer-to-target-port fact and keep the runner
   deterministic; they do not add dynamic scheduling, registration, callback,
   or graph inheritance behavior.
2. The one local correction is bounded by failure class, attempt count, frozen
   projection, same owner/Prompt/Skill, and persisted physical attempts. It
   cannot become an implicit provider retry or a Repair budget.
3. The Builder protocol is complete at the necessary boundary: the candidate is
   given the exact executable process ABI rather than inferred framework source
   knowledge. The plan correctly leaves installation/admission/hash/release
   authority framework-owned.
4. The four-family verifier subset is executable and independent for minimal
   R9 because the framework, not the Challenger, determines all private values
   and the Judge actually runs every compiled case in fresh processes. It is
   intentionally not claimed to be a general solver, full verifier DSL, or
   future Consumer training mechanism.
5. Operation evidence is sufficient to support only the claimed telemetry
   categories without a separate observability product; `unknown` prevents
   false zero-usage claims.
6. Re-admitted lock closure, typed/canonical package files, physical entry
   equality, SBOM/difficulty recompilation, and Registry cross-checks close the
   supply/package path without receipt hash cycles.
7. The explicit subprocess environment and strict source-tree closure are a
   sufficient minimum hardening measure for this slice. They do not promise OS
   sandboxing or invent a permission system.
8. No later-child logic leaks into Direct. The plan strengthens the frozen
   package/ref/difficulty/runtime seams that later children explicitly depend
   on, while preserving their separate authority and proof obligations.

## Files found

- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-c5-check-block.md` — prior independent static block and its seven concrete gaps.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-c6-contract-closure-plan.md` — reviewed C6 correction scope, implementation surface, and proof order.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/plan-digest-r9-c6-contract-closure.md` — seven-file Direct identity and first-revision lineage.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/product-alignment-checkpoints.md` — PAC-22 preserves the no-real-proof and Direct-only non-claims.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,implement,node-contracts}.md` — Direct product target, two-graph boundaries, frozen contracts, C6 gate, and package/runtime handoffs.
- `.trellis/tasks/08-11-foundry-complete-v1/{prd,design,implement}.md` and `research/plan-digest-contract-closure-c6.md` — parent target, shared ABI owners, child ordering, and eighteen-file identity.
- `.trellis/tasks/08-11-foundry-{bounded-repair,expand-multiparent,consumer-sft-rl}/implement.md` — later child proof plans; their PRD/design files confirm the repaired, campaign, and public/private downstream seams.
- `agent_world/{graph,contracts,candidate,runtime,supply_chain,observe}.py` — current C5 implementation that C6 must close without changing product scope.

## Code patterns

- `agent_world/graph.py:70-76,334-443` — literal `EdgeSpec` declarations exist, but `execute` currently accepts unbound positional refs; C6 correctly targets this actual bypass.
- `agent_world/graph.py:455-516` — a node currently makes one attempt then commits/fails; C6 can add one explicit correction branch here rather than a global retry mechanism.
- `agent_world/candidate.py:315-356` — CandidateBuild already creates only Design/implementation-contract/BuildPlan inputs and deletes them before scanning; C6 needs to make the contract complete, not broaden exposure.
- `agent_world/candidate.py:445-510` and `agent_world/runtime.py:343-375` — current free-text risk cases include seed and public step in stored bundle; C6 must replace this with public commitments plus same-run private executable cases.
- `agent_world/candidate.py:615-657,839-889,981-1008` — current telemetry/SBOM/envpkg/Registry closure is demonstrably incomplete, matching the C5 block; C6's physical reparse and typed closure are necessary.
- `agent_world/supply_chain.py:52-91,297-343,372-447` — framework already has finite admitted wheel closure and scrubbed install environment, so exposing/committing the closure is a small extension rather than a new supply-chain platform.
- `agent_world/runtime.py:84-215` — candidate modules are already out-of-process JSONL children; passing an explicit minimal environment and rejecting ambient source entries tightens this existing boundary.
- `agent_world/contracts.py:249-273,434-450` — the released ref has the needed downstream fields, whereas current verifier case persistence is precisely the privacy boundary C6 closes.

## Smallest required checks and proof

Before any live run, retain all C5 checks and add deterministic hostile tests
for the following exact C6 obligations:

1. exact port-set binding, wrong/missing/extra port rejection, source-envelope
   provenance, a permitted external input, and deterministic multi-shard order;
2. one and only one eligible correction with a safe packet and two persisted
   attempt facts; no correction for provider/framework/candidate/Integration/
   Judge/Package/Registry terminals;
3. exact Builder-visible Materializer/Runtime protocol, no ambient source or
   verifier/Judge/release exposure, and both stdlib plus admitted trusted-wheel
   dependency behavior;
4. compiler and Judge coverage for each of the four verifier families,
   fresh-process execution of every emitted case, and absence of concrete
   seed/key/mutation/expected values from Artifacts, candidate inputs, package,
   and Observe;
5. evidence-derived telemetry with `unknown` preserved; nonempty SBOM;
   metadata/source/extra-entry tamper rejection by Registry and Observe;
6. hidden/symlink/device/unmanifested source rejection and a clean
   Materializer/Runtime child environment.

Only after deterministic checks and an independent whole-diff check may the
ordered true-boundary proof begin: one Direct node, one singleton-Skill SDK
Agent, real CandidateBuild plus stdlib and trusted-wheel Integration cases, and
one fresh natural-language Direct E2E through Registry cold-read and Observe.
Every real terminal requires Observe; a failure begins the separate
diagnosis/repair-plan/critic flow.

## External references and related specs

- No network or third-party reference was needed for this read-only plan gate.
  The baseline pins `openai-codex==0.144.4`; C6 does not change transport or
  provider routing.
- `docs/agent-world-environment-generation.zh.md` — canonical authority for
  Artifact provenance, isolated Materializer/Runtime, independent Judge,
  envpkg/Registry, and downstream Consumer boundaries.
- `docs/direct-rewrite-execution-map.zh.md` — derived execution taxonomy and
  two-static-graph anti-overdesign constraint; it was used only consistently
  with the canonical document.
- `AGENTS.md`, `.trellis/spec/agent_world/backend/index.md`, and
  `.trellis/spec/guides/foundry-product-alignment.md` — current clean-lineage,
  InvocationBackend, artifact-DAG, live-evidence, and PAC requirements.

## Non-claims and next permitted gate

This allow approves only implementation of the exact C6 plan. It does not
prove C6 code, deterministic checks, a live Direct release, automatic Repair,
Campaign/Expand or multi-parent success, Consumer/SFT/RL use, broad verifier
coverage beyond the four bounded families, provider availability, or OS-level
sandboxing.

The next permitted gate is for the main session to add this exact current allow
record to both task JSONL manifests, then dispatch the bounded Direct
implementation. After implementation, a fresh independent whole-diff check is
required before the listed real proofs. No implementation may widen these
contracts or add later-child behavior without a revised plan and fresh critic.

## Caveats / Not Found

- C5 was a static whole-diff block, not a real proof terminal; no Observe
  failure scene exists for it.
- No C6 product code, provider call, candidate process, or test was run by this
  reviewer. The approval relies on the written contract and the mandatory
  checks above, not on a claim that the current C5 code already satisfies it.
