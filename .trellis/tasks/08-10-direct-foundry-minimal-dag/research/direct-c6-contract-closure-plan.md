# Direct R9-C6 — minimal executable contract closure

## Goal and non-goals

Close only the eight blocked Direct trust boundaries while preserving the two
fixed graphs and the product target: an arbitrary natural-language need becomes
an executable, independently judged and Registry-published EnvironmentPackage
with safe Observe. This is not a new graph engine, scheduler, plugin system,
permission layer, generic sandbox, repair loop, Expand implementation or
training system.

## 1. Enforce graph ports and edges

- Replace positional bare input tuples at the `GraphRunner` boundary with an
  explicit closed mapping from every declared target input port to one or more
  committed Artifact refs.
- Require the exact declared port set. For a port with incoming graph edges,
  cold-read every envelope and require its graph/node producer to be one of the
  edge's declared sources. A sharded producer may contribute multiple refs.
  Ports with no incoming edge are explicit external inputs and may come only
  from a previously committed external graph/framework Artifact.
- Flatten the validated mapping into one deterministic, duplicate-free
  dependency order for ArtifactEnvelope and WorkRecord. No caller may bypass a
  required edge, and no scheduler or dynamic graph API is added.
- One source envelope may back multiple logical source ports when the fixed
  node emits a closed multi-port payload; port identity remains explicit in the
  binding even though storage stays one immutable envelope.

## 2. Implement one local output-contract correction

- Add the existing closed `CorrectionPacket` value (`code`, exact JSON path,
  violated condition, expected output category) to model/Agent operation input.
- Only a model/Agent compiler or semantic-validator `NodeExecutionError` may
  request one correction before commit. Framework, provider, candidate-process,
  Integration, Judge, Package and Registry failures never enter this path.
- The second dispatch uses the identical frozen semantic projection plus the
  safe packet, the same node owner/Prompt/Skill, and a new physical invocation.
  Persist both bounded attempt facts; commit only the validated final proposal.
  Direct C6 permits exactly one correction, so no progress heuristic, retry
  multiplier or hidden budget is introduced.

## 3. Make CandidateBuild frozen inputs sufficient

- Compile one canonical `implementation-contract.json` containing required
  files/limits, exact Materializer JSONL request and ordered response fields,
  every Runtime operation request/response shape, idempotency rule, tool/result
  obligations, difficulty echo rule, dependency policy and shutdown behavior.
- BuildPlan uses the already documented structured step/risk schema and cites
  these contract sections. CandidateBuild sees only Design, that contract and
  BuildPlan; no repository path, verifier, Judge or release data.
- Update only the product `engineer-environment-codegen` Skill: prefer stdlib
  for the first proof, but permit ordinary registry-wheel dependencies only
  when represented by exact `pyproject.toml`/`uv.lock` entries. Framework C5
  admission remains authoritative; the Agent never chooses hashes, installs,
  downloads or assumes a wheel exists. Missing trusted bytes fail honestly.

## 4. Compile a small executable sealed VerifierBundle

- Replace free-text risks with a closed bounded R9 intent: Challenger selects
  one or more public tool/property targets and one of four executable families:
  unknown-seed, alternate-difficulty, idempotency-key variation, or
  type-preserving argument variation. It supplies semantic risk text but no
  case ID, seed, concrete mutation, expected value, partition or verdict.
- Framework validates references and deterministically expands each intent into
  a public commitment plus a private case with framework-owned seed/key/value.
  Persist only commitments/counts; concrete private cases stay in the same-run
  Judge memory and never enter candidate inputs, ordinary Artifacts or package.
- Judge launches fresh processes and actually executes every case. Baseline
  task claims still require exact expected results; varied cases require the
  closed response schema, declared result types, idempotency/restart behavior
  and safe state transition rather than an Agent-authored verdict. A failed
  case creates route-free evidence and blocks Package.
- This is the smallest executable subset of the canonical Verifier IR; it adds
  no LLM Judge, solver, vault or configurable verifier language.

## 5. Derive operation evidence and telemetry

- Every real Direct/Agent invocation commits a secret-safe operation-evidence
  Artifact with node/category, selected model, usage or `unknown`, and Skill
  digest where applicable. Research acquisition commits actual search, fetch
  and extract category evidence from the performed operations.
- WorkRecord assurance refs bind those facts. Package compiles one
  `TelemetryReleaseSummary` from the exact passed WorkRecords; it may claim only
  categories present in committed evidence and keeps unavailable usage as
  `unknown`, never zero. Delete all hard-coded invocation/research success.

## 6. Close dependency, package and Registry evidence

- `prepare_candidate` exposes the framework-compiled `AdmittedLockClosure`
  alongside its fresh interpreter. Integration commits that exact dependency
  closure and Judge independently re-admits the same closure.
- Package writes canonical flat `envpkg.toml`, typed manifest/provenance/
  assurance/fidelity/curriculum/protocol metadata and an SBOM compiled from the
  admitted physical lock closure. It binds exact source/lock, Design,
  Candidate, passed Integration/Judge/Verifier, dossier, telemetry and lineage
  digests without a manifest hash cycle.
- Registry stages the zip, rejects missing or extra physical entries,
  canonical-parses TOML/JSON, rehashes source and every metadata file,
  recompiles difficulty and SBOM from packaged `pyproject.toml`/`uv.lock`, and
  cross-checks all committed refs before atomic publication. Observe repeats
  the released package/receipt/manifest/lineage/verifier checks.

## 7. Tighten the candidate process boundary

- Reject every hidden file/directory, symlink, device and unmanifested entry in
  candidate source instead of skipping it.
- Launch Materializer and Runtime with an explicit minimal environment that
  contains no credentials, proxy/index variables, Python path, uv/Codex config
  or ambient project state. Continue using absolute fresh-venv Python, fixed
  cwd, JSONL stdio, timeout and teardown; add no configurable sandbox system.

## 8. Tests and proof order

Add focused hostile tests for missing/wrong/multi-shard edge bindings, local
correction scope/count, complete Builder protocol disclosure, verifier secrecy
and actual varied execution, non-hard-coded telemetry, non-empty SBOM,
Registry metadata/extra-file tampering, clean subprocess environment and hidden
source rejection. Preserve C5 offline-wheel and all current tests.

Then run full deterministic checks and an independent Terra `trellis-check`.
Only an `allow` permits the already ordered real proofs: one Direct node, one
singleton-Skill SDK Agent, real CandidateBuild + both stdlib and trusted-wheel
install/Integration cases, then one fresh natural-language E2E to Registry and
Observe. A real failure still enters Observe -> diagnosis -> revised plan ->
fresh critic; it is never patched directly.

## Intended implementation surface

`agent_world/graph.py`, `contracts.py`, `design.py`, `candidate.py`,
`runtime.py`, `supply_chain.py`, `invocation.py`, `observe.py`, the four small
product Runtime Skills only where their frozen contract changes, and focused
tests. `foundry.py`, config and public CLI change only if exact typed handoff
wiring requires it. No legacy module or later-child runtime is in scope.
