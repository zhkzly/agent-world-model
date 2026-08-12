# Research: cross-layer review — Observe gate evidence addendum R1

- Query: Independent read-only review of revision 1 of the Observe evidence addendum, with particular review of whether its parameterized cold-read interception directly tests Observe's gate-evidence comparison and preserves fail-closed release projection.
- Scope: internal
- Date: 2026-08-11
- Reviewer: fresh independent read-only `trellis-research`

## Decision

Decision: allow

- Plan digest (independently recomputed): `3efaf683de4f09a2fd6934aa30476daf2322f7e5c2780cd81fa2375c07f3a2cf`.
- Plan revision: `Minimal R2 addendum — close Observe gate evidence`, revision 1.
- Revision count: 1 of at most 2 for the `diagnosis-r2-observe-gate-evidence.md` lineage; it directly addresses predecessor block `9ee47ea9`.
- Scope classification: coordinated cross-node consumer-closure repair. The only product edit is local to Observe, while the consumed contract crosses Designer -> Judge -> Registry -> Observe.
- Trigger and evidence: persisted diagnosis reports two otherwise valid R2 releases downgraded to `not_published` because Observe still universally expects the pre-R2 four-field Judge evidence object. The upstream R2 review `c69de83b` permitted the Design/Judge/package/Registry assurance closure; this is a distinct downstream drift. No new real scene, test execution, model invocation, or network action was performed for this review.

## Product Target, Scope, and Impact Chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

```text
immutable Design.local_rule_assurance
  -> Judge local_tool_semantics gate evidence
  -> package / ReleaseDossier
  -> Registry cold verification and atomic publication
  -> Observe cold re-read and safe released | not_published projection
```

The addendum advances only Observe's final read-only consumer check. It does not make run status, a Judge report, package bytes, or a Registry receipt sufficient by itself, and does not alter Direct execution, Judge, package construction, Registry policy, Repair, Expand, or Consumer.

## Owners and Compatibility Facts

- Designer/framework owns the compiled assurance: `agent_world/design.py:1741-1761` creates and persists `LocalRuleAssurancePlan` in immutable Design payload.
- Judge/framework owns individual gate evidence: `agent_world/candidate.py:1239-1258` permits assurance only on `local_tool_semantics` and persists it as `judge.gate_evidence`.
- Registry remains the release/cold-read owner and already requires exact conditional evidence equality from that Design-owned assurance: `agent_world/candidate.py:2528-2580`, especially `2560-2577`.
- Observe is the downstream safe read-only consumer. It cold-reads each gate evidence at `agent_world/observe.py:198-206`, then currently uses universal four-field equality at `257-266`; the one-site conditional expected-object update restores compatibility with the Registry rule without expanding the artifact ABI.
- `ArtifactStore.read_json` verifies reference, bytes digest, canonical envelope, kind, and safe payload before returning payload (`agent_world/artifacts.py:405-425`). Therefore no persistent artifact can bypass the normal integrity boundary.
- Repair, Expand, and Consumer do not consume a changed package, lineage, Runtime, or public API field. Their relevant compatibility fact is that the immutable package and Registry handoffs stay unchanged; only the existing Observe projection expectation becomes consistent with Registry.

## Direct Evidence-Comparison Regression

The revised parameterized strategy is sufficient and directly exercises the changed consumer boundary, provided the test implements the stated narrow interception:

1. Start from the existing `_release_candidate` fixture, whose Judge produces one normal gate and one `local_tool_semantics` gate carrying the Design-derived assurance (`tests/test_direct_release.py:273-286`). Persist a released `DirectRun` and assert the unmodified Observe result is released.
2. Monkeypatch only `ArtifactStore.read_json` for the Observe cold read, delegate to the original method first, and return a copied/modified payload only when the requested reference is a `judge.gate_evidence` artifact. Since `observe_run` creates a fresh `ArtifactStore` (`agent_world/observe.py:421-433`), a class-method interception reaches that real cold-read instance.
3. Parameterize exactly the four revised cases: absent local assurance, altered local assurance value, assurance added to non-local evidence, and an unrelated extra local-evidence field. Each must project exactly `{"status": "not_published"}`.

This does not merely produce `ArtifactIntegrityError`: the original reader completes digest/canonical validation before the in-memory altered payload is returned. All preceding package, receipt, Design, candidate, integration, Judge-report, verifier, dossier, telemetry, and lineage checks therefore retain their valid fixture values. The altered value first becomes relevant in the `zip(judge["gates"], gate_evidence, strict=True)` exact-object comparison at `agent_world/observe.py:257-266`. The four cases consequently prove absence, value drift, widening to another gate, and unrelated extra shape all fail closed at Observe's evidence-content rule itself.

Exact dict equality remains the correct rule: it admits the Design-derived assurance only on the one named gate and rejects missing, altered, misplaced, and additional fields. The revised plan introduces no normalizer, subset/superset comparison, default, compatibility route, retry, model call, graph node, second Judge, or release authority.

## Smallest Allowed Implementation and Proof

- Edit only `agent_world/observe.py`: construct the same four required fields, conditionally add the exact `local_rule_assurance` from the already cold-read immutable Design only when `gate_id == "local_tool_semantics"`, and retain exact object equality.
- Edit only `tests/test_artifacts_observe.py`: retain the valid-fixture released assertion and add the four-case parameterized, post-integrity `judge.gate_evidence` interception regression described above.
- Deterministic checks: the valid Observe release case; all four direct evidence-negative cases; existing package/verifier/lineage tamper downgrades; then full pytest, Ruff, mypy, compileall, and diff checks.
- True-boundary proof remains the R2 sequence, not a claim from those deterministic checks: Luna ToolSemantics shard; Candidate/Integration/Judge; fresh Direct E2E ending in terminal Observe. After every terminal, read Observe; any new failure requires a new diagnosis and critic gate.

## Non-claims

This allow does not claim implementation, passing deterministic checks, Registry publication, a live shard, CandidateBuild, Integration, Judge, Direct E2E, dynamic assurance of error/reject behavior, Repair, Expand, Consumer/SFT/RL, or product completion. It does not authorize edits outside the two named files or broaden the reviewed trust boundary.

## Next Permitted Gate

Implementation of this exact digest is permitted, followed by independent check and the stated real-execution proof order. This allow expires if the plan digest, Observe/Judge-evidence boundary, or latest relevant real Observe scene changes. The main planner must add this current allow record to implementation/check context before dispatching work.

## Files Found

- `docs/agent-world-environment-generation.zh.md` — canonical product, artifact, Registry, Judge, and safe Observe requirements.
- `docs/direct-rewrite-execution-map.zh.md:30-88,164-187` — Direct graph and explicit read-only Observe boundary.
- `.trellis/spec/guides/foundry-product-alignment.md` — required product-alignment framing for this boundary.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd.md,design.md,implement.md,node-contracts.md}` — active Direct task contracts and declared downstream seams.
- `research/diagnosis-r2-observe-gate-evidence.md` — persisted causal diagnosis.
- `research/r2-observe-gate-evidence-plan.md` — reviewed revision-1 plan.
- `research/cross-layer-review-9ee47ea9-observe-evidence.md` — predecessor block and requested regression matrix.
- `research/direct-tool-semantics-closure-plan-r2.md` and `research/cross-layer-review-c69de83b-tool-semantics-r2.md` — upstream R2 plan and prior allowed assurance contract.
- `agent_world/{artifacts.py,design.py,candidate.py,observe.py}` — current owner and cold-read implementation evidence.
- `tests/{test_direct_release.py,test_artifacts_observe.py}` — valid release fixture and intended focused test location.

## Caveats / Not Found

- This review intentionally did not read task `implement.jsonl` or `check.jsonl`, mutate production/test/task-plan files, run pytest, or perform model/network calls.
- The worktree contains unrelated pre-existing modifications and untracked task/code files; they were inspected only where necessary for this review and are not covered by this allow.
- The planned interception is deterministic test instrumentation, not an artifact-tampering success path. It must delegate to the original reader first and target only `judge.gate_evidence`; a physical-byte mutation would instead prove the earlier digest-rejection path and would not satisfy this review's evidence-content regression requirement.
