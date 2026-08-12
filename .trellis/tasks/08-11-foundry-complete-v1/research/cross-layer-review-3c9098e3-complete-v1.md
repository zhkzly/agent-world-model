# Research: complete-v1 C5 full-scope cross-layer review

- Query: Fresh independent full-scope parent review of complete-v1 C5, including parent digest `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`, embedded Direct R9-C5 digest `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`, the C4 block, PAC-19, canonical contracts, execution map, and sequential Repair/Expand/Consumer plans.
- Scope: internal, read-only static plan review
- Date: 2026-08-11
- Reviewer: independent `trellis-research`

## Decision

Decision: allow

- Parent plan digest: `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`.
- Embedded Direct plan digest: `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`.
- Plan revision: complete-v1 C5 / Direct R9-C5, first and final planning revision after the Direct R9-C4 full-scope block `cross-layer-review-97dd80a7-complete-direct.md`.
- Scope classification: larger coherent product slice. It covers the Direct vertical slice across Controller, Designer, Builder, Judge, Registry, and Observe, plus the frozen handoffs and ordered gates for bounded Repair, Expand, and Consumer.
- Trigger: PAC-19's static C4 plan correction. It is not a failed product terminal; no new Observe scene or Diagnosis Record exists or is required.

This allow authorizes the coordinator to execute the written complete-v1 parent sequence at the exact parent digest above and to dispatch Direct implementation and check at the exact Direct digest above. It does not authorize Repair, Expand, or Consumer implementation/check now: each still needs its exact upstream commit/contract handoff and a fresh, matching child-specific critic allow.

## Digest Reproduction

I SHA-256 hashed raw bytes, formed standard lowercase newline-terminated `sha256sum` lines with the repo-relative paths in parent `implement.md:61-77`, then SHA-256 hashed the respective ordered concatenations.

- All sixteen prescribed parent inputs reproduce `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`.
- The five Direct inputs—four Direct planning files plus `docs/direct-rewrite-execution-map.zh.md`—reproduce `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`.
- Component hashes match `plan-digest-closed-install-c5.md`; the parent digest excludes review records and manifests as declared. Any byte change to these inputs, any changed trust boundary, or a relevant later real scene expires this allow.

## Product Target, Scope, and Impact Chain

The target remains to turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe durable facts through Observe. Expand must produce a fresh package from real technical evidence and one or more exact released parents through the same Design/Build/Judge/Release path. Consumer may create isolated public Episodes for SFT/RL from exact released packages, without environment, reward, or release authority.

```text
EnvironmentRequest
  -> Direct DesignGraph -> CandidateGraph -> Registry EnvironmentPackage -> Observe
                             failed Work/Gate -> Finding
                                                   -> bounded Repair -> graph re-entry

exact released parents + technical evidence
  -> frozen Campaign + current parent-use admission
  -> DesignGraph -> CandidateGraph -> fresh Registry package -> Observe

exact released package
  -> immutable Suite + current episode-use admission
  -> private materialization/reset -> public Episode -> SFT / thin RL -> Observe
```

The C5 delta is confined to the Builder-owned Direct dependency-admission and Integration installation transaction. It does not alter the shared Artifact/package/runtime ABI, grant installer authority to Repair/Expand/Consumer, or change a runtime model route. The parent makes this constraint explicit (`implement.md:40-56`), while the parent design keeps Direct and Expand as separate inputs to the same two static generation graphs, Repair as deterministic control, Consumer downstream, and Observe read-only (`design.md:5-31`).

## C4 Block Closure

The Direct C4 block identified four plan-level defects. C5 closes each without a fallback path or a new general dependency platform:

1. **Empty admitted closure:** `uv pip sync` now includes `--allow-empty-requirements`; empty requirements are admitted only when the framework has committed an exactly empty stdlib-only closure (`node-contracts.md:630-657`).
2. **Candidate project isolation:** both commands run from a fresh framework-owned directory outside candidate source; `uv venv` uses `--no-project`, and the fixed scrubbed environment/config prevents candidate or ambient configuration discovery (`node-contracts.md:623-652`; Direct `implement.md:205-239`).
3. **Exact finite closure:** framework commits an `AdmittedLockClosure` with canonical distribution name, exact version, verified wheel filename/hash/size data; it rejects markers, extras, forks, duplicate/multiple versions, and every shape needing resolution before `uv`. It emits only normalized pinned hash-bearing requirements and verifies exact installed canonical `(name, version)` set equality after sync (`node-contracts.md:611-659`). This is admission and validation, not a resolver.
4. **Current lineage:** the Direct and parent plans identify C5 as current, preserve prior C1-C4 facts as history, and require this fresh exact-digest parent/Direct review before code (`Direct implement.md:1-29`; parent `implement.md:35-86`).

PAC-19 records the same bounded correction and the existing command-shape probes only as static installer evidence. The current code/test surface still contains the retired C3 candidate-root `uv sync` shape; it is pre-change baseline evidence, not an implementation claim or an alternate success path.

## Owner and Consumer Compatibility

### Direct seed, package, and release

- `WorkRecord` retains immutable ordered input/dependency provenance, execution kind, validation/assurance/Finding references, and Direct's inert `invalidated_by=null`; a `CANDIDATE_PROCESS` never transfers commit authority. `Finding` remains framework-derived and route-free—no target, retry, budget, invalidation, jump, or release action (`node-contracts.md:56-118`; parent `design.md:102-145`).
- Framework remains the sole candidate-closure and installer owner; CandidateBuild supplies advisory completion/source only and sees neither verifier/Judge/release authority. BuildPlan and VerifierIntent are read-only siblings, Integration consumes Design + Candidate, and Judge is the first verifier join after exact passed Integration (`design.md:74-94`; execution map `:80-101`).
- The single Controller ReleaseKernel packages only the exact passed closure. Registry cold-reads/re-hashes physical package contents and publishes atomically; the emitted `EnvironmentPackageRef` binds the same Design/Candidate/passed-Integration/Judge/lineage closure. The C5 temporary venv, requirements file, verified wheel directory, and cache are Integration evidence only and do not enter package bytes or receipt semantics (`node-contracts.md:721-810`).
- The framework-compiled ordered `DifficultySchema` remains the only difficulty owner. TaskRequirement, Materializer, Integration, Judge, package, Expand, and Consumer all consume the same exact closed selection; candidate code and Consumer cannot widen or default it (`node-contracts.md:408-483`, `:669-719`).

### Bounded Repair

Repair consumes the frozen Direct Finding/provenance closure, re-derives the owner and dependency closure, writes append-only `RepairDecision`/`WorkInvalidation`, preserves unrelated Artifacts, and caps same-owner and one-hop behavior. It has no installer input or authority and is not pre-implemented by Direct (`08-11-foundry-bounded-repair/{prd,design,implement}.md`). Its fresh gate remains conditioned on an exact completed Direct commit and frozen contracts.

### Expand and multi-parent

Campaign freezes exact parent/package/receipt/semantic refs, source/policy/operator revisions, direction, seed, and budget. Each selected parent undergoes a current Registry `PackageUseAdmission`; quarantine/supersession blocks use before Design/Build without changing snapshot bytes. Policy selects only; Designer rebuilds a complete child design; Builder alone receives verified read-only source closures after Design commit; every child receives fresh Integration/Judge/Registry results. `CandidateOutcome` keeps execution, hard-gate, and release facts distinct, and infrastructure error cannot become a quality score (`08-11-foundry-expand-multiparent/{prd,design,implement}.md`). C5 has no shared Contract or installer-role effect on these facts.

### Consumer, SFT/RL, and Observe

Consumer freezes exact released refs in a Suite, repeats package/receipt/current-Registry admission before each new Episode, and leaves the Suite unchanged on a blocked result. Only the framework carries Materializer `initial_config` through private `MaterializedEpisodeInput` to Runtime; public Episode/SFT/RL/log/Observe records contain only allowed public facts. Consumer cold-reads the exact package difficulty schema and cannot define a second domain (`08-11-foundry-consumer-sft-rl/{prd,design,implement}.md`). Observe projects durable safe Direct/Repair/Campaign/Episode facts only; it cannot route, retry, judge, mutate, publish, or disclose private/sealed inputs (`parent design.md:274-293`).

### Model assignments and minimalism

Runtime retains exactly two distinct product routes: prompt-only Direct LLM and real Codex SDK/session/one-Skill Agent; development workers remain separately and explicitly Terra-pinned. C5 adds neither a model assignment nor ambient Skill/SDK inheritance. The reviewed design stays within two static domain graphs, one deterministic RepairController, one bounded `directed@1` Campaign, two minimal Expand operators, one small Consumer service, one exporter, one thin RL adapter, and read-only Observe. It continues to reject a scheduler, dynamic graph/plugin system, source merger, trainer, permission/profile DSL, callback platform, compatibility route, runtime Critic, second Judge, second Registry, or second ReleaseKernel.

## Smallest Allowed Implementation and Proof

1. Record this exact allow in the required parent and Direct implementation/check contexts. Every future worker dispatch must retain explicit `--provider codex --model gpt-5.6-terra` (`parent implement.md:180-205`).
2. Implement only Direct R9-C5 in the clean worktree: the two fixed graphs and committed-Artifact transactions; route/Skill projection boundaries; candidate/verifier separation; canonical Runtime/Materializer; framework-owned C5 installer/Integration fail-stop; independent Judge; single ReleaseKernel; Registry cold-read; and safe Observe. Do not add Repair, Campaign, Consumer, a third route, or a generic install/configuration system.
3. Deterministically prove C5's exact two argv lists and framework-only cwd/environment/config/cache/requirements paths; reject hostile pre-`uv` sources and ambiguous lock shapes; prove valid third-party-wheel exact closure and empty stdlib closure; reject mutation, network, build, project install, and nonexact installed sets. Retain Direct regressions for graph/owner/dependency closure, route-free Finding, difficulty selection/echo, candidate-verifier exclusion, Integration fail-stop, package/Registry cold-read, Observe secrecy, lint/type/compile, and legacy firewall.
4. Run the true-boundary sequence in order: Direct-LLM contract; singleton-Skill real Codex preflight; real CandidateBuild plus offline Integration for valid and invalid difficulty selections; then one fresh non-fixture Direct-to-Registry release. Read Observe after every real terminal.
5. Permit Repair only after the Direct exit handoff names the exact clean commit, contract digest, Registry receipt, and safe Observe scene; its separate proof is one real negative-to-repaired lineage. Permit Expand only after the same frozen Direct handoff and a fresh Campaign/Release allow; permit Consumer only after frozen Registry/runtime contracts, an exact released Expand package, and its fresh public-boundary allow.

## Non-Claims and Next Permitted Gate

- This is a static planning authorization only. It does not prove C5 code exists, the former C3 implementation is usable, a wheel install succeeds beyond the recorded local probes, any provider/Agent is available, or any Direct package has been released.
- It does not prove bounded Repair, parent-use admission, Campaign, useful multi-parent composition, Consumer isolation, SFT export, online RL, training improvement, or complete-v1 delivery.
- A green deterministic check, graph declaration, model response, package-shaped file, or installer probe is not the natural-language-need-to-published-EnvironmentPackage outcome.
- Any failed real terminal must follow Observe -> debugging -> Diagnosis Record -> revised repair plan -> fresh critic -> smallest proof -> Observe. This C5 review authorizes no retry or repair shortcut.

Next permitted gate: the coordinator may add this matching record to the parent and Direct contexts, then dispatch the explicitly Terra-pinned Direct implementation/check at Direct digest `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a` under parent digest `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`. Continue through the written parent sequence only with the later exact-handoff and fresh-child-allow gates intact.

## Files Found

- `08-11-foundry-complete-v1/{prd,design,implement}.md` — parent target, ABI, child order, acceptance, and dispatch gates.
- `08-10-direct-foundry-minimal-dag/{prd,design,node-contracts,implement}.md` — Direct graph, Runtime/package, C5 installer, and proof contracts.
- `08-11-foundry-{bounded-repair,expand-multiparent,consumer-sft-rl}/*` — later consumer contracts, authority separation, and fresh-gate requirements.
- `research/{plan-digest-closed-install-c5,cross-layer-review-6e98efdd-complete-v1}.md` and Direct `research/{plan-digest-r9-c5-closed-install,cross-layer-review-97dd80a7-complete-direct,product-alignment-checkpoints}.md` — C5 identity, C4 block, and PAC-19 correction evidence.
- `docs/agent-world-environment-generation.zh.md` and `docs/direct-rewrite-execution-map.zh.md` — canonical product/authority contract and derived executor map.
- `agent_world/{supply_chain,graph}.py` and `tests/test_supply_chain.py` — partial pre-change Direct/C3 baseline; not relied upon as product proof.

## Caveats / Not Found

- No code, plan, manifest, Registry state, live provider, candidate process, or real proof was changed or run by this reviewer. No external reference was needed for this static review.
- The record is valid only for the exact digests above and is a development gate, not a runtime CriticReport, Judge result, release fact, Artifact ABI, or package evidence.
