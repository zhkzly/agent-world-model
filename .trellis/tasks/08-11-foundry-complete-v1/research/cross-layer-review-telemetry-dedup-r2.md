# Cross-Layer Review: telemetry dedup by (work, operation) identity (diagnosis 16) — revision 2

- **Decision: allow**
- **Plan digest:** `228a77a0` (sha256 of plan file content, first 8 hex)
- **Plan revision:** 2
- **Scope classification:** local (framework telemetry compiler only)
- **Revision count:** 2 of 2 allowed
- **Trigger:** revision-1 block (digest `2f02baff`) — the counters
  `deduplicated_work_refs` / `deduplicated_operation_refs` would have broken the
  Registry exact key-set cold verify (candidate.py 3280) and the 3378 deterministic
  recompute. Same underlying failure: e2e resume terminal
  `telemetry_operation_duplicate` on run_386e4f07c70d4f61be9cafbf82edcc55 (need
  用户预订宾馆), the first Judge-passing run, aborted at the package node.
- **Diagnosis evidence (re-confirmed):** _compile_telemetry (candidate.py 2328-2398)
  dedups on raw evidence digest. OperationEvidence carries no per-operation
  discriminator, so one fetch/extract per research source produces byte-identical
  evidence and identical digests; the duplicate raise sites fire on legitimate
  repeated operation evidence (2342-2343 work-level, 2351-2354 operation-level).
  Root cause: digest identity is the wrong dedup key.
- **Affected trust boundary:** framework telemetry compiler candidate.py
  _compile_telemetry (producer) -> release.telemetry_summary artifact ->
  evidence/telemetry.json -> envpkg telemetry_digest -> Registry _cold_verify
  (consumer-owner, 3277-3285 exact-key + 3378 deterministic recompute).

## Repeated product target

natural-language need -> evidence-grounded executable environment -> independent
isolated verification -> immutable Registry EnvironmentPackage -> safe Observe facts.
This repair unblocks the package->Registry handoff for the first Judge-passing run
without weakening the anti-inflation invariant ("the same operation is never counted
twice").

## Impact chain

_compile_telemetry (1941) -> release.telemetry_summary (1942) -> _package_metadata
evidence/telemetry.json -> envpkg telemetry_digest -> package bytes -> Registry
_cold_verify exact-key (3280) + recompute (3378).

## Owners

Framework telemetry compiler (single owner: candidate.py _compile_telemetry). Registry
_cold_verify remains the downstream consumer-owner that recomputes the same value under
an unchanged summary shape.

## Compatibility facts (verified against code)

1. Revision 2 DROPS the counter keys entirely. _compile_telemetry returns exactly
   `{"schema_version", "category_counts", "model_counts", "operations"}`
   (2393-2398), byte-shape identical to today. The revision-1 blocking contradiction is
   RESOLVED: no new top-level summary key exists to trip the exact-key predicate.
2. Registry exact key set at 3280 is
   `set(telemetry) != {"schema_version","category_counts","model_counts","operations"}`
   and 3378 requires `telemetry_value == _compile_telemetry(store, design.work_refs,
   manifest.work_refs)`. With the unchanged return shape, BOTH continue to hold.
3. The two duplicate raise sites (2342-2343 work, 2351-2354 operation) are the ONLY
   behavioral changes. All other validation paths (telemetry_work_record_missing,
   telemetry_work_record_invalid, telemetry_operation_ref_invalid,
   telemetry_operation_invalid, telemetry_operation_missing) are untouched.
4. Grep confirms NO test references `telemetry_operation_duplicate` /
   `telemetry_work_record_duplicate` — the only matches are the two raise sites in
   candidate.py. Removing their raise semantics breaks no existing test.
5. NO existing unit test for _compile_telemetry dedup semantics; the plan's new tests
   are the first. Placement is natural in tests/test_direct_release.py (already imports
   `candidate_module` and exercises _cold_verify + release telemetry artifacts) or a
   sibling unit module following the test_design_semantics.py /
   test_judge_gate_semantics.py candidate_module pattern. Existing indirect coverage
   exists: test_direct_release.py produces telemetry summaries through _release_candidate
   and asserts registry receipt; test_graph_contracts.py references "telemetry".
6. Anti-inflation claim VERIFIED by inspection: within a work the same
   (work_digest, operation_digest) is seen once; across two DISTINCT works an identical
   operation digest is keyed differently (by its own work digest) and therefore counts
   once per work. Note the current code actually uses ONE module-scoped
   `seen_operations` set (2339), so today identical digests across distinct works are
   wrongly collapsed; the plan's per-work `(work_digest, operation_digest)` key
   FIXES this, matching the diagnosis intent ("distinct operations are never collapsed
   across works").

## Unproved consumers

- Registry validation itself has never executed at runtime (per diagnosis "What remains
  unknown"): the 3277-3285 exact-key and 3378 recompute paths are the next untested
  boundary. Their shape assertions are deterministic-code-verified as compatible, but
  they have no live run yet.
- The "303 tests stay green" figure was not re-run here; no direct assertion exists on
  summary shape beyond the registry_mismatch branch, and the change is exactly in the
  code that branch validates only at runtime (not unit-asserted).

## Smallest allowed implementation and proof plan

1. Change ONLY dedup key + skip semantics in _compile_telemetry:
   - work level: repeated work digest -> skip (continue), no raise.
   - operation level: key dedup by (work_digest, operation_digest) per work; reset the
     per-work seen set inside the work loop; skip on repeat, no raise.
   - return dict shape unchanged (four keys; schema_version unchanged).
2. Deterministic unit tests: (a) same operation digest repeated within one work ->
   counted once; (b) identical operation digest across two works -> both count; (c)
   repeated work digest -> counted once; (d) returned dict has exactly the four schema
   keys.
3. True-boundary proof: pure `uv run agent-world generate --config
   config/agent-world.example.toml --need "用户预订宾馆" --resume
   run_386e4f07c70d4f61be9cafbf82edcc55`; design/Judge frozen, package re-runs; stop at
   first new terminal; Registry receipt remains the only release verdict.

## Explicit non-claims

- No change to OperationEvidence schema, persistence, or secrets posture.
- No change to Judge, verifier, package entry-set, Registry authority, or the
  telemetry-release-summary@1 key set / Registry validation.
- Skip dedup resolves an acknowledged correct-terminal (legitimate repeated evidence),
  not a hidden failure. Registry publication has never run and remains the next
  untested boundary.
- No new observability/counter channel is introduced; the revision-1 counter feedback
  gap is explicitly out of scope in revision 2 and left for a later non-schema change.

## Next permitted gate

Implementation of Change 1 (dedup key + skip semantics only) may proceed, followed by
agent-world-real-execution-proof (the --resume run) and an Observe read; the release
verdict remains the Registry receipt. Append the Product Alignment Checkpoint
(pac-judge-node-family.md) after the proof as planned.
