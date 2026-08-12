# Research: complete-v1 C4 full-scope cross-layer review

- Query: Fresh independent review of the complete-v1 parent sequence and all
  four child plans at parent digest
  `6e98efdd14d7ee57ce526ecbccb3c238418c12c4da3e7836b055bd6fbf65e929`,
  including embedded Direct R9-C4 digest
  `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`.
- Scope: internal
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`, model `gpt-5.6-terra`

## Decision

Decision: allow

- Parent plan digest: `6e98efdd14d7ee57ce526ecbccb3c238418c12c4da3e7836b055bd6fbf65e929`.
- Embedded Direct plan digest: `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`.
- Plan revision: complete-v1 C4, revision 1 in the
  `complete-v1-hashed-pip-sync` lineage; embedded Direct R9-C4,
  framework-compiled hashed `uv pip sync`.
- Revision count: one C4 plan revision. The earlier full-scope C3 allows are
  immutable lineage evidence only and expired when the four Direct plan inputs
  changed.
- Scope classification: larger coherent product slice across Controller,
  Designer, Builder, Judge, Registry, Observe, and the ordered Direct ->
  Repair -> Expand -> Consumer child handoffs.
- Trigger: a static deterministic installer contradiction, not a product or
  real-proof terminal. PAC-18 records that the tested C3 `uv sync` form either
  rejected `--no-sources` or followed a remote lock URL; a local,
  hash-required, offline `uv pip sync` probe succeeded instead
  (`08-10-direct-foundry-minimal-dag/research/product-alignment-checkpoints.md:472-496`).
  There is therefore no relevant Observe scene or Diagnosis Record, and this
  review does not authorize a retry of a failed product run.

This allow authorizes the written **parent sequence** at the exact parent
digest and the Direct implementation/check sequence at the exact embedded
Direct digest. It does not collapse later child gates: Repair, Expand, and
Consumer may start only after the exact predecessor commit/contract handoff is
recorded and that child receives its own fresh matching allow.

## Digest Reproduction

I independently hashed raw UTF-8 bytes, emitted lowercase standard
newline-terminated `sha256sum` lines in the order declared by parent
`implement.md`, and SHA-256 hashed each concatenation.

- The prescribed sixteen-file parent aggregate is exactly
  `6e98efdd14d7ee57ce526ecbccb3c238418c12c4da3e7836b055bd6fbf65e929`.
- The Direct aggregate is exactly
  `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`.
  It correctly includes the four Direct planning files **and**
  `docs/direct-rewrite-execution-map.zh.md`; the latter currently hashes to
  `8a8d324e833beee78b7cfb9ca6624e15315a6895e228b4eef584c00b06a8509e`.

The sixteen component hashes match the C4 digest record:

```text
5d54acb103f6752f2543b683201643ca7c5c0b8af802f6fb54ccce74c657a8e2  parent/prd.md
2e993c838294a0ceae24a79553caf6c0d5d74e88f097960b1cfab73f09402a9d  parent/design.md
906437a5b7eb1f3c2303c3cd536fd66a391b57ffdc3340a21cc43a4cbbb53223  parent/implement.md
d3034f514dcdcebcaf093c1e62a742766af4ce1d747f2b79de50a107770b3a61  Direct/prd.md
886c3ecfacdbec1585e17ed501babe3b0b38cbfa201b576ec2717f9997625723  Direct/design.md
df7a7eb702c12c97044cb7704ef6bf4eb320f1aba0a58b497ac0be3cb94e50d3  Direct/node-contracts.md
779c7c0779515d1eb6455777be8316351741ded2b43ea7429b44e85854ec05f5  Direct/implement.md
95fa444c3e8519df90cac7680a1ce9c256100dd47a84b493462d28d843b57149  Repair/prd.md
cbfee29d2392182eb908495e6d23652a508a1c33dea4f2c0cacff3659a1b1af5  Repair/design.md
f6445cb6ba97b0e32280f30718f8c28bdc51d4514771cd48418dd007d50aedc1  Repair/implement.md
bf10d6b5c7d44a810e97c28499663fc150b1d3abd5f7fec5f30586605a289cca  Expand/prd.md
fc55bb580858493222a21c0482e247faba85095bbbb5cd66a1149ef0dc41cefd  Expand/design.md
d60a0534bb77267248605b4bedf0dcd4525b129e7e047c2d85c87440430dad9f  Expand/implement.md
fbb3b46ca05c31047029e6a1c68e215f2fd7edd47d68bf363c4c7290324d1038  Consumer/prd.md
f8bd06ed66cfdcd0abf03606ff2573ae10dea51a68966e922b3602b808c6369d  Consumer/design.md
490d985ed2915430167722c6673ddd11fe84de2ec7686c1439e723d472265cd8  Consumer/implement.md
```

## Product Target, Scope, And Impact Chain

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.
Expand must make fresh packages from technical evidence and exact released
parents through that same path; Consumer may make isolated public Episodes for
SFT/RL without obtaining environment, reward, or release authority. This
matches the canonical flow and its separations
(`docs/agent-world-environment-generation.zh.md:70-103,117-129`).

```text
EnvironmentRequest -> DesignGraph -> CandidateGraph -> Judge -> Package
  -> Registry -> Observe
                     failed exact Work/Gate -> Finding -> bounded Repair

exact Registry parents + technical evidence -> frozen Campaign -> DesignGraph
  -> CandidateGraph -> new Registry package -> Observe

exact Registry package -> immutable Suite -> current admission -> private
  materialization/reset -> public Episode -> SFT / thin RL -> Observe
```

The C4 change is confined to the Builder-owned Integration install transaction:
framework canonical-parses and admits the lock closure, hash/size verifies
wheels, compiles a temporary fully pinned/hash-required requirements file,
creates a fresh framework venv, and invokes fixed offline/no-build/no-index
`uv pip sync` over the verified flat store
(`08-10-direct-foundry-minimal-dag/node-contracts.md:596-649`; Direct plan
`implement.md:187-220`). Candidate metadata, root, lock, config and ambient
environment are absent from the installer input.

This is semantically compatible with the canonical offline-build objective:
the framework owns the clean candidate copy, independent venv, verified wheel
admission, and fail-closed no-network/no-build behavior
(`docs/agent-world-environment-generation.zh.md:728-750`). The C4 temporary
requirements file is an Integration-only framework artifact, not an envpkg
input or a runtime ABI. It introduces no resolver, downloader, index client,
candidate project installation, cache mutation, graph node, or control plane.
Implementation must retain the canonical physical separation of the fresh venv
and clean materialization; C4 does not authorize a candidate-root install.

## Owner And Consumer Compatibility Review

- **Direct shared ABI:** immutable `ArtifactEnvelope`/`WorkRecord` preserve
  producer, ordered dependency provenance, execution kind, terminal evidence,
  and the inert `invalidated_by=null` Direct baseline
  (`node-contracts.md:18-69`). Findings remain framework-derived and route-free
  (`node-contracts.md:94-115`). C4 changes neither record shape nor any owner.
- **Release and package:** Controller remains the sole ReleaseKernel and
  Registry remains physical re-verifier/atomic publisher
  (`node-contracts.md:71-92`). The portable package closure,
  `EnvironmentPackageRef`, receipt, exact passed Integration, and separate
  semantic/implementation lineage remain unchanged
  (`node-contracts.md:735-800`). Thus the installer produces only Integration
  evidence; it cannot change package bytes, receipt meaning, or release facts.
- **Repair:** it consumes a re-derived Finding owner, immutable dependencies,
  a capped same-owner/one-hop decision, append-only invalidation, and honest
  exhaustion/no-progress rather than an LLM router
  (`08-11-foundry-bounded-repair/design.md:5-69`). It has no installer input or
  installer authority; its plan still requires an exact Direct handoff and a
  fresh critic before code (`implement.md:1-30`).
- **Expand:** Campaign freezes exact parents and rechecks their live Registry
  eligibility before Design/Build; Policy selects while Designer rebuilds a
  complete Design and Builder alone receives verified read-only parent source
  closures after that commit. A self-contained child earns a new verdict and
  package; execution, hard-gate, and release statuses stay distinct
  (`08-11-foundry-expand-multiparent/design.md:5-119,197-241`). This child
  consumes the released package/runtime ABI, not the temporary Direct install
  input, and retains its Campaign/Release-boundary critic gate.
- **Consumer:** Suite and each new Episode revalidate exact package/receipt and
  current Registry status; the framework alone carries Materializer
  `initial_config` privately to Runtime, computes/validates reward and
  termination, and exposes only a public trajectory
  (`08-11-foundry-consumer-sft-rl/design.md:115-210`). SFT/RL therefore have no
  package, installer, environment, reward, or release authority. Its plan
  retains its separate public-boundary critic gate
  (`08-11-foundry-consumer-sft-rl/implement.md:213-248`).
- **Model and graph minimalism:** runtime remains the two distinct product
  routes, Direct LLM and one-Skill Codex Agent; framework/candidate process are
  not model routes. The derived map fixes two static graphs and bars a generic
  scheduler/DSL/plugin plane (`docs/direct-rewrite-execution-map.zh.md:20-60`).
  Development workers are explicitly Terra-pinned and remain separate from
  those runtime routes. C4 does not add a model assignment, Agent surface, or
  general installer/policy subsystem.

The result is a coherent sequential plan: Direct first freezes the shared
Artifact/Finding/package/runtime handoff; Repair consumes its exact provenance;
Expand consumes exact released packages and may use but does not require
Repair; Consumer consumes exact Registry/runtime contracts and a released
Expand package. The parent continues to reject a generic workflow engine,
automatic source merger, trainer, compatibility layer, or second authority
(`docs/direct-rewrite-execution-map.zh.md:159-181`).

## Smallest Allowed Implementation And Proof

1. Add this allow and the matching C4 Direct allow record to the relevant
   parent/Direct implementation and check contexts. Every dispatched research,
   critic, implementation, and check worker remains explicitly
   `--provider codex --model gpt-5.6-terra`.
2. Implement only written Direct R9-C4 scope in the clean worktree: two static
   graphs, committed-Artifact edges, exact Agent/Direct projections, candidate/
   verifier separation, parameterized Materializer/Runtime, Integration
   fail-stop, one framework ReleaseKernel, Registry cold-read, safe Observe,
   and the C4 installer boundary. Do not add Repair/Campaign/Consumer behavior
   or a second route.
3. Deterministically prove exact C4 argv, version pin, minimal environment,
   hash/size closure, hostile pre-`uv` rejection, no network/build/project
   install, source/lock/wheel-store rehash, and valid locked-wheel installation
   into a fresh framework venv. Also retain the Direct ABI regressions for
   provenance, route-free Findings, difficulty closure, Integration fail-stop,
   package/Registry cold-read, and Observe secrecy.
4. Run the existing ordered true-boundary proofs: Direct LLM contract; singleton
   Runtime-Skill Codex preflight; real CandidateBuild plus C4 offline
   Integration for two valid and one invalid difficulty selection; then one
   fresh non-fixture Direct-to-Registry release. Read Observe after every real
   terminal.
5. Only after that Direct exit handoff names its exact commit, shared digest,
   Registry receipt and safe Observe scene may a fresh Repair critic run. The
   same rule applies independently before Expand and before Consumer.

## Non-Claims And Next Permitted Gate

- This is a planning allow, not proof that C4 is implemented, that an installer
  works beyond the recorded local probe, or that any Agent/LLM/provider is
  available.
- It does not claim a Direct E2E release, bounded repair, Campaign, useful
  multi-parent child, Suite/Episode, SFT export, online RL episode, or parent
  product completion. PAC-18 expressly limits its evidence to installer-command
  feasibility.
- A byte change to any of the sixteen parent inputs, Direct map, shared
  contract/owner, runtime route, or later real scene expires this allow. A real
  failure must use Observe -> debugging -> Diagnosis Record -> revised plan ->
  fresh critic -> smallest proof -> Observe.

Next permitted gate: the coordinator may record this exact allow in the
required contexts and dispatch the explicit-Terra Direct implementation/check
at embedded Direct digest `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`.
Proceed through the full parent sequence only with its written exact-handoff
and fresh-later-child gates; do not dispatch Repair, Expand, or Consumer work
now.

## Files Found

- `08-11-foundry-complete-v1/{prd,design,implement}.md` — product target,
  frozen cross-child ABI, ordered delivery, and model-pinned dispatch rules.
- `08-10-direct-foundry-minimal-dag/{prd,design,node-contracts,implement}.md`
  — Direct contracts, C4 framework-only installer, package/runtime handoff,
  and proof plan.
- `08-11-foundry-bounded-repair/*` — deterministic provenance repair and
  bounded invalidation consumer.
- `08-11-foundry-expand-multiparent/*` — frozen campaign, exact parent
  admission, useful multi-parent, and lineage contracts.
- `08-11-foundry-consumer-sft-rl/*` — immutable Suite, private materialization,
  public Episode, SFT/RL and secrecy contracts.
- `docs/agent-world-environment-generation.zh.md` — canonical product/authority
  contract; `docs/direct-rewrite-execution-map.zh.md` — derived executor map.
- `research/product-alignment-checkpoints.md` PAC-18 and the prior parent and
  Direct scope-complete C3 allows — C4 trigger/non-claims and superseded lineage.

## Caveats / Not Found

- No code or live proof was run or changed. No external reference was required
  for this plan/contract review.
- The requested C4 installer correction is static/pre-execution evidence; it
  supplies no Observe scene and must not be presented as a repaired real run.
