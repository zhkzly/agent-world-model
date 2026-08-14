# Diagnosis Record 17: resume-skip workspace materialization leaves a partial candidate closure

Date: 2026-08-14 (session)
Trigger: e2e resume terminal `foundry_internal_error` (SupplyChainError
candidate_dependency_metadata_missing) on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆) — the FIRST run to
reach the package node's SBOM step after the Judge passed.

## Evidence (verified)

- Debug instrumentation of _package showed the package-time candidate root
  contains ONLY inputs/ and runtime.py; pyproject.toml, uv.lock,
  materializer.py, LICENSE are missing -> compile_sbom ->
  _read_candidate_metadata -> candidate_dependency_metadata_missing.
- Builder flow (candidate.py run 858-880): fresh TemporaryDirectory root ->
  _candidate_build PREPARES inputs/ + copies the runtime template into root
  (1229-1247) BEFORE graph.execute; on resume-skip graph.execute returns the
  committed head WITHOUT writing the other files; then _ensure_workspace
  (1352-1369) short-circuits on `(root / "runtime.py").exists()` — the
  template copy makes it exist — so the committed 9-file source closure
  (heads.json candidate:candidate_build source_files: LICENSE, inputs/*,
  materializer.py, pyproject.toml, runtime.py, uv.lock) is never restored.
- The committed closure IS complete (9 files, verified in heads.json).
- Second defect: _package.operation calls compile_sbom with no
  SupplyChainError catch (unlike _judge_node 1694-1695), so the error
  escapes graph.execute as a non-NodeExecutionError and surfaces as
  foundry_internal_error instead of an honest node failure.

## Root cause

(1) _ensure_workspace's completeness check uses runtime.py presence, which
the candidate_build pre-write satisfies even when the rest of the closure is
missing; the skip path must materialize the FULL committed closure. (2) The
package node does not convert SupplyChainError into NodeExecutionError.

## Five-lens status

1. Project Agent view — not implicated.
2. Effective Prompt/input — not implicated.
3. Runtime Skill / Direct no-Skill — not implicated.
4. Code/execution boundary — SUPPORTED: candidate.py 1357-1358 short-circuit;
   1229-1247 pre-writes; _package lacks the SupplyChainError catch.
5. Feedback/observability — SUPPORTED gap: the error surfaced as
   foundry_internal_error (SafeFailure "error") instead of the typed code.

## Alternatives rejected

- Keeping the short-circuit and moving the pre-writes: fragile — the
  completeness signal must be the closure itself, not one file.
- Wrapping only compile_sbom: the missing metadata is the workspace defect;
  the typed conversion is defense-in-depth.

## Owner / boundary

Builder workspace materialization (candidate.py) + package node error
conversion; no contract, Judge, or Registry change.

## Smallest next proof

Pure `--resume`: package-time root must contain the full 9-file closure
and the package node must proceed past SBOM/telemetry to the Registry (or
the next honest terminal).
