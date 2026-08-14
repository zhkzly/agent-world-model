# Repair Plan: complete closure materialization on resume-skip + typed package errors (diagnosis 17)

Scope: local, builder lane — agent_world/candidate.py only. No contracts,
no Judge/Registry policy change.

## Change 1 — _ensure_workspace always materializes the committed closure

Remove the `if (root / "runtime.py").exists(): return` short-circuit
(candidate.py 1357-1358). The skip path restores every file of the
committed source closure from the candidate artifact envelope — overwriting
the partial state _candidate_build's pre-writes created (inputs/ + the
runtime template). When candidate_build actually ran, the envelope is the
same closure that was just produced, so the materialization is idempotent.

## Change 2 — package node converts SupplyChainError

In _package.operation, wrap compile_sbom (candidate.py ~1938) so a
SupplyChainError becomes NodeExecutionError(str(exc)) — mirroring the
_judge_node conversion (candidate.py 1694-1695) — so supply-chain failures
surface as typed node failures instead of foundry_internal_error.

## Explicitly not changed

- The closure snapshot contents, the candidate_build pre-writes, the
  Registry's SBOM recompilation, and all release policy.

## Verification

1. Deterministic: unit test that _ensure_workspace restores ALL closure
   files even when runtime.py already exists (pre-seed root with a
   runtime.py + inputs/, assert pyproject.toml/uv.lock/materializer.py
   appear afterwards and digest checks still apply); a package-path test
   asserting SupplyChainError surfaces as NodeExecutionError (existing
   release tests already cover the happy path). Existing 304 tests stay
   green.
2. Real boundary (mandated): pure `uv run agent-world generate --config
   config/agent-world.example.toml --need "用户预订宾馆" --resume
   run_386e4f07c70d4f61be9cafbf82edcc55` — package-time root complete, the
   run proceeds past SBOM/telemetry; stop at the first new terminal and
   re-attribute. Registry receipt remains the only release verdict.

## Product Alignment Checkpoint

pac-judge-node-family.md is extended after the proof (canonical goal
restated; trust boundary = workspace materialization + package error
conversion; the release verdict remains the Registry receipt).
