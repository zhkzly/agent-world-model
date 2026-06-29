# Design

## Target Shape

The request-driven path should be a generic environment generation pipeline:

```text
raw request / local source paths
  -> DomainPlan
  -> SourceEvidenceIndex
  -> KnowledgePack
  -> EnvironmentSpec
  -> LogicalToolGraph
  -> TaskSet
  -> SurfacePlan
  -> VerifierPlan
  -> ImplementationRequest
  -> code-agent GeneratedEnvironmentBundle
  -> framework generic replay/check
  -> bounded repair
  -> package/release
```

The framework can contain generic contracts and executors, but not domain-specific domain/task/runtime/verifier constants on the normal request-driven path.

## Key Refactor

### 1. Split legacy probes from request-driven pipeline

Move or isolate booking/library/project-board probe logic so `request_driven_node_registry()` no longer calls it. Existing fixture tests may keep fixture modules, but the new success path must not import them.

### 2. Generic planning and synthesis

Introduce generic synthesis helpers that derive artifacts from raw request and source evidence:

- `DomainPlan`: generated slug/id, domain summary, source plan, constraints.
- `KnowledgePack`: state entities, operations, business rules, examples, uncertainties extracted from source evidence.
- `LogicalToolGraph`: operation schemas and dependencies derived from KnowledgePack.
- `TaskSet`: generated from tool graph paths, not domain task ids.
- `VerifierPlan`: generated deterministic expectations from task state/action evidence.
- `SurfacePlan`: Python callable surface generated from logical tools.

When the source evidence is too thin, the pipeline should fail with a typed failure packet instead of inventing hidden domain constants.

### 3. Agent-backed implementation by default

For the normal request-driven success path, implementation must call `AgentBackend` and write generated files in an isolated workdir. Tests can use a local mock/process runner that reads the generic workspace packet and produces candidate files, but the framework path must be the same one used by Codex/code-agent runners.

### 4. Generic replay contract

`framework-replay-contract.json` should be built from artifacts:

- runtime entrypoint and methods from `SurfacePlan`
- tool call sequence from `TaskSet.dependency_path` and generated replay inputs
- verifier kwargs from framework contract
- expected answer/state metadata from `TaskSet` / `VerifierPlan`

Production code must not contain a dictionary keyed by environment ids such as booking/library/project-board. Domain-specific tool calls belong in artifact data generated earlier in the pipeline.

### 5. Generic framework candidate check

Replace domain-specific independent verifier dispatch for request-driven generated environments with a generic checker:

1. import `runtime.py`, `verifier.py`, and `seed_state.json`
2. instantiate runtime entrypoint from contract
3. execute each replay case from the contract
4. verify trace order and output shape
5. call generated verifier for positive and negative cases
6. collect structured observation with expected/actual/traceback

This still uses generated verifier logic, but the framework controls execution, negative checks, trace validation, and release decision.

## Compatibility

- Keep older support-desk/project-board/booking/library tests only if they validate legacy fixtures or regression behavior outside `run_request_driven_pipeline()`.
- Update or remove tests that assert booking/library request-driven success as the primary path.
- Keep `awm` CLI compatibility unless explicitly unrelated tests are removed.

## Completion Definition

The implementation is complete only when:

- request-driven production modules do not contain domain-specific hardcoding
- generic request-driven tests pass with a new arbitrary request
- repair/check/release still execute generated files
- docs accurately state that previous probes were removed or moved to historical fixtures
