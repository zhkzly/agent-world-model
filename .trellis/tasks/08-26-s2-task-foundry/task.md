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
- The generic cross-environment Qualification coordinator and filesystem/Git repeat remain incomplete; there is no S2 completion claim.

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
- This is partial Checkpoint F evidence only. Checker mutation remains blocking before any TaskPack claim.
- Repository lock, Ruff, format, Mypy, full Pytest and diff checks are green after the deletion.
