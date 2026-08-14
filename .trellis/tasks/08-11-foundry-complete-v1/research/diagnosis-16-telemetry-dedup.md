# Diagnosis Record 16: telemetry dedup rejects legitimate repeated operation evidence

Date: 2026-08-14 (session)
Trigger: e2e resume terminal `telemetry_operation_duplicate` on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆) — the FIRST run to
pass the Judge (all 20 + 4 gates passed at 05:07:41) and reach the package
node.

## Evidence (verified)

- Judge passed (judge.gate_evidence terminal_success_reward_plus_one);
  package node failed at 05:07:42 with telemetry_operation_duplicate
  (release.package.failure).
- _compile_telemetry (candidate.py 2328-2398) walks design.work_refs and
  manifest.work_refs, raising telemetry_work_record_duplicate on a repeated
  work digest and telemetry_operation_duplicate on a repeated
  assurance.operation digest.
- The research_acquire work record (50caf18240e6) references the SAME
  operation evidence digests repeatedly: 1 search + 6 fetch + 6 extract
  assurance refs, where every fetch ref is digest ce207f737... and every
  extract ref digest 1a09c46... — identical OperationEvidence content
  (category fetch/extract, model null, usage null) because the evidence
  schema carries no per-operation discriminator (no source/document
  identity).
- Content-addressed storage: identical evidence content -> identical
  artifact digest -> the dedup-by-digest check fires although every ref is
  a distinct real operation.

## Root cause

Telemetry dedup keys on operation evidence DIGEST, but OperationEvidence
(category, node_id, route_model, usage, skill_digest) is not
per-operation unique: multiple real research fetch/extract operations (one
per source) produce byte-identical evidence. The duplicate checks were
designed as anti-inflation guards, but digest identity is the wrong key —
legitimate repeated evidence (also across re-rolled attempts with equal
token usage) collides and aborts release.

## Five-lens status

1. Project Agent view — not implicated.
2. Effective Prompt/input — not implicated.
3. Runtime Skill / Direct no-Skill — not implicated.
4. Code/execution boundary — SUPPORTED ROOT CAUSE: candidate.py
   2342-2355 dedup keys and error semantics.
5. Feedback/observability — SUPPORTED gap: no counters expose how many
   references were deduplicated.

## Alternatives rejected

- Adding a per-operation discriminator to OperationEvidence: a contracts +
  persistence + registry-validation change; the evidence schema is
  deliberately identity-free, and the telemetry only needs honest distinct
  attestation.
- Erroring on duplicates is necessary for release honesty: no — the
  anti-inflation property is "the same operation is never counted twice";
  skipping repeated digests delivers exactly that.

## Owner / boundary

Framework telemetry compiler (candidate.py _compile_telemetry); the
Registry cross-checks the same deterministic computation.

## Smallest next proof

Pure `--resume`: the design graph and all candidate nodes up to the Judge
are frozen (heads match), the package node re-runs — telemetry must compile
and the run must reach the Registry (or the next honest terminal).

## What remains unknown

- Registry validation itself has never run; its cross-checks are the next
  untested boundary.
