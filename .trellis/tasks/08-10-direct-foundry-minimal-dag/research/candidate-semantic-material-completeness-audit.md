# Research: CandidateGraph semantic material completeness audit

- Query: Read-only CandidateGraph semantic-identity audit for `/home/kelong/pycodes/foundry-direct-graph`, including every CandidateGraph `GraphRunner.execute`/terminal path in `candidate.py`, and the absence of such calls in `runtime.py` and `foundry.py`. Assess exact input refs, actual immutable executor-visible values, `semantic_material`, semantic revision sensitivity, Registry cold-read, and Observe downstream facts.
- Scope: internal
- Date: 2026-08-11
- Model boundary: `gpt-5.6-terra/max` was treated as the requested Agent model identity to audit; no model was invoked. The finding applies to any `AgentRoute.model`, including that value.

## Findings

### Evidence basis and files found

| File | What was checked |
| --- | --- |
| `AGENTS.md` | Product goal, source-of-truth precedence, Direct trust path, and read-only constraints. |
| `docs/agent-world-environment-generation.zh.md:109-113,969-990` | Canonical requirement: semantic identity binds effective Prompt/input, output model, Runtime Skill, profile-materialization and validator/acceptance surfaces; package is a portable cold-verifiable closure. |
| `docs/direct-rewrite-execution-map.zh.md:49-60,77-100` | Each node is exact refs -> minimum projection -> one operation -> validation -> commit; CandidateBuild/Integration/Judge authority separation. |
| `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,implement,node-contracts}.md` | Binding task contracts, especially `design.md:201-204,302-321`, `implement.md:48-60,223-257`, and `node-contracts.md:25-56,449-558,656-738`. |
| `.trellis/spec/agent_world/backend/index.md:576-591,619-634` | Local semantic/acceptance identity guidance and Agent Prompt/Skill boundary. |
| `agent_world/graph.py:232-375,442-461,463-809` | Candidate node/edge declarations; semantic digest; exact port cold-read; execute/fail/not_run persistence. |
| `agent_world/candidate.py:554-706,753-1710,1870-1940,2388-2462,2854-3018` | All CandidateGraph handlers, telemetry, package cold-read, Registry verification and publication. |
| `agent_world/invocation.py:165-309,364-367` | Actual Agent route model, composed prompt, isolated Skill mounting, and Skill closure digest. |
| `agent_world/runtime.py:38-76,653-847` | Frozen private-case/process inputs; no direct GraphRunner terminal call. |
| `agent_world/foundry.py:27-104` | Composition root; no direct GraphRunner terminal call. |
| `agent_world/observe.py:76-268,381-536` | Registry/package cold-read projection and safe WorkRecord projection. |
| `tests/test_graph_contracts.py`, `tests/test_direct_release.py`, `tests/test_agent_route_config.py` | Existing port, visible-file, cold-read, route, and not-run coverage. No execution was run for this audit. |

External references: none. The only versioned runtime reference used here is the task's local `openai-codex==0.144.4` contract (`implement.md:91-123`), not an external documentation claim.

### Review rule: closure is not projection identity

`GraphRunner._resolve_inputs` cold-reads and records ordered port refs (`agent_world/graph.py:598-670`), and `execute` persists those same refs in both the envelope and `WorkRecord` (`agent_world/graph.py:569-595`). This is an **exact dependency closure** and is broadly sound.

It is separate from `semantic_revision_digest`: `GraphRunner.semantic_revision` hashes only the supplied `semantic_material` plus static `NodeSpec` fields (`agent_world/graph.py:442-461`). A value is adequately covered only when it is either:

1. explicitly in that material; or
2. deterministically and completely represented by a materialized immutable ref/value that the handler actually consumes.

Recording a ref in `dependency_refs` alone does not make a changed executor-visible projection change `semantic_revision_digest`.

### CandidateGraph pass/gap matrix

`P` means the named value is adequately represented under the current Direct path. `G#` links to a real gap below. `NC` is an explicit non-claim, not a requested repair.

| Node | Exact graph inputs and actual values consumed | Current semantic material | Pass / gap result |
| --- | --- | --- | --- |
| `build_plan` | `design -> design.artifact` (`candidate.py:832-846`). Agent reads canonical `design.json` projection and `implementation-contract.json` (`810-825`), with the mounted Skill, composed prompt, resolved Agent model, and possible correction packet. | `design` digest, `projection`, `implementation_contract` (`840-844`); `NodeSpec` adds label `build-plan@1` and Skill digest. | P for Design ref + both visible JSON values. G1 Agent model/prompt/profile identity; G2 correction identity; G3 compiler/validator executable identity. |
| `candidate_build` | `design -> design.artifact`, `build_plan -> plan.artifact` (`888-903`). Agent reads exact bytes of `inputs/design.json`, `inputs/implementation-contract.json`, `inputs/build-plan.json` (`857-877`). Framework scans physical source (`909-952`). | `design` digest, `build_plan` artifact digest, `implementation_contract` (`896-900`). | P for implementation contract and Plan artifact in the canonical unmutated in-process path. G1, G2, G3. G4: the separately written `design.json` projection is not represented. See NC-1 for the in-memory `plan.value` equality caveat. |
| `integration` | `design`, `candidate` (`1005-1019`). It consumes Design recipes/tasks/schemas/tools, candidate source root, and fresh admitted dependency closure (`963-1003`; `supply_chain.py:445-523`). | Design ref, Candidate ref, Candidate source digest (`1013-1017`). | P for exact Design/Candidate/source closure. The trusted wheel path, temporary venv path, installer cache, and retry mechanics are validation transport, not semantic inputs; source/lock/wheel mutation is checked and admitted closure is emitted. G3 for the acceptance executable itself. |
| `verifier_intent` | `design -> design.artifact` (`1155-1172`). Agent reads only canonical `public-design.json` catalog (`1024-1039`); private cases are later deterministically derived. | Design ref + `catalog` (`1163-1166`). | P for catalog and public-visibility boundary. G1, G2, G3. |
| `judge` | `design`, `candidate`, `integration`, `verifier` (`1320-1340`). It cold-reads verifier/integration, validates deterministic private cases, prepares a fresh candidate, and executes Judge (`1254-1318`). | Digests for all four refs (`1333-1338`). | P for direct inputs. Private cases are deterministically derived from Design + persisted commitments (`1128-1227`) and then validated; no separate persisted case ref is needed. G3 for Judge/validation executable identity. |
| `package` | `design`, `candidate`, `integration`, `judge`, `verifier`, two lineages, plus ordered Design/Candidate WorkRecord refs (`1558-1585`). It reads work records to produce telemetry (`1488-1556`, `1870-1940`). | First seven major refs only; **omits both WorkRecord lists** (`1576-1584`). | P for source closure, passed evidence, lineages and SBOM inputs as represented by their refs/output checks. G3. G5: WorkRecords are actual telemetry inputs, not redundant graph decoration. |
| `registry` | Package, Design, Candidate, Integration, Judge, Verifier, physical package, dossier, telemetry, lineages, and both WorkRecord lists (`1652-1684`). It cold-reads `physical_package`, then rebuilds expected package metadata/telemetry (`1610-1650`, `2854-2975`). | Package, dossier, integration, judge, verifier, telemetry, lineages; **omits physical package and both WorkRecord lists** (`1674-1683`). | P for cold-read of the submitted ZIP and exact Design/Candidate/Integration/Judge/Verifier closure inside a coherent package. G3 and G5. G6 is a true physical-release blocker: the submitted physical ZIP is never compared with Package's committed `physical_package_ref`. |

### `execute`, `fail`, `not_run`, runtime, and composition-root paths

- `GraphRunner.execute` resolves exact refs first and passes the same `semantic_material` into `fail` if execution/compilation fails (`graph.py:482-540`). Its passed envelope and failed WorkRecord therefore have correct input/dependency closure, but inherit G1-G5 where applicable.
- `GraphRunner.fail` records its supplied inputs, evidence and Finding (`graph.py:700-780`). Failure code/evidence are terminal output facts, not hidden model/process inputs; no separate semantic-material field is required for them. If a correction was actually used before a terminal failure, G2 applies to `fail` as well.
- Every unreachable Candidate node is recorded by `graph.not_run` through `CandidateExecutor._not_run` (`candidate.py:570-706`). `not_run` has empty input/dependency refs and hashes only `{"not_run": true}` (`graph.py:782-809`). **Pass:** it consumes no executor/model/candidate input; its upstream safe code is a reason field, not a semantic projection.
- `runtime.py` and `foundry.py` contain no `GraphRunner.execute`, `.fail`, or `.not_run` call. Runtime receives the immutable values supplied by the Candidate handlers; Foundry only composes Design then Candidate and records their WorkRecords (`runtime.py:38-76,653-847`; `foundry.py:37-69`).

### Real gaps, minimal field-level repair, and regression proof

No recommendation below adds a node, graph, schema family, Repair/Expand/Consumer path, compatibility path, reflection mechanism, or generic framework. Each is a field added to the existing per-node semantic material / existing equality check.

| ID and severity | Evidence and impact | Smallest field-level repair | Minimum regression |
| --- | --- | --- | --- |
| **G1 — semantic-identity blocker** for all Agent nodes | `NodeSpec` stores only static labels (`build-plan@1`, `verifier-intent@1`, `candidate-build@1`) (`graph.py:232-265`), while revision hashes that label and route string only (`442-461`). Actual Agent invocation composes wrapper + instruction (`invocation.py:239-244`) and supplies `route.model` to the SDK (`291-302`); the returned model is merely operation evidence (`candidate.py:741-745`). Thus changing the effective prompt, resolved model (including `gpt-5.6-terra/max`), or materialization surface can leave the semantic revision unchanged. | For each of `build_plan`, `candidate_build`, `verifier_intent`, add one explicit non-secret `agent_semantic_surface` field containing: `resolved_model`, `effective_prompt_digest` (wrapper + node instruction, never body), and `profile_materialization_revision`. Keep existing Runtime Skill digest; do not add base URL, credential, retry ordinal, or workspace path. | For each Agent node, hold graph refs/output shape/Skill fixed, change one of model, prompt digest, or materialization revision, and assert the terminal envelope and WorkRecord revision differ. A base-URL/key/retry-only change must not be asserted semantic. |
| **G2 — semantic-identity blocker** for the three Agent nodes and their terminal `fail` path | All three use `operation(correction)` and append the canonical correction packet to the actual instruction (`candidate.py:708-731,815-825,865-877,1029-1039`). Every Candidate Agent node permits one local correction by `NodeSpec` default/setting (`graph.py:49,232-266`). The runner calculates one revision before the retry loop and never adds the actual correction packet (`graph.py:482-516`). | Add `authorized_correction: null | digest(canonical CorrectionPacket)` to the **terminal** semantic material used by the successful or failed corrected attempt. It must be `null` for an uncorrected attempt. | Drive a first rejected compiler result followed by a corrected valid result; mutate only the correction packet and assert final revision differs. Repeat for a terminal failure after correction and assert its failed WorkRecord revision differs. |
| **G3 — semantic-identity blocker** for every executed Candidate node | The canonical source requires an explicit validator/acceptance executable revision (`environment-generation.zh.md:111`; backend guide `index.md:576-591`). `semantic_revision` does not hash operation/compiler/validator/Judge/Registry executable identity (`graph.py:442-461`). This includes BuildPlan validation, Candidate scan/compiler, Integration/prepare-candidate, verifier compiler/private-case validator, Judge, Package assembly/telemetry, and Registry cold verification. | Add one explicit, node-local `acceptance_executable_revision` field to each existing execute material mapping. It names the exact handler/compiler/validator surface for that node; it is not automatic source reflection and it does not introduce a new schema. | Parameterize the seven existing handler-level semantic-material tests: changing only that node's explicit executable revision changes its semantic revision; unchanged value preserves it. Include one Registry cold-validator revision and one Candidate scan/compiler revision. |
| **G4 — semantic-identity blocker** for `candidate_build` | CandidateBuild writes and exposes `_projection(design)` as `inputs/design.json` (`candidate.py:857-863`) but its material does not contain that projection (`896-900`). A projection-code change can alter Agent-visible bytes while the Design ref and implementation contract remain unchanged. BuildPlan already correctly includes its own projection (`840-844`). | Add `design_projection: <canonical projection digest>` (or the canonical projection value) beside existing CandidateBuild fields. Use the exact bytes written to `inputs/design.json`. | Keep the Design artifact and implementation contract fixed, change only the CandidateBuild projection fixture/override, and assert the CandidateBuild revision changes. |
| **G5 — semantic-identity blocker** for `package` and `registry` | Ordered WorkRecord refs are declared graph inputs (`graph.py:286-325`) and are read to construct/recompute telemetry (`candidate.py:1495,1870-1940,2926-2928`). Package and Registry omit both lists from their semantic material (`1576-1584,1674-1683`). The exact dependency list remains persisted, but does not affect semantic revision. | Add ordered `design_work_record_digests` and `candidate_work_record_digests` fields to Package and Registry semantic material. Use the exact ordered input-ref digests, not a summarized telemetry count. | Substitute one valid WorkRecord ref while keeping major evidence refs fixed; assert Package and Registry semantic revisions differ. Retain the existing cold-read test that rejects telemetry inconsistent with the selected WorkRecords. |
| **G6 — true physical-release blocker** at `registry` | Package commits `physical_package_ref` in its payload (`candidate.py:1551-1556`). Registry checks only dossier and telemetry equality, then cold-reads the separately supplied `physical_package` (`1611-1621`); it never checks `package_payload["physical_package_ref"] == _ref(physical_package)`. The physical ZIP is also omitted from Registry semantic material (`1674-1683`). A different byte-level-valid ZIP with the same manifest/entries can therefore be published as Registry output even though Package committed another physical ref. Observe then verifies the actually published ZIP, not the missing Package-to-ZIP equality. | Before cold-read, require `package_payload["physical_package_ref"] == _ref(physical_package)` and reject a mismatch with a closed Registry code. Add `physical_package_digest` to Registry semantic material. No new artifact or graph edge is needed; both values already exist. | Create two byte-distinct but individually valid ZIP containers with the same expected manifest/entries. Pass the second ref with the first Package envelope and assert Registry rejects before publication; changing only the physical ref must change Registry revision. Assert Observe returns no `released` fact for that rejected run. |

### Values adequately represented by exact dependency closure (no repair requested)

- Named ports, producer/edge provenance, media type, and ordered refs are already validated and persisted (`graph.py:598-670,569-595`). This is a pass for all seven nodes.
- Integration's Candidate source closure is represented by Candidate manifest ref + source digest, while dependency installation validates input immutability and exact admitted distributions (`candidate.py:1013-1017`; `supply_chain.py:451-523`). The wheel-store path, temporary directories, cache path, and invocation retry are not release semantics.
- Judge private cases need no ArtifactRef: they are deterministically computed from the exact Design artifact digest and persisted verifier commitments, then validated before execution (`candidate.py:1128-1227,1254-1273`).
- Package's physical candidate source, lock, SBOM, Design/Candidate/Integration/Judge/Verifier refs, and lineages are rechecked by Registry cold-read (`candidate.py:2388-2462,2854-2975`). They need not be duplicated merely because they appear in more than one closure.
- At Registry, Design/Candidate are represented again inside the Package manifest and checked by `_cold_verify`; their omission from Registry's own material is not separately called a gap here. G6 is different because the Package payload's already-existing physical ref is not compared with the physical input actually published.
- Observe safely projects WorkRecord dependency/output/finding Artifact IDs as required by the task contract (`observe.py:381-445`) and independently rechecks receipt/package facts before exposing `released` (`76-268,498-536`). It intentionally does not expose prompt bodies, private cases, credentials, or full source.

### Cold-read and Observe conclusion

Registry's package parser is materially strong: it rehashes bytes, verifies every ZIP entry, canonical metadata, source closure, and SBOM (`candidate.py:2388-2462`), then rebuilds expected metadata, evidence, telemetry, lineages, and exact passed closure (`2854-2975`). Observe independently reopens the Registry package/receipt and validates the release handoff (`observe.py:76-268`).

Those protections make current package/Registry/Observe behavior **precise for the submitted physical package**, but they do not repair G6's missing equality between that submitted package and Package's committed physical output. Fix G6 before claiming that Registry publication is the exact Package-node physical result. Fix G1-G5 before claiming complete semantic-revision identity.

### Non-claims

- This is a static audit, not a real execution proof, a diagnosed production failure, or a claim that a malicious substitution has occurred.
- No claim is made that a current released package is invalid; G6 identifies an unguarded admissible input substitution, not observed corruption.
- No claim is made that `NodeResult.value` is mutated on the current normal path. CandidateBuild writes `plan.value` rather than cold-reading its envelope, but its `plan.artifact` is the canonical compiled plan in the current internal flow. This is **NC-1**, not a requested repair. If future callers permit a divergent mutable `NodeResult.value`, explicitly compare it with the committed plan payload at the boundary.
- No claim is made that base URL, API key, temporary workspace path, SDK retry count, cache path, or wheel-store location must enter semantic identity. They are transport/operational values unless they change the Agent-visible Prompt/Skill/model or acceptance executable.
- No new graph node, generic workflow/reflection mechanism, Repair/Expand/Consumer route, schema, or compatibility path is proposed.

## Caveats / Not Found

- The requested “latest final whole-diff block” was not available in the readable task markdown/spec set. This research role is prohibited from reading task `implement.jsonl`/`check.jsonl` and from git operations, so the report audits the checked current target-tree code rather than asserting a diff-specific review.
- No code, tests, task plans, existing documents, configs, artifacts, or git state were modified; only this research file was written.
- No model call, Registry publication, test suite, or Observe run was executed. The listed regressions are the smallest proof obligations for a later authorized implementation/check phase.
