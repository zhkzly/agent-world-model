# Research: cross-layer-review-fc89e935-graph-fail-zip

- Query: Judge whether plan `fc89e935c0835c5c403927e55948d20ff720ee0e66feb027d24b88c50e24cc24` is the smallest correct repair for a Registry physical-package mismatch that cannot persist its failed `WorkRecord` because `GraphRunner.fail` cold-reads a valid ZIP dependency as JSON.
- Scope: internal, read-only cross-layer critic; only the existing `GraphRunner.fail` JSON/ZIP cold-read loop and its focused regression.
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `fc89e935c0835c5c403927e55948d20ff720ee0e66feb027d24b88c50e24cc24` (verified against `graph-fail-media-type-plan.md`).
- Plan lineage / revision: `graph-fail-media-type`, revision 1/2; this is the first review of this digest.
- Scope classification: local failure-path persistence correction.  It changes neither the `ArtifactRef`/`WorkRecord` schema nor Registry acceptance, publication, owner, route, retry, or package semantics.
- Trigger and evidence: deterministic focused Registry-mismatch test terminal only.  The persisted diagnosis and PAC-65 explicitly say no real product run or Observe scene exists; none is inferred here.
- Affected trust boundary: framework-owned GraphRunner integrity re-read of already-resolved inputs before it commits the existing Validation, Finding, and failed Registry `WorkRecord`.

## Product target and impact chain

The preserved target is: an arbitrary natural-language `EnvironmentRequest` becomes an evidence-grounded executable environment, independently verified in an isolated boundary, released by Registry as an immutable `EnvironmentPackage`, with only safe durable facts exposed by Observe.  This repair advances only the honest non-release evidence portion of that chain; it is not a release or E2E claim.

```text
valid ZIP ArtifactRef on Registry physical_package port
  -> GraphRunner._resolve_inputs cold-reads bytes and verifies its digest
  -> CandidateExecutor._registry detects physical-ref inequality before _publish
  -> NodeExecutionError(registry_physical_package_mismatch)
  -> GraphRunner.execute calls GraphRunner.fail with the exact resolved dependencies
  -> fail re-cold-reads JSON as JSON/envelope and ZIP as bytes
  -> existing Validation + Finding + failed registry WorkRecord
  -> unchanged CandidateError/non-release handling; Observe can project the durable record
```

`_resolve_inputs` already implements the closed two-media rule: JSON is read through `read_json` and optional envelope validation; ZIP is read through `read_bytes`; every other media type raises `graph_input_media_type_invalid` (`agent_world/graph.py:634`, `agent_world/graph.py:637`, `agent_world/graph.py:641`).  `fail` currently uses only `read_json` (`agent_world/graph.py:725`), so the ZIP dependency reaches `ArtifactStore.read_json` and is rejected as `artifact_not_json` (`agent_world/artifacts.py:405`).

The Registry operation checks physical-package ref equality before reading or publishing (`agent_world/candidate.py:1613`-`1616`), and calls the existing graph transaction with that ZIP input (`agent_world/candidate.py:1657`-`1694`).  The existing regression creates a different but integrity-valid ZIP, asserts the safe mismatch, prevents `_publish`, and expects the failed Registry work/finding (`tests/test_direct_release.py:1119`-`1154`).  Therefore the proposed branch restores the intended failure record; it does not weaken Registry's cold-read or publication boundary.

## Owner and consumer compatibility

| Owner / consumer | Compatibility fact |
| --- | --- |
| GraphRunner | `execute` already resolves inputs before invoking the operation and calls `fail` on terminal `NodeExecutionError` (`agent_world/graph.py:482`, `agent_world/graph.py:496`-`539`). The change only makes `fail` revalidate the same already-accepted ZIP media type. |
| ArtifactStore | `read_bytes` revalidates the closed ref/path/media-type/digest before returning bytes (`agent_world/artifacts.py:387`-`403`); JSON retains the existing `read_json` and envelope checks. No new media type or decoding rule is introduced. |
| Registry | Registry stays the sole physical re-verifier/publisher. The mismatch remains pre-publication and keeps the same safe code, Finding owner, subject, evidence, and failed `WorkRecord` shape (`agent_world/graph.py:749`-`778`). |
| CandidateExecutor / Controller | The original `NodeExecutionError` is still rethrown after `artifact_refs` receives the failed work (`agent_world/graph.py:537`-`539`); CandidateExecutor continues its existing terminal conversion (`agent_world/candidate.py:670`-`676`) and Controller remains the non-release owner (`agent_world/foundry.py:53`-`68`). |
| Observe | No projection contract changes. Observe already discovers persisted `control.work_record` and Finding artifacts even when they were not added to the run's ordered refs (`agent_world/observe.py:381`-`445`, `agent_world/observe.py:448`-`495`). |
| Repair / Expand / Consumer | Not modified and not blockers. They receive no new field, type, release fact, or package; the repaired failure record uses the frozen existing provenance schema. |

The `WorkRecord` contract requires failed work to carry validation plus a Finding (`agent_world/contracts.py:193`-`224`; task `node-contracts.md:35`-`74`).  The plan restores that existing requirement for a valid binary dependency instead of inventing a special Registry path.

## Smallest permitted implementation and proof

1. Change only the `for ref in inputs` loop in `GraphRunner.fail` (`agent_world/graph.py:725`):
   - `application/json` -> existing `read_json`, then existing envelope validation when applicable;
   - `application/zip` -> `read_bytes`;
   - anything else -> existing closed code `graph_input_media_type_invalid`.
2. Add one focused `tests/test_graph_contracts.py` regression that gives `fail` an integrity-valid ZIP dependency and asserts the existing validation, Finding, and failed `WorkRecord` shape.
3. Retain the existing Registry physical-package mismatch regression as the smallest constructed true-boundary proof: it exercises `_registry -> graph.execute -> fail`, proves no publication, and proves the Registry work is failed with `registry_physical_package_mismatch`.

Do **not** introduce or extract a helper.  There are only two context-specific call sites, the relevant low-level helpers already exist (`ArtifactStore.read_json` / `read_bytes`), and a new shared helper would alter `_resolve_inputs`' error/order surface without reducing a real cross-layer risk.  It would violate the plan's explicit minimality boundary without improving ownership or compatibility.

The plan's focused suites followed by its prescribed full deterministic checks are sufficient before a new whole-diff review.  No live Provider, Candidate, Judge, Registry-publication, Repair, Expand, or Consumer proof is required or authorized by this allow.

## Files found

| Path | Relevance |
| --- | --- |
| `AGENTS.md` | Requires source-of-truth precedence, independent critic gate, and fail-closed evidence. |
| `.trellis/workflow.md` | Defines critic-before-implementation and the deterministic-failure distinction. |
| `docs/agent-world-environment-generation.zh.md` | Source of truth: immutable Artifact DAG, framework-owned non-release/release authority, Registry cold verification. |
| `docs/direct-rewrite-execution-map.zh.md` | Derived execution map: one deterministic runner, Registry may honestly terminally reject, Observe is read-only. |
| `.trellis/spec/agent_world/backend/index.md` | Relevant strict input-closure and frozen graph-completeness guidance. |
| `.trellis/spec/guides/foundry-product-alignment.md` | Requires the product target, evidence/non-claims, and next permitted gate. |
| `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,implement,node-contracts}.md` | Current Direct graph, failed-WorkRecord, Registry, and no-new-framework constraints. |
| `research/diagnosis-graph-fail-zip-dependency.md` | Static diagnosis of the exact JSON-only failure loop. |
| `research/graph-fail-media-type-plan.md` | Reviewed bounded plan, revision 1/2. |
| `research/product-alignment-checkpoints.md` | PAC-65 records the same static blocker and non-claims. |
| `agent_world/graph.py` | Existing resolver, execute/fail transaction, and Registry node declaration. |
| `agent_world/artifacts.py` | Closed JSON/ZIP artifact integrity readers. |
| `agent_world/candidate.py` | Registry mismatch origin and downstream terminal handling. |
| `agent_world/foundry.py` | Controller's unchanged non-release terminal handling. |
| `agent_world/observe.py` | Safe durable WorkRecord/Finding projection. |
| `tests/test_graph_contracts.py` | Existing JSON/ZIP input-rule regression surface. |
| `tests/test_direct_release.py` | Existing actual Registry mismatch/no-publication regression. |

## Related specs and references

- Source-of-truth product/Registry constraints: `docs/agent-world-environment-generation.zh.md:198`-`215`, `:596`-`613`, `:1001`-`1005`.
- Static graph and ownership constraints: `docs/direct-rewrite-execution-map.zh.md:30`-`60`, `:84`-`88`, `:164`-`181`.
- Task contracts: `node-contracts.md:12`-`74`, `:777`-`786`; Design CandidateGraph ownership: `design.md:113`-`141`, `:319`-`341`.
- External references / versions: none consulted; this is an internal closed-media contract. The task's `openai-codex==0.144.4` pin is unrelated to this deterministic artifact-read repair.

## Caveats / Not Found

- No test was run: the requested role is read-only and the terminal is a static deterministic regression, not a live scene. This report relies on source, diagnosis, plan, and test-path inspection.
- `read_bytes` verifies artifact integrity, not ZIP archive semantics; that is intentionally sufficient for GraphRunner and leaves package structure validation to Registry's existing cold-read boundary.
- This allow expires if the plan digest, the JSON/ZIP trust boundary, or the relevant terminal evidence changes. The main session must add this matching allow record to the implementation and check context before dispatch.
- No claim is made that a live Direct request, Registry publication, later Repair, Expand, or Consumer path succeeds.
