# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher or fallback survives.
Invariant 2: Framework owns deterministic identities, execution and verdicts; Codex-authored release code never self-authorizes.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks, dictionary worlds or green tests alone.
Not doing now: do not implement later S2 checkpoints while the v2 release/Qualification boundary is incomplete.
Gold reference: the contrasting real SQLite and filesystem/Git releases and the held-out Need gates in `implement.md`.

## Current boundary

- B: mutually blind Qualification Verifier authoring is implemented.
- C1: actor, TaskSemantics and verifier share one canonical locked materializer.
- C2: exact Author inputs and three isolated runtimes bind one acyclic Core.
- C3 SQLite vertical is complete: public physical cases, dual-reader comparison, evidence and executable mutants are sealed.
- D SQLite vertical is complete: strict receipt, immutable Publication, deterministic ZIP, relocation and audit-only cold replay pass.
- Failure-code strings are local diagnostics; cross-reader agreement covers the declared result axes and `report_values`.
- The generic cross-environment Qualification coordinator and filesystem/Git C3+D repeat are complete; Checkpoints E-G remain incomplete, so there is no S2 completion claim.

## Deletion-first correction

- Deleted the model-only `agent_task_foundry` package and its tests because no production runtime consumed it.
- Deleted the standalone QualificationCaseSpec format; real case inputs will be recorded directly by the C3 runner/evidence writer.
- Deleted disabled Alignment Patrol code, agent card and tests.
- Deleted the brittle qualification-goal keyword blacklist and duplicate completion-confirmation contract.
- Future TaskDefinition, TaskPack, AdmissionPlan, assessment and corpus records may be implemented only together with their first executable Checkpoint E–G consumer.

## Current real C3 evidence

- Expected Semantics digest: `b368ab19bd726082c21d6b99d8f6b36aee27a34e04d4e44e0bd4c9f09815a29d`.
- Actor digest: `65ad8443b5a24ec908703d85404d61c8ab73c1aa6e9e4656788a187c139650ac`.
- Repaired TaskSemantics digest: `6d0d3df0a392b1b4deec60536f7bdf61291e284437ca639629819824bebf52f7`.
- Repaired independent verifier digest: `c688c1512ec2b914a324b11eb2ee28745e97f80adfd45e7b8502e4899353c98a`.
- Current Core: `cb0b8beb3ba29e66ef705bfa99c96deacadf5721d923284ce3bb199e500bd97f`.
- Evidence manifest: `2c1150aa1c43ad5f51cc3afd0fd881218d828124336dd43659dfc0e0d2494d3b` (11 physical cases, 4 executable mutants).
- Strict receipt: `110dfd7262784817c2095675c8f17141687ff3eeea799dbb1c72a359928c4b9e`.
- Published Release ID: `36e4d7256b8865aa7d0187179a4bc813ffdbb58e3239ecf9d1c3bb1c390d6329`.
- Real public positives pass for query, persisted state change with public read-back, and stable refusal.
- No-op query/state/refusal, wrong answer and missing-readback negatives agree on all result axes and report values.
- Wrong-target, deadline near-miss, collateral and alternative-route cases agree; local failure-code wording is diagnostic only.
- Deterministic directory/ZIP bytes relocate to the same Release ID; cold preparation reproduces 5 tools, 3 capabilities and 1 StartCase.
- Audit-only cold replay reinstalls archived Semantics/Verifier and reproduces all 11 sealed results without a model call.
- Recomputed catalog/evidence tampering and a fully rebound sealed-result tamper are rejected by receipt and cold replay respectively.
- Production Atom compilation consumes only the admitted release projection and produced 6 unique Tasks: CAP-001 ×3, CAP-002 ×1 and CAP-003 ×2.
- Every compiled checker was false initially and frozen before instruction exposure; all 6 exact instructions passed two fresh public-only witnesses (12 total) with independent materialization IDs and rebinding.
- A new Atom admission run freezes plan `90a247e9111a09da5f3303bffa699e834dbcae40d4f6bed9bc84b916b2243d14` before any witness call for Task `197d40396dd6b510124ba1f85d75d03e8e76db428fbd563b8359c00e41dabd68`.
- Its two fresh public witnesses used distinct materializations and both satisfied the checker; independently executed no-op and full process-ablation challenges were rejected.
- The next fresh CAP-002 run froze CAP-003/`charge:CHG-INELIGIBLE-001` as its wrong-target Task, proved that target's own checker passed, then proved CAP-002 rejected the same physical episode.
- Two further fresh CAP-002 witnesses resolved every argument leaf: charge references to Task literals, each generated dispute reference to one prior successful trace event, and free dispute reasons explicitly to `agent_choice`; error prose is never a source.
- Plan `981ac12ff1303e1624dbc38c7c35e0854b508cf933b4657300365f56053b8cd9` precommitted to perturb every AgentChoice occurrence; two fresh public replays changed the two `/reason` values, rebound dynamic dispute references and both remained satisfied (`aad280a4861b7adcfb0c2e80c4d6b26ce6a792ae5e477dea70caba5101b4053d`).
- CAP-001 plan `12ff5376e4e9b71a5a6e8c56b12a050c88a3d0c02e991b38b5527b60b94a4317` froze disjoint-workflow CAP-002 as collateral; CAP-002 succeeded, while CAP-001 retained effects/answer/process truth and failed only `collateral_ok`.
- CAP-002 plan `ae2ec448c8a04ce1712f32455cf4da786b0a00598e6a05cf40a78c105c688d88` produced a fresh non-subsequence route that replaced public discovery/readback steps and remained satisfied (`636b079a9a9880f05fb441eb4a5a57c5864a34360dcaaee83ecc075c44d280b2`).
- Current CAP-002 plan `d7b6262950eb754d0a78dc7d376d109d5ca6327f4dcc38eb2f41e79c514b0742` froze three applicable checker result-axis mutants; live no-op/process challenges killed all three (`2fe45b87cf9d14e4bf9ddd8ed81536dff948b64f5b2a528505ba757abc9f5f49`).
- One consolidated rerun under that exact Plan bound two new witnesses, every AgentChoice perturbation, all planned challenges, a non-subsequence alternative route and 3/3 checker mutants into AdmissionReport `6f3b34cff1b6434b06e6eae78c8b196597ec8c29f5a1fac5413308c4703c9de9`.
- First sealed Atom TaskPack: `74ecb308842ad6143f88059d00bb597eeb2a7ae71abb583d6d4394c431f35c10`; canonical artifact SHA-256 `7ab100e1eded17ccb8cbbde990e891075f63d7fb94b796d2d773fd60b2dd8803` under ignored `.artifacts/taskpacks/`.
- This establishes one SQLite Atom vertical only. It does not satisfy multi-Goal, yield, cross-environment, held-out, corpus, assessment or downstream paper gates.
- ForEach-all compilation ignores inert `supported_goal_kinds`/facets and freezes the complete eligible binding set directly. The SQLite release produced exactly CAP-001 (3 members) and CAP-003 (2 members), with no singleton CAP-002 pseudo-diversity.
- CAP-003 ForEach Task `6d6bdf79a9d1851cb6c4d4a543f2880f13f17c2eaec933925e64686cdf374ea8` passed two fresh exact-instruction witnesses; both physically executed both selected refusals and every member Atom result was satisfied.
- The same Task's pre-witness plan `e6326de196b75529ae4774f36b2a9ac868844d1785411f0fe839a30b47ccd533` froze one fresh omission per member. Physical partial report `052f7f5195d539ba1916a8aadf65a1d85e723dc744987efdd7eaa2706950d9a9` produced exactly `[false,true]` and `[true,false]`.
- Current plan `e8b8d19235bdd0939eb889b1b46daa34ccda65fb45b1dd0ff1fe2a269fa93264` also precommitted to perturb every AgentChoice. Four independent fresh replays changed one `/reason` at a time and kept both members satisfied (`fde30f1716460b90aa85220b794f2802ee63f5546c0d1baf25bed7e9bcc61d04`).
- Under the same plan, physical partial report `27fe26f60899dcafd5bb1d9861f5b03ed8fcf96a70123a623b1501ff5c9c0c35` again produced exactly `[false,true]` and `[true,false]`.
- Current plan `2d66b7f6120e791a40aa78a874c5806894d19825b3c2887305d97dde902ed00c` added fresh no-op, reverse-order and `ignore_member_i` mutation policies. The live no-op returned `[false,false]`; reverse action order `[1,0]` kept both members true (`a17f2605d379c1a918fa47e3083163bc3820b1e837d536e3f3d1b26ecd6346a6`); both member mutants were killed (`c532633e3e4d45e838e51e71e22f8a2eb97a125f2ed3bb39d65288e00e4cdcf4`).
- Final plan `0c5ea736b77518b2bc615df23900e4853859d9729fdd275913a9370aa8463e33` preselected out-of-selection CAP-002 as collateral before witnesses. CAP-002 succeeded; both ForEach members retained required/process truth, failed only collateral and became unsatisfied.
- Consolidated AdmissionReport `39a71a0c7b3bac3e0d2a2761f4c219d4bf5d4f91e7083d40e6e5c0a2da0730dc` sealed ForEach TaskPack `da9dc7aca9aec274dcbfa4e2f5fac9e5bb3f60c397d3978c1a74650fbb0984e9`; canonical artifact SHA-256 `0200ef851db1dde64772ee24d7484c8eb88c4b656412524927e059f439c908aa`.
- One first provider call failed as `InfrastructureFailure/responses_request_failed` with upstream TLS EOF; a fresh unchanged run completed, so no product retry/fallback or semantic change was added.
- If compiler derives branch support only from the frozen ConditionSpec plus eligible Atom Tasks; it does not consume inert `supported_goal_kinds` or invent a condition DSL. The SQLite release compiled three If Tasks: one true CAP-002 branch and two false CAP-003 branches.
- True Task `c4cff5028b53b9fa4eeddc2b508f518ed7da237e0dc0e12ef1953de8d7a9bdc4` and false Task `c9cb93cb97dc8812d409b15ee31018f6846b525f83c8e9d6201310f0ca3e04a7` each passed two fresh exact-instruction witnesses with condition status and selected Atom result agreeing.
- Each If Task now precommits to a `flip_condition_branch` checker mutant. On four fresh witnesses, selected branch stayed satisfied while the opposite Atom evaluator rejected the exact same physical before/after/trace; true and false plans are `52b7f207e09f40518a39b443f9c0b2d1b8fef0f0a44baddf8b59a0b86db57e30` and `79df3c5c1f2776ec3569e2e510a38cbb2e3149ccaa10db222404b53f6d2a9863`.
- The true If Task reuses exact admitted CAP-002 AtomTaskPack `151d94d0dc4e39276acb487275e3ae546843b7072c7cdf59f0f4b82f3497dc36` instead of duplicating branch challenges. Conditional AdmissionReport `924041773a79eba232512553a460cdac5c87801cb5290418256cc8d29d502bae` sealed If TaskPack `ac444345bea360f5489829a75b82022991faa77b449b5f6d7b89997e757a10c8`; canonical artifact SHA-256 `9b3f00c093c90c9536df06bd059ab10d82069ecc2e1772fcff0cc4a9be576469`.
- This establishes one true-branch If TaskPack. False-branch admission remains dependent on a complete CAP-003 AtomTaskPack; AllGoal remains unavailable without a natural qualified CompositionRule.
- Repository lock, Ruff, format, Mypy, full Pytest and diff checks are green after the deletion.

## Filesystem/Git C3+D evidence

- The same production `run_v2_qualification` used for SQLite sealed 18 Git
  physical cases: six positives, six fresh replays, two missing-process cases,
  and one each for no-op, wrong answer, wrong target and collateral.
- Core `ce26a09b89c4ee3ef7487b1fae968f4af8add4ce7f47bd054779455799e9ed43`
  binds actor `055dfeae...`, TaskSemantics `ead395ed...` and independent
  verifier `249f03c9...`; evidence digest is `8a3ed79c...`.
- Strict Publication produced Release ID
  `175d92d1d8c107ad6cabc6b5b39c7334216b849a3971a5233781ae8ddbff393e`.
- Directory verification, audit-only cold replay, renamed ZIP preparation and a
  Consumer-side real `reset/tools/invoke` all reproduced that exact Release ID,
  three capabilities, two StartCases and six Git tools.
- The first ZIP attempt exposed a real physical defect: file-only archives drop
  empty `.git` directories that are included in sealed tree identity. Production
  ZIP writing/staging now preserves explicit directory entries and modes; the
  corrected canonical ZIP SHA-256 is
  `6bb57a0744127accbe8bd60a657d77566eba6c4523044d830d78487ee07d652e`.

## Filesystem/Git semantic successor and Checkpoint E

- Cross-layer compilation exposed that the first Git release classified the
  real update+commit as `process`, allowing S2 to omit a physically applicable
  collateral challenge. The Expected Semantics contract now defines and
  physically enforces state-effect precedence for `task_kind`.
- Every Taskable capability now has a structured final answer. Public conditions
  require one branch-neutral answer contract, and generated AnswerField schemas
  are rejected before Provider use unless they satisfy the strict structured
  output subset recursively.
- The current mutually blind Authors are TaskSemantics `e92b4db5...` and
  Verifier `0720dcf7...`. Production Qualification sealed 19 physical cases and
  two reader mutants under Core `5d185bd1...`.
- Current immutable Git Release ID:
  `3ee01aedf891592abc14d0039ce65127463eacb5785d7d1014ca9ad50fcfdfde`;
  evidence digest `f632a710...`, receipt digest `3d604a5c...`, canonical ZIP
  SHA-256 `e5c43ce5ff635776537f280fc4a2f255a9b6cc261e8bf85b9dd90367d002fa0b`.
- Cold Checkpoint E compiled 12 Atom, 4 complete ForEach and 6 If candidates
  from that exact release: 22 total over `git-clean` and
  `git-pending_change`. Irrelevant condition/binding pairs abstain and reject
  only that Blueprint.
- Post-witness AgentChoice replay now rebinds dynamic final answers from the new
  physical run's checker report before its second evaluation. Public witness
  answers are never rewritten by Framework.
- Checkpoint F remains incomplete for the current Release. One state-Atom run
  reached its later challenge phase before an upstream 503; the next fresh run
  failed before witness execution with `auth_unavailable` for the configured
  Luna route. No current-release TaskPack is claimed.
