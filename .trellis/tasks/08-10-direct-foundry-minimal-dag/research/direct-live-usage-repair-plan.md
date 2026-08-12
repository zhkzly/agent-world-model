# Minimal repair plan R1 — canonical Direct usage evidence

## Goal

Allow the real Direct result to cross the existing secret-safe operation
evidence boundary without weakening safety or changing node semantics.

## Exact implementation

1. In `DirectChatBackend`, map valid provider `prompt_tokens` to
   `input_tokens` and `completion_tokens` to `output_tokens`; preserve valid
   `total_tokens`. Do not persist provider payloads or add usage fields.
2. In `OperationEvidence`, retain only the canonical token keys already used by
   Codex Agent evidence: cached/input/output/reasoning-output/total. Remove the
   two provider aliases so accepted contracts are always persistable.
3. Add focused deterministic coverage that:
   - a mocked Direct response normalizes only valid non-negative integer usage;
   - provider aliases are rejected by `OperationEvidence`;
   - canonical Direct evidence persists as `assurance.operation` and appears in
     the WorkRecord assurance closure.
4. Run the existing deterministic quality gate. Do not mutate stale diagnostic
   run `run_0fe1d0215d644837a43cfe7fc9994abe`; its safe Observe scene remains an
   incomplete, unreconciled harness record and is never a resume/release input.
   Use one fresh run for the exact frozen `world_architecture` proof. The proof
   harness must contemporaneously map any raw `OSError`/`ValueError`/`TypeError`
   to the public root's existing `foundry_internal_error` terminal result, then
   read Observe once the process stops.

## Explicit non-goals

No historical run mutation, reconciliation/recovery path, Artifact safety
exception, new telemetry schema, graph/node/error framework, Prompt or compiler
change, route/fallback/retry change, Skill, Candidate, Repair, Expand or
Consumer implementation. The real model result remains unproved until the
fresh run commits a passing WorkRecord.

## Acceptance

- Direct usage evidence uses canonical safe names and can be cold-read.
- Provider-specific aliases fail at contract construction rather than Artifact
  commit.
- Existing checks remain green.
- The stale proof scope remains visibly incomplete and is never adopted. The
  exact fresh run either commits one passing Direct WorkRecord or stops with a
  contemporaneously recorded safe failure.
