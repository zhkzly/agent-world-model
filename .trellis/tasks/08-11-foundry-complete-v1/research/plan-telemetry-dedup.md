# Repair Plan (revision 2): telemetry dedup by (work, operation) identity instead of raw digest (diagnosis 16)

Plan lineage: diagnosis-16-telemetry-dedup.md. Revision 1 (digest 2f02baff)
was blocked by the cross-layer critic (cross-layer-review-telemetry-dedup.md):
the counter keys would break the Registry's exact key-set cold verify.
Revision 2 drops the counters entirely; the summary schema stays byte-shape
identical.

Scope: local, framework telemetry compiler only — agent_world/candidate.py
_compile_telemetry. No contracts, no evidence schema, no summary schema, no
Judge/Registry policy change.

## Change 1 — dedup keys and skip semantics (no schema change)

In _compile_telemetry (candidate.py 2337-2355):

- Work level: a repeated WORK digest (resume re-listing of the same passed
  work) is SKIPPED, not an error.
- Operation level: within each work, dedup by (work_digest,
  operation_digest): a repeated reference to the same operation evidence is
  SKIPPED; the same operation digest may appear in DIFFERENT works (distinct
  real operations with identical evidence content — e.g. one fetch per
  research source) and each occurrence counts once per work.
- The returned summary keeps EXACTLY the schema_version / category_counts /
  model_counts / operations keys — byte-shape identical to today, so the
  Registry's exact key-set cold verify (candidate.py ~3277-3285) and its
  deterministic recompute (~3378) continue to hold.

The anti-inflation property is preserved: the same operation is never
counted twice within a work; distinct operations are never collapsed across
works.

## Explicitly not changed

- OperationEvidence schema, persistence, or secrets posture.
- The telemetry-release-summary@1 key set and Registry validation.
- telemetry_work_record_missing / telemetry_operation_missing / invalid
  evidence validation.
- Judge, verifier, package entry-set, and Registry authority.

## Verification

1. Deterministic: unit tests for _compile_telemetry with a store containing
   (a) a work whose assurance_refs repeat the same operation digest — assert
   the operation is counted once; (b) two distinct works referencing the
   same operation digest — assert both count; (c) repeated work digests in
   the input tuple — assert one count; (d) the returned dict has exactly the
   four schema keys. Existing 303 tests stay green (no test asserts the
   removed duplicate errors — verified by grep).
2. Real boundary (mandated): pure `uv run agent-world generate --config
   config/agent-world.example.toml --need "用户预订宾馆" --resume
   run_386e4f07c70d4f61be9cafbf82edcc55` — design/Judge frozen, package
   re-runs; stop at the first new terminal and re-attribute. Registry
   receipt remains the only release verdict.

## Product Alignment Checkpoint

pac-judge-node-family.md is extended after the proof with the package-stage
result (canonical goal restated; trust boundary = telemetry compiler; the
release verdict remains the Registry receipt).
