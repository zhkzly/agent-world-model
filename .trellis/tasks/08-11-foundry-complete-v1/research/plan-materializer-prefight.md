# Repair Plan: candidate_build materializer pre-flight

Lineage: diagnosis-11-materializer-prefight.md. Continues the direct-completion
lineage after fe33df95 / 0ff3ae1d / 58a29e92 / 3fd31254 / c0fe624d / 4ec3cd93 /
5ea84b4d allows (all spent).

## Scope classification

Local. Producer: candidate_build compile_candidate (candidate.py); consumer:
the codegen agent (one authorized correction via local_corrections=1). No
schema, artifact-envelope, package, or Registry change.

## Changes

1. agent_world/candidate.py compile_candidate: after writing the workspace
   files, run the materializer pre-flight — for each assurance recipe,
   materialize(root, request, schema) + _validate_materialization — offline
   with sys.executable (no venv, no network). On CandidateRuntimeError raise
   NodeExecutionError with an actionable correction packet: code
   materializer_preflight_failed, violated_condition listing the failing
   family/tool and the exact category mismatches (public_goal /
   initial_config, field, expected vs actual category). The graph's local
   correction loop re-dispatches the codegen agent once with this feedback.
2. Deterministic test: a deliberately broken materializer stub is rejected
   at candidate_build compile with the correction packet (test via the
   _release_candidate harness with a bad materializer).

## Compatibility

- The pre-flight is read-only against the workspace; integration behavior
  unchanged (it re-validates the corrected candidate).
- Correction budget unchanged (1 local correction already declared).

## Checks and proofs

- pytest full suite green.
- Offline bench: after the real candidate_build re-dispatch, integrate()
  must pass all recipes.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim the corrected materializer passes; further terminals are
  new observations.
