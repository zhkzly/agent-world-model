# Research: complete Direct R9-C5 cross-layer review

- Query: Final fresh, independent, full-scope cross-layer review of Direct
  R9-C5 digest `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`
  and complete-v1 parent digest
  `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`.
- Scope: mixed — read-only plan, contracts, canonical documentation, parent
  handoffs, partial cleanroom code/tests, and locally installed `uv` CLI
  contract.
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`

## Decision

Decision: allow

- Direct plan digest independently recomputed from the declared five raw
  `sha256sum` lines: `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`.
- Parent digest independently recomputed from the declared sixteen raw lines:
  `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`.
- Plan revision: Direct R9-C5, “closed install transaction”; its declared
  revision count is the first and final planning revision after the full-scope
  R9-C4 block.
- Scope classification: larger Direct vertical slice. It coordinates the
  Controller, Designer, Builder, Judge, Registry, and Observe boundaries, and
  freezes compatible inputs for Repair, Expand, and Consumer without
  implementing their control paths.
- Trigger: static review of the written C5 correction after the C4 critic
  block. This is not a real proof terminal; no Observe scene or Diagnosis
  Record applies.

This record authorizes **only** full R9-C5 implementation and check at the two
digests above. It is a development gate, not a runtime Critic, Judge, Finding,
ReleaseKernel, or product-completion claim. It expires if either plan digest,
the reviewed trust boundary, or a relevant later real scene changes.

## Product Target, Scope, And Impact Chain

The target remains:

> Turn an arbitrary natural-language `EnvironmentRequest` into an
> evidence-grounded executable environment, independently verify it in a real
> isolated boundary, publish an immutable Registry `EnvironmentPackage`, and
> expose only safe facts through Observe.

The approved Direct chain is:

```text
EnvironmentRequest
  -> Research / DesignGraph -> complete EnvironmentDesign
  -> BuildPlan + CandidateBuild / sibling VerifierIntent
  -> framework-owned closed dependency admission + isolated Integration
  -> independent Judge -> Controller Package/ReleaseKernel
  -> Registry cold-read + atomic receipt -> safe Observe
```

Direct is the required first-package path. Future Repair consumes immutable
Work/Finding/dependency provenance; Expand supplies a complete new Design from
admitted evidence and exact released parents; Consumer consumes exact released
package/runtime/difficulty contracts through isolated public Episodes. C5
changes none of those later-child contracts: it closes the Builder installer
transaction that must precede Integration.

## C4 Block Closure Recheck

All four C4 block criteria are closed in the C5 bytes, with no compensating
resolver, downloader, candidate exception, or alternate success path.

| C4 blocking criterion | C5 binding closure and compatibility fact |
| --- | --- |
| Empty stdlib-only closure could not sync | `uv pip sync` now includes `--allow-empty-requirements`; empty requirements are permitted only when the framework-committed `AdmittedLockClosure` is exactly empty. This is written in `implement.md:200-222`, `node-contracts.md:596-655`, `prd.md:446-455`, and PAC-19. |
| `uv venv` could discover candidate project metadata | The fixed venv argv includes `--no-project`; both commands use one fresh framework-owned cwd outside the candidate root, empty framework config, and a scrubbed minimal environment. `uv pip sync` receives no candidate root, `pyproject.toml`, `uv.lock`, config, project option, cache, or environment variable. See `implement.md:187-224` and `node-contracts.md:611-655`. |
| Installed package comparison had no defined active closure | Framework commits one finite `AdmittedLockClosure` before `uv`: canonical name, exact version, and selected wheel filename/hash/size candidates for every selected package. It derives one complete active transitive closure and rejects marker, extra, fork, duplicate/multiple-version, or any resolver-requiring ambiguity before `uv`. See `node-contracts.md:596-610`, `implement.md:181-199`, and PAC-19. |
| Requirements/install validation was underdefined | Framework alone emits normalized `name==version` lines with the admitted SHA-256 hashes; no candidate requirements text is copied. After sync it rehashes inputs/store and requires exact canonical installed `(name, version)` set equality, rejecting duplicate, missing, extra, or candidate-root distributions. `--strict` is additive validation, not a replacement for equality. See `node-contracts.md:596-655` and `implement.md:211-224`. |
| The planned gate still named obsolete C2/C4 lineage | The operative child gate requires this exact C5 allow plus the matching fresh parent allow before code changes (`implement.md:15-27`). The parent calls C5 the current revision, preserves the later child ABI, and binds its aggregate to the embedded Direct C5 digest (`08-11-foundry-complete-v1/implement.md:31-100`; `plan-digest-closed-install-c5.md:1-31`). |

The actual C5 command policy is deterministic and shell-free:

```text
uv venv --no-project --python <framework-python> --no-python-downloads
  --config-file <empty-framework-uv.toml> <fresh-venv>

uv pip sync --python <fresh-venv-python> --offline --no-build --strict
  --allow-empty-requirements --require-hashes --no-index
  --find-links <run-local-verified-wheel-store>
  --config-file <empty-framework-uv.toml>
  --cache-dir <run-local-verified-wheel-cache>
  <framework-owned-hashed-requirements.txt>
```

Only framework-created values appear in those argv lists. The trusted flat
wheel directory is the sole ingestion surface, always paired with `--no-index`.
The requirement-file positional argument remains present even for the exactly
empty stdlib closure. This preserves the candidate/verifier firewall and keeps
candidate metadata out of the installer after preflight.

Local command evidence rechecked during this review: installed `uv` is
`0.11.29`; its help exposes `uv venv --no-project` and `uv pip sync`
`--allow-empty-requirements`, `--require-hashes`, `--no-build`, `--strict`,
`--no-index`, `--find-links`, and `--offline`.

## Owner And Consumer Compatibility

- The two fixed domain graphs, one `NodeSpec`, one `EdgeSpec`, and deterministic
  transaction runner remain the smallest coherent form (`design.md:59-197`;
  `docs/direct-rewrite-execution-map.zh.md:30-60`). A node resolves committed
  input refs, runs the minimum executor, framework-validates, then commits an
  immutable Artifact/terminal WorkRecord; raw model output cannot traverse an
  edge.
- Designer owns DesignGraph and `verifier_intent`; Builder owns `build_plan`,
  `candidate_build`, the dependency admission, and Integration; Judge owns
  evidence-only judging; Controller alone owns Package/ReleaseKernel; Registry
  only cold-verifies and atomically publishes; Observe only projects durable
  safe facts (`node-contracts.md:16-117`, `design.md:302-342`). No additional
  installer/release owner is introduced.
- CandidateBuild receives only Design, ImplementationContract, and BuildPlan.
  It receives no VerifierIntent/IR, challenge file, sealed case, Judge trace,
  hash/manifest authority, or release policy. Integration depends on Design +
  Candidate and can commit before verifier work; Judge is the first join of the
  exact passed Integration and framework-compiled VerifierBundle
  (`design.md:113-141`, `node-contracts.md:487-595`).
- Curriculum is the only semantic producer of finite ordered difficulty;
  framework compiles and validates the exact schema. TaskRequirement,
  Materializer, Integration, Judge, package cold-read, future Expand, and
  future Consumer consume the same digest (`node-contracts.md:408-483`,
  `node-contracts.md:667-720`). No candidate or Consumer schema owner exists.
- Integration non-pass commits safe evidence and leaves Judge/Package/Registry
  `not_run`; Findings are framework-owned and route-free. Judge cannot select a
  repair target or release action (`design.md:345-393`; `node-contracts.md:71-117`).
- The package/Registry handoff binds complete scanned physical closure, exact
  passed Integration, Verifier/Judge evidence, dossier, telemetry, direct
  origin, and empty Direct parent refs. Registry re-parses/re-hashes before
  publication; Observe rechecks package/receipt before showing `released`
  (`node-contracts.md:721-810`). This is sufficient but not a claim that
  Repair, Campaign, or Consumer is implemented.

The parent compatibility facts remain consumable: Repair re-derives owner and
dependency closure from immutable Work/Artifact facts; Expand appends current
package-use admission without rewriting a frozen snapshot; Consumer cold-reads
the exact released schema and keeps `initial_config` private
(`08-11-foundry-bounded-repair/design.md:42-76`,
`08-11-foundry-expand-multiparent/design.md:3-120`, and
`08-11-foundry-consumer-sft-rl/design.md:60-114`). C5 gives none of those
children a dependency-admission or release role.

## Partial Code/Test Compatibility

The existing cleanroom implementation is pre-allow baseline only. In
particular, `agent_world/supply_chain.py:226-328` still uses the retired C3
candidate-root `uv sync --project <root>` shape, and
`tests/test_supply_chain.py:20-64` asserts that retired argv. It is evidence
that an in-place replacement and matching test rewrite are necessary; it is not
evidence against the C5 plan and it is not itself authorized as a product
claim.

The partial graph declarations already show two literal graph shapes and keep
CandidateBuild free of a verifier input (`agent_world/graph.py:96-295`), but
the plan correctly requires implementing the full transaction, projection,
provenance, Integration, Judge, package, Registry, and Observe closure before
any Direct success assertion.

## Smallest Deterministic Checks

Implementation/check is authorized only if it first proves all of the
following deterministically:

1. Recompute child and parent plan aggregates; confirm this exact allow is
   current in the implementation and check context before dispatch.
2. Subprocess-spy the two fixed argv lists, framework-only cwd, empty config,
   minimal scrubbed environment, requirements/cache/wheel-store paths, no shell,
   `uv venv --no-project`, and no candidate metadata passed to `uv pip sync`.
3. Exercise an exactly empty stdlib closure and a valid third-party locked-wheel
   closure. In the latter, prove canonical name/version plus exact hash/size
   admission, normalized fully hashed requirements, no candidate-root install
   or mutation, and exact post-install distribution-set equality.
4. Before `uv`, reject build backend/sdist, workspace/group/editable,
   custom-index/find-links, Git/URL/path/local source, missing/tampered wheel,
   source/lock/requirements/store mutation, marker, extra, fork, duplicate, and
   multiple-version ambiguity. Prove none reaches a hook, network, `uv`, or
   candidate process as applicable.
5. Prove two static graph definitions, closed owner/port/execution contracts,
   immutable ArtifactEnvelope/WorkRecord provenance, exact model projections,
   one mounted Agent Skill or no Direct skill, and no generic/legacy control
   path.
6. Prove CandidateBuild/Verifier separation; Integration independence and
   fail-stop; difficulty compilation, exact echo, paired valid-level semantic
   change, and invalid-selection rejection; independent Judge and route-free
   Findings; package/Registry cold-read/tamper rejection; direct lineage; and
   safe read-only Observe.

## Ordered True-Boundary Proofs

After deterministic checks, run proofs in this order:

1. One real Direct LLM node against its closed prompt/input/output contract.
2. One real Codex SDK Agent preflight that proves the initial exact-singleton
   Runtime Skill surface, bundle-only marker, closure digest, non-ambient
   `CODEX_HOME`, session close, and cleanup.
3. One real CandidateBuild in a temporary workspace, framework scan, revised
   offline install, and isolated Integration. It must materialize two admitted
   difficulty selections and reject one invalid selection before Judge/release;
   exercise both the trusted-wheel and stdlib-only admitted closures.
4. One fresh, non-fixture natural-language Direct request through DesignGraph,
   CandidateGraph, independent Judge, Registry cold-read/atomic release, and a
   fresh Observe projection.

Any later real terminal, successful or failed, must be followed by Observe. A
failed terminal begins the required Observe -> debugging -> Diagnosis Record ->
revised repair plan -> fresh critic flow; it is not covered by this static
allow.

## Non-Claims And Next Permitted Gate

This allow does not claim that R9-C5 is implemented, that the partial C3 code
is conformant, that a candidate can install, that any provider is available, or
that CandidateBuild, Integration, Judge, Registry release, Direct E2E, Repair,
Expand/multi-parent evolution, Consumer/SFT/RL, or complete-v1 has succeeded.
PAC-19 and local `uv` command evidence establish the corrected installer-plan
contract only, not a product proof.

Next permitted gate: the main session may add this matching allow record to
both implementation/check manifests, then dispatch the explicit-model
R9-C5 implementation worker. It must run the deterministic checks above before
the ordered true-boundary proofs, append Product Alignment Checkpoints at the
DesignGraph, CandidateGraph, proof, and release boundaries, and stop for a new
plan/critic review if a new producer/consumer or trust-boundary change appears.

## Files Found

- `prd.md` — Direct requirements, acceptance criteria, future child seams, and
  C5 offline-install invariant.
- `design.md` — R9 two-graph architecture, ownership, model/Skill firewall,
  C5 installer rationale, and anti-overdesign budget.
- `node-contracts.md` — binding provenance, candidate/verifier, finite
  dependency-closure, materialization, package, Registry, and Observe contracts.
- `implement.md` — active C5 gates, ordered implementation, deterministic
  checks, true-boundary proofs, and sibling handoff.
- `research/plan-digest-r9-c5-closed-install.md` and parent
  `08-11-foundry-complete-v1/research/plan-digest-closed-install-c5.md` —
  declared aggregate inputs and lineage identities, independently reproduced.
- `research/cross-layer-review-97dd80a7-complete-direct.md` — prior C4 block
  and its four closure criteria; `research/product-alignment-checkpoints.md` —
  PAC-19 correction boundary.
- `docs/agent-world-environment-generation.zh.md` — canonical product/trust
  contract; `docs/direct-rewrite-execution-map.zh.md` — derived execution
  taxonomy; `docs/task-materializer-v3-integration.md` — materializer split.
- `agent_world/supply_chain.py`, `agent_world/graph.py`, and their focused
  tests — partial pre-allow implementation surface, inspected read-only.

## External References

- Local executable contract: `uv 0.11.29 (x86_64-unknown-linux-gnu)`; help
  confirmed the flags used by the C5 command policy.
- [uv CLI reference](https://docs.astral.sh/uv/reference/cli/) — command and
  option semantics for `uv venv` and `uv pip sync`.
- [uv settings reference](https://docs.astral.sh/uv/reference/settings/) —
  hash-mode and index settings referenced by the reviewed policy.

## Caveats / Not Found

- Per research-role isolation, `implement.jsonl` and `check.jsonl` were not
  read or edited. The main session, not this reviewer, must add this allow to
  both after this record exists.
- No product files, task plans, specs, JSONLs, git state, providers, or proof
  state were modified by this review; only this research record was written.
- The plan authorizes replacing the stale partial C3 installer/test surface in
  the clean worktree. Until deterministic and true-boundary evidence exists,
  that surface remains neither an accepted implementation nor release evidence.
