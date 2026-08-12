# Research: complete Direct R9-C4 cross-layer review

- Query: Fresh independent full-scope cross-layer review of the complete Direct
  R9-C4 plan and its complete-v1 parent, including the framework-compiled
  hashed `uv pip sync` installation transaction.
- Scope: mixed (clean-worktree task/code evidence plus the installed and
  official `uv` command contracts).
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`

## Decision

Decision: block

- Child plan digest (independently recomputed):
  `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`.
- Parent plan digest (independently recomputed):
  `6e98efdd14d7ee57ce526ecbccb3c238418c12c4da3e7836b055bd6fbf65e929`.
- Plan revision: Direct R9-C4, C4 revision 1. This is its first full-scope
  review; a corrected plan may receive only the next review in this lineage.
- Scope classification: larger Direct vertical slice across Controller,
  Designer, Builder, Judge, Registry and Observe. C4's immediate change is the
  Builder-owned dependency-admission/installation boundary, but a bad install
  result would invalidate downstream Integration, Judge, package, Registry and
  Observe claims.
- Trigger: PAC-18's deterministic, pre-execution C3 installer contradiction.
  It is not a failed Direct/E2E terminal. No Observe scene or Diagnosis Record
  applies, and this review ran no candidate or product proof.

The C4 records correctly describe the intent, but the exact written plan cannot
be allowed: its fixed `uv pip sync` command does not admit the explicitly
permitted stdlib-only closure, and the plan identity still contains operative
R9-C2 gates. A C4 `allow` would neither satisfy the written C2 prerequisite
nor prove the stated C4 stdlib path. Therefore this record grants **no**
implementation or check authorization for digest `97dd80a7...` or parent digest
`6e98efdd...`.

## Product Target, Impact Chain, And Owners

The target remains:

> Turn an arbitrary natural-language `EnvironmentRequest` into an
> evidence-grounded executable environment, independently verify it in a real
> isolated boundary, publish an immutable Registry `EnvironmentPackage`, and
> expose only safe facts through Observe.

```text
EnvironmentRequest -> DesignGraph -> BuildPlan + CandidateBuild / VerifierIntent
  -> framework lock admission -> isolated Integration -> independent Judge
  -> Controller ReleaseKernel/Package -> Registry cold-read + receipt -> Observe
```

- The two fixed graphs and one `NodeSpec`/`EdgeSpec` vocabulary remain the
  smallest coherent composition: no scheduler, graph DSL, plugin registry,
  callback bus, or second success route is proposed.
- Designer owns DesignGraph and VerifierIntent; Builder owns BuildPlan,
  CandidateBuild and the C4 installer/Integration boundary; Judge owns
  evidence-only verdicts; Controller owns the sole ReleaseKernel; Registry
  cold-verifies and atomically publishes; Observe only projects durable facts.
- CandidateBuild consumes only Design and BuildPlan. It cannot receive
  VerifierIntent, sealed/Judge data, Finding routing, hashes, manifests or
  release authority. Integration starts from the committed candidate without a
  VerifierIntent dependency; Judge is the first join of the exact passed
  Integration and framework-compiled VerifierBundle.
- Curriculum remains the sole semantic producer of ordered finite difficulty
  domains. Framework compiles the exact schema; TaskRequirement, Materializer,
  Integration, Judge, package, future Expand and Consumer only consume it.
- A non-pass Integration leaves Judge, Package and Registry `not_run`; route-
  free Findings preserve subject/evidence/owner facts for the later bounded
  Repair child without implementing a Repair Router here.
- Package/Registry retain complete physical closure, passed-Integration,
  Judge/Verifier, dossier and telemetry bindings. Registry's independent
  cold-read and Observe's receipt/package recheck preserve the future Expand
  and Consumer handoffs without implementing those children now.

Those cross-layer meanings are compatible *if* the installer is corrected
without changing their immutable handoffs. They are not evidence that the
current partial clean-worktree implementation has completed any product path.

## Blocking Criteria And Actionable Plan Revision

### 1. The exact C4 command cannot serve the permitted stdlib-only case

The plan and node contract mandate a fixed `uv pip sync` transaction while
also permitting the first live proof to be stdlib-only
([implement.md:196-222](../implement.md),
[node-contracts.md:611-655](../node-contracts.md)). For an empty
framework-owned requirements file, installed `uv 0.11.29` documents
`--allow-empty-requirements` as required to allow a sync that clears an empty
closure. The listed C4 argv omits it. Thus a valid stdlib-only candidate would
fail before candidate execution despite satisfying the C4 admission policy.

The plan writer must add `--allow-empty-requirements` to the fixed `uv pip
sync` argv (with framework validation that emptiness means exactly an admitted
stdlib-only closure), or explicitly choose and prove a different fixed
stdlib-only transaction. Do not special-case a candidate, relax hash mode, or
skip source/recheck assertions.

### 2. The venv transaction can still discover the candidate project

The exact `uv venv` argv has no `--no-project` and specifies no
framework-owned working directory ([implement.md:200-208](../implement.md),
[node-contracts.md:619-636](../node-contracts.md)). `uv 0.11.29` exposes
`uv venv --no-project` specifically to avoid project/workspace discovery.
Although preflight rejects candidate `tool.uv` configuration and sources, the
written invocation leaves candidate project discovery as an unbounded input
channel. That contradicts the claim that C4's only installer inputs are
framework Python, empty config, framework requirements and the verified flat
wheel directory.

The revised plan must require both commands to execute from a fresh
framework-owned directory outside the candidate root. It must add `--no-project`
to the fixed `uv venv` argv and make a subprocess-spy check prove neither argv,
`cwd`, environment nor config path reaches candidate metadata. The pip command
must retain only the framework-owned requirements file as its positional input;
it must never receive `--project`, candidate root, `pyproject.toml`, `uv.lock`,
candidate config, a candidate cache or a candidate environment variable.

### 3. “Compare installed names/versions” needs an exact closure definition

C4 correctly requires lock hash/size admission, an empty verified wheel store,
fully pinned/hash-bearing framework requirements, rehashing, and an installed
name/version comparison ([implement.md:187-220](../implement.md),
[node-contracts.md:598-649](../node-contracts.md)). It does not state the
comparison as set equality or define how a universal `uv.lock` with markers,
extras, forks, or multiple lock entries becomes the active closure. A subset
check could silently miss a locked dependency; an over-broad parse could install
an unselected one. Reimplementing uv resolution would also violate the
minimalism constraint.

The revised plan must define one framework-owned `AdmittedLockClosure` before
uv: canonical distribution name, exact version, active marker context, selected
wheel filename(s), SHA-256 hash set and exact size for every admitted package.
It must deterministically derive only a single unambiguous active closure from
the candidate declarations and the frozen lock, failing closed before uv on a
marker/extra/fork/multi-version shape it cannot reduce without resolution. The
requirements compiler may emit only normalized `name==version` plus the
closure's `--hash=sha256:...` values; it must not copy candidate requirement
text or add a resolver/configuration service. After sync, the framework must
enumerate the fresh venv's installed distributions and require exact canonical
`(name, version)` equality with the admitted closure (and reject duplicates or
unexpected project installation); `--strict` is additional environment
validation, not a replacement for that equality assertion.

### 4. The written plan identity is internally stale

The same bytes presented as C4 still say that C2 is the operative plan and that
no product code may change until an exact R9-C2 allow
([implement.md:15-29](../implement.md)). The binding node-contract header also
labels the closure C2 ([node-contracts.md:1-10](../node-contracts.md)), and the
parent execution plan calls C2 the current revision
([../../08-11-foundry-complete-v1/implement.md:39-55](../../08-11-foundry-complete-v1/implement.md)).
This is not harmless historical prose: the child condition is an active
pre-change gate. A record allowing C4 cannot meet it.

The plan writer must update the operative child and parent lineage language to
the next exact revision, retain earlier C1/C2/C3 facts as history only, and
recompute both aggregate digests. This is a planning-only revision; it must not
edit product code or manifests while this review is blocked.

## C4 Boundary Assessment

Subject to the corrections above, C4 remains the right minimal mechanism:

- Preflight must reject build backends/sdists, workspaces/groups/editables,
  custom indexes/find-links, Git/URL/path/local sources, lock sources outside
  the configured registry, missing wheels and mismatched hash/size **before**
  either uv command or any candidate process.
- Framework, not the candidate, copies only byte-hash/size-matched wheels into
  an empty run-local flat directory. `--no-index` plus that directory is the
  sole distribution input; a separate run-local cache remains opaque and is
  never directly modified.
- `uv pip sync --require-hashes --offline --no-build --strict` on a fresh venv
  and framework requirements is compatible with no candidate project install
  and no downloader/index/resolver/configuration platform, provided the revised
  cwd/argv/closure requirements above are made binding.
- Source-tree, lock, requirements and verified-store digests must be recorded
  as Integration evidence and rechecked after installation. Installation
  mutation, missing wheel, attempted build/network, a nonexact installed set or
  a candidate-root installation is a terminal Integration non-pass, never a
  fallback/retry.

The current partial code is not C4 evidence: it still runs candidate-root
`uv sync --project <root>` with C3-only flags
([agent_world/supply_chain.py:226-328](../../../../agent_world/supply_chain.py))
and its current test asserts that retired command
([tests/test_supply_chain.py:20-64](../../../../tests/test_supply_chain.py)).
It must be replaced only after a matching revised allow. The partial graph code
does already declare two fixed graph shapes and keeps CandidateBuild free of a
verifier input ([agent_world/graph.py:88-295](../../../../agent_world/graph.py)),
but its small tests are not a proof of the full written node contracts or
release closure.

## Required Checks And Proofs After A Revised Allow

Deterministic checks must prove all of the following before a real Direct
claim:

1. The recomputed child and parent aggregates match the revised bytes and the
   current critic allow is present in the implementation/check context.
2. A subprocess spy sees exactly the reviewed two command arrays, framework-only
   `cwd`/environment/config/cache/requirements paths, `--no-project` for venv,
   `--allow-empty-requirements` for sync, no shell and no candidate-project
   install input.
3. Hostile build-system, sdist, custom-index, Git/URL/path/editable/local,
   workspace/group, missing/tampered wheel, source/lock/requirements/store
   mutation and ambiguous lock-closure cases fail before uv, hook, network or
   candidate-process execution.
4. A valid third-party wheel case proves exact lock hash/size admission,
   requirements hashes, closed transitive name/version set, no candidate-root
   mutation/install and no extra installed distribution. A separate stdlib-only
   case executes the same fixed transaction with an empty admitted closure.
5. Existing whole-slice checks still cover node projections and singleton
   Skills, difficulty closure, candidate/verifier separation, Integration
   fail-stop, independent Judge/route-free Finding, package/Registry
   cold-read/tamper rejection, safe Observe, direct lineage and the legacy
   firewall.

The smallest true-boundary proof sequence remains: real Direct LLM contract;
real singleton-Skill Codex preflight; real CandidateBuild followed by the
revised third-party-wheel and stdlib-only Integration cases; then a fresh,
non-fixture Direct request through independent Judge, Registry cold-read and
Observe. Any future real terminal must be followed by Observe and the normal
debugging/Diagnosis/critic flow; none is required for this static plan block.

## Files Found

- `prd.md` — Direct product requirements, two-graph path, future child seams
  and acceptance criteria.
- `design.md` — R9-C4 graph/owner/Skill/installer design and minimalism budget.
- `node-contracts.md` — binding provenance, difficulty, installer, package and
  Registry handoffs.
- `implement.md` — complete ordered Direct implementation/check/proof plan;
  contains the operative stale C2 gate and fixed C4 installer argv.
- `research/plan-digest-r9-c4-hashed-pip-sync.md` — declared child C4 digest
  and C3-to-C4 static-installer trigger.
- `research/product-alignment-checkpoints.md` — PAC-18, which correctly limits
  the earlier local wheel probe to installer feasibility.
- `research/cross-layer-review-dec00ffe-complete-direct.md` — prior full-scope
  C3 allow; it expires because C4 changed the Builder install boundary and both
  reviewed digests.
- `../../08-11-foundry-complete-v1/research/plan-digest-hashed-pip-sync-c4.md`
  — parent aggregate and evidence that only Direct planning inputs changed.
- `agent_world/supply_chain.py` and `tests/test_supply_chain.py` — partial C3
  implementation/test surface; read as compatibility evidence only, not
  permission to modify it.

## External References

- Installed command evidence: `uv 0.11.29 (x86_64-unknown-linux-gnu)`;
  `uv pip sync --help` exposes `--allow-empty-requirements`, `--require-hashes`,
  `--no-index`, `--find-links`, `--offline`, `--no-build` and `--strict`; `uv
  venv --help` exposes `--no-project`.
- [uv CLI reference](https://docs.astral.sh/uv/reference/cli/) — `--no-index`
  uses local find-links/direct URLs, `--offline` disables network, and
  `--require-hashes` enforces hashes.
- [uv settings reference](https://docs.astral.sh/uv/reference/settings/) —
  hash mode requires exact pins and hashes; `strict` validates the resulting
  environment rather than defining the expected package set.
- [uv pip locking guide](https://docs.astral.sh/uv/pip/compile/) — `uv pip
  sync` is the exact-environment operation for a requirements file.

## Non-Claims And Next Permitted Gate

This block does not claim a C4 implementation, a successful candidate install,
CandidateBuild, Integration, independent Judge, Registry release, Direct E2E,
Repair, Expand/multi-parent evolution, Consumer/SFT/RL, provider availability
or complete-v1 completion. PAC-18's local wheel probe proves command
feasibility only, not any of those outcomes.

Next permitted gate: revise **planning artifacts only** to resolve all four
blocking criteria, recompute the child and parent aggregates, append a new PAC
for the revised plan identity, then request one fresh independent full-scope
critic review. Do not dispatch implementation/check, modify product code, or
invent an Observe/Diagnosis record for this static contradiction.

## Caveats / Not Found

- The implementation/check JSONL manifests were intentionally not read: this
  research role is isolated from those dispatch manifests. The main session
  must add a future matching `allow` to both only after it exists.
- The clean worktree contains partial, uncommitted product/test changes. They
  were inspected read-only and do not change the blocked plan decision.
