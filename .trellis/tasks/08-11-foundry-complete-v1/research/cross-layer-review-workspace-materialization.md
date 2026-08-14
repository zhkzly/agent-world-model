# Cross-Layer Review: workspace materialization closure + typed package errors (diagnosis 17)

- Decision: allow
- Plan digest: 64423ad0 (sha256 of plan-workspace-materialization.md, first 12 hex: 64423ad0f434)
- Plan revision: 1
- Revision count: 1 (new small plan lineage; this is the first critic submission)
- Scope classification: local (builder lane, single file agent_world/candidate.py)

## Trigger

e2e resume terminal `foundry_internal_error` (SupplyChainError
candidate_dependency_metadata_missing) on run_386e4f07c70d4f61be9cafbf82edcc55
(need: 用户预订宾馆) — the first run to reach the package node's SBOM step after
the Judge passed.

## Diagnosis evidence (verified against code)

- candidate.py run() 858-880: fresh TemporaryDirectory root -> _candidate_build
  BEFORE _ensure_workspace (line 878, after _build_plan 872 and _candidate_build
  874); _ensure_workspace is called with candidate_node.artifact.
- _candidate_build 1237-1316: pre-writes inputs/ (design.json,
  implementation-contract.json, build-plan.json) at 1246-1252 and copies the
  runtime template to root/runtime.py at 1253-1256 BEFORE graph.execute;
  compile_candidate (1279-1297) copies pyproject.toml + uv.lock (1282-1283),
  re-renders runtime.py (1287-1289), then snapshots `source_files:
  _source_files_closure(root)` (1296). On resume-skip, graph.execute returns the
  committed head (graph.py 636-644) WITHOUT running compile_candidate, so the
  pre-writes are all that exist on disk.
- _ensure_workspace 1352-1369: short-circuits on
  `if (root / "runtime.py").exists(): return` (1357-1358). The template copy at
  1253-1256 makes runtime.py exist even on skip, so the committed source closure
  is never restored. Confirmed the short-circuit is the defect.
- _source_files_closure 407-424: content-addressed (path/digest/size/mode/
  content_b64 of every file under root). The committed closure is complete for
  the candidate (materializer.py, LICENSE, pyproject.toml, uv.lock, runtime.py,
  inputs/* — including template copies). The diagnosis's "9 files incl.
  pyproject.toml/uv.lock" claim is consistent with the on-disk closure shape;
  exact count depends on whether __pycache__/*.pyc residuals are present, which
  does not change the correctness argument (the closure is whatever the scan
  produced at commit time).
- _package 1934-2002: compile_sbom(root) at 1938 with NO SupplyChainError catch.
  Confirmed. _integration (1397-1398) and _judge_node (1709-1710) already
  convert SupplyChainError; _package is the only one that lets it escape.
- supply_chain.py 29: `class SupplyChainError(ValueError)`. NOT a
  NodeExecutionError (graph.py 244: `class NodeExecutionError(RuntimeError)`)
  subclass. graph.execute only catches NodeExecutionError (graph.py 662); run()
  only catches NodeExecutionError (candidate.py 881/899/921/981). Therefore an
  uncaught SupplyChainError propagates out of the graph to the controller and
  surfaces as foundry_internal_error instead of a typed node failure. Confirmed.

## Affected trust boundary

Builder workspace materialization (candidate.py) + package node error conversion.
No contract, Judge, Registry, or release-policy change. No controller/scheduler/
budget/release boundary crossed; public composition root unchanged; spans a
single component (EnvironmentBuilder). Local scope is genuine — an
independent trellis-research subagent critic is not required.

## Repeated product target

Natural-language EnvironmentRequest -> Research -> Design/WorldSpec ->
Task/Verifier/Implementation -> Builder -> isolated Runtime -> independent Judge
-> Package -> Registry -> Observe. This plan repairs the Builder resume lane so
the materialized candidate closure is complete before integrate/judge/package,
and makes a supply-chain failure surface as an honest, typed node terminal
rather than a generic foundry_internal_error.

## Impact chain

producer: _candidate_build commit (source_files closure, content_b64) ->
changed handoff: _ensure_workspace restore decision ->
immediate consumer: _integration (prepare_candidate/validate_candidate_dependencies
reads root/pyproject.toml/uv.lock) / _judge_node (prepare_candidate) / _package
(compile_sbom) -> package -> Registry -> Observe.

No schema/owners/artifacts/stores change: the closure bytes already persist in
the candidate artifact payload (per allow record fe33df95: "source_files bytes
stay in candidate artifact payload only, package manifest unchanged"). This plan
only changes WHEN those already-persisted bytes are written back to disk.

## Owners

Single framework owner retained: Builder (CandidateExecutor) owns workspace
materialization; the package node owns its SupplyChainError -> NodeExecutionError
conversion (same owner as _judge_node's existing identical conversion). No new
owner, no model-can-claim-completion path introduced. A model cannot falsely
claim completion: the typed terminal is produced deterministically by
graph.execute's NodeExecutionError handling, not by any Agent declaration.

## Compatibility facts

- Existing test test_candidate_source_closure_round_trip_and_materialization
  (tests/test_direct_release.py 1428-1487) calls _ensure_workspace on EMPTY
  directories (fresh/fresh2/empty) with no pre-seeded runtime.py, so the current
  short-circuit does not early-return for it; removing the short-circuit keeps
  all three asserts passing (materialize, digest-mismatch raises, empty-closure
  raises). Confirmed the only three callers: candidate.py 878 + test 1469/1481/
  1487.
- Non-skip idempotency: when candidate_build actually runs, candidate_node.artifact
  references the just-committed envelope whose source_files closure IS the
  on-disk content compile_candidate just produced; _ensure_workspace re-reads it
  and rewrites byte-identical files with a re-verified sha256. Idempotent and
  side-effect-free on the non-skip path. (No test asserts the early-return
  skips a store read, so nothing breaks.)
- SupplyChainError conversion in _package mirrors _judge_node 1709-1710 exactly
  (`raise NodeExecutionError(str(exc)) from exc`) and catches ONLY
  SupplyChainError, so NodeExecutionError and other exceptions still propagate
  unchanged (no swallowing). The existing package_admitted_lock_closure_mismatch
  raise (1940) and all other NodeExecutionError paths are unaffected.

## Unproved consumers

None newly unproved within scope. Not re-verified here (out of scope, unchanged
by this plan): Registry SBOM recompilation (compile_sbom_from_metadata) and
release policy — both explicitly "not changed" (plan lines 22-25). The real
boundary proof below is the honest gate for the resume terminal; Registry
receipt remains the only release verdict.

## Smallest allowed implementation and proof plan

1. Remove candidate.py 1357-1358 short-circuit (and adjust the docstring 1355 if
   it over-claims "when candidate_build was skipped").
2. In _package.operation (1938), wrap compile_sbom:
   `try: sbom = compile_sbom(root) except SupplyChainError as exc: raise
   NodeExecutionError(str(exc)) from exc`.
   Add `SupplyChainError` to candidate.py's imports from agent_world.supply_chain
   if not already imported.
3. Nothing else.

Proof:
- Deterministic: (a) unit test — pre-seed root with runtime.py + inputs/ (and a
  bogus runtime.py content to prove overwrite), then assert _ensure_workspace
  restores ALL closure files (pyproject.toml / uv.lock / materializer.py appear
  afterwards with correct digests). (b) package-path test — a SupplyChainError
  from compile_sbom surfaces as NodeExecutionError(str(exc)). Existing 304 tests
  stay green.
- Real boundary (mandated): pure `uv run agent-world generate --config
  config/agent-world.example.toml --need "用户预订宾馆" --resume
  run_386e4f07c70d4f61be9cafbf82edcc55` — package-time root complete, run
  proceeds past SBOM/telemetry; stop at the first new terminal and re-attribute.

## Deterministic checks

- _ensure_workspace restores the full closure even when runtime.py already exists
  (regression for the exact defect).
- SupplyChainError -> NodeExecutionError in _package (typed terminal, not
  foundry_internal_error).
- Full existing suite (304 tests) stays green.

## True-boundary proof

The real --resume run above, observing live that the package-time workspace
contains the complete committed closure and that a supply-chain failure (if it
occurs) surfaces as a typed node terminal rather than foundry_internal_error.
Distinct from unit/green-test evidence; distinct from end-to-end product proof
(Registry receipt remains the only release verdict).

## Explicit non-claims

- No change to closure snapshot contents, candidate_build pre-writes, Registry
  SBOM recompilation, or release policy.
- No contract/schema/artifact-ABI change (source_files bytes already persist in
  the candidate payload; package manifest unchanged).
- No new runtime CriticNode, Judge, second ReleaseKernel, or fixture/registry/environment-id
  verifier branch.
- Green tests and the resume reaching the next terminal do not by themselves
  claim product completion; the Registry receipt is the only release verdict.

## Next permitted gate

Implementation (after the planner appends this allow record to implement.jsonl
and check.jsonl), then agent-world-real-execution-proof, then read Observe.
PAC pac-judge-node-family.md is extended after the proof.
