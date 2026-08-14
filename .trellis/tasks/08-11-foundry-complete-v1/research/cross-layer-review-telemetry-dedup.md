# Cross-Layer Review: telemetry dedup by (work, operation) identity (diagnosis 16)

- **Decision: block**
- **Plan digest:** `2f02baff` (sha256 of plan file content, first 8 hex)
- **Plan revision:** 1
- **Scope classification:** coordinated cross-node (telemetry compiler -> Registry cold verify)
- **Revision count:** 1 of 2 allowed
- **Trigger:** e2e resume terminal `telemetry_operation_duplicate` on
  run_386e4f07c70d4f61be9cafbf82edcc55 — first Judge-passing run; package node
  aborted release at the telemetry compile step.
- **Diagnosis evidence:** _compile_telemetry (candidate.py 2328-2398) raises
  `telemetry_work_record_duplicate` (2343) and `telemetry_operation_duplicate`
  (2354) on repeated digest. research_acquire work 50caf18240e6 references the
  same OperationEvidence digests repeatedly (1 search + 6 fetch + 6 extract),
  every fetch ref digest ce207f737..., every extract 1a09c46.... OperationEvidence
  (contracts.py 177-184) carries no per-operation discriminator — fields are
  category, node_id, model, usage, skill_digest only — so one-fetch-per-source
  produces byte-identical evidence and thus identical digests. Digest identity is
  the wrong dedup key.
- **Affected trust boundary:** framework telemetry compiler candidate.py
  _compile_telemetry AND the Registry cold-verify telemetry cross-check
  (candidate.py 3277-3295 and 3378), which both deterministically recompute /
  validate the same summary.
- **Repeated product target:** natural-language need -> evidence-grounded
  executable environment -> independent isolated verification -> immutable
  Registry EnvironmentPackage -> safe Observe facts. This repair unblocks the
  package->Registry handoff for the first Judge-passing run without weakening the
  anti-inflation invariant ("the same operation is never counted twice").
- **Impact chain:** _compile_telemetry -> release.telemetry_summary artifact ->
  _package_metadata evidence/telemetry.json (2587) -> envpkg telemetry_digest ->
  package bytes -> Registry _cold_verify (3277-3295 exact-key validation) +
  Registry re-derivation at 3378.
- **Owners:** framework telemetry compiler (single owner); Registry cold-verify is
  the downstream consumer-owner that recomputes the same value.

## Compatibility facts (verified)

- OperationEvidence has no per-operation discriminator; digest collisions across
  distinct real fetch/extract operations are legitimate. Diagnosis is correct.
- No test references `telemetry_work_record_duplicate` /
  `telemetry_operation_duplicate` (grep returns only the two raise sites in
  candidate.py). Replacing them with skip semantics won't break existing tests.
- There are currently NO unit tests for _compile_telemetry; the plan's tests would
  be the first.

## Critical contradiction (blocking)

The plan (Change 1) adds two NEW top-level keys to the telemetry summary —
`deduplicated_work_refs` and `deduplicated_operation_refs` — claiming "the
Registry recomputes the same value." This is FALSE for the actual code:

- candidate.py 3277-3285 (_cold_verify, the Registry node) enforces an EXACT key
  set: `set(telemetry) != {"schema_version", "category_counts", "model_counts",
  "operations"}` or it raises `registry_telemetry_mismatch`.
- candidate.py 3378 additionally requires `telemetry_value ==
  _compile_telemetry(store, design.work_refs, manifest.work_refs)` — a
  deterministic recompute.

Adding the two counters changes the returned dict shape, so the summary's exact-key
predicate at 3280 fails, the recompute at 3378 diverges from stored telemetry, and
the Registry rejects the package — the very node this plan must unblock. Either the
counters must NOT be new top-level keys (derive them inside the existing projection,
or drop them and log the skip counts separately — counters are a feedback gap, not a
release-integrity fact), or the plan must be reclassified as coordinated cross-node
and also change the Registry exact-key predicate and the 3378 recompute in the same
plan. As written it is a self-contradictory node-local patch.

## Unproved consumers

- Registry cold verification (3277-3295 + 3378) — plan claims it "recomputes the
  same value" without accounting for the exact-key/equality checks.
- The "303 tests stay green" claim was not re-verified here; no direct assertion
  exists on the summary shape beyond the registry_mismatch branch, but the new-key
  change is exactly what that branch will catch.

## Smallest allowed implementation and proof plan

1. Narrow the change to dedup KEY + SKIP semantics only: work level skip on repeated
   work digest; operation level dedup by (work_digest, operation_digest) within each
   work. Do NOT add new top-level summary keys. If skip-count observability is
   wanted, route it through existing feedback/observability (a non-schema channel)
   or add the counts inside category_counts/model_counts/operations projection with
   an explicit Registry-key update in the SAME plan.
2. Deterministic checks: unit tests (new) for _compile_telemetry covering (a) repeated
   operation digest within one work -> counted once; (b) same digest across two
   works -> both count; (c) repeated work digest -> skipped once. Existing suite stays
   green.
3. True-boundary proof: pure `uv run agent-world generate --resume
   run_386e4f07c70d4f61be9cafbf82edcc55`; package re-runs; stop at first new
   terminal; Registry receipt remains the only release verdict.

## Explicit non-claims

- No change to OperationEvidence schema, persistence, or secrets posture.
- No change to Judge, verifier, package entry-set, or Registry authority.
- Skip dedup resolves the acknowledged correct-terminal (legitimate repeated
  evidence), not a hidden failure; Registry publication has never run and remains
  the next untested boundary (per diagnosis "What remains unknown").

## Next permitted gate

Plan revision 2 must resolve the exact-key/recompute contradiction (either drop the
new top-level keys, or coordinate the Registry predicate change in the same plan),
then re-submit to this critic.

## Actionable feedback (verbatim for plan writer)

BLOCKED — failed criterion: "Is the scope honest / does each changed field retain
one owner and survive the downstream chain?" Your Change 1 adds two new top-level
keys (`deduplicated_work_refs`, `deduplicated_operation_refs`) to the telemetry
summary and claims "the Registry recomputes the same value", but candidate.py
3277-3285 enforces an exact key set
`{"schema_version","category_counts","model_counts","operations"}` via
`registry_telemetry_mismatch`, and 3378 requires `telemetry_value ==
_compile_telemetry(...)`. Both will fail once the keys are added, so your patch does
not unblock release — it moves the failure from the package node to the Registry
node. Missing/contradictory fact: the Registry is a downstream consumer-owner of the
summary shape, not a passive recomputer. Affected chain: _compile_telemetry ->
release.telemetry_summary -> evidence/telemetry.json -> envpkg telemetry_digest ->
Registry _cold_verify (3280 exact-key, 3378 recompute). Smallest scope change
(allowed, pick ONE): (a) keep the fix to dedup-key + skip semantics only — do not add
new top-level summary keys; surface skip counts through the existing
feedback/observability channel instead of the signed summary, OR (b) keep the counters
but reclassify as coordinated cross-node and in the SAME plan update the Registry
exact-key predicate (3280) and confirm the 3378 recompute includes them. Do not
submit a node-local patch that broadens the producer projection while leaving the
Registry consumer frozen. Next proof: after revision, pure --resume on
run_386e4f07c70d4f61be9cafbf82edcc55 through the Registry receipt (or next honest
terminal).
