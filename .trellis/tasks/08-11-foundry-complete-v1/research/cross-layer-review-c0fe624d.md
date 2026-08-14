# Cross-Layer Review: plan-runtime-idempotency.md (digest c0fe624d7f131abe)

## Decision

**allow**

## Plan identity

- Plan digest: c0fe624d7f131abe
- Plan revision: 1 (first submission for diagnosis-8-runtime-idempotency.md)
- Revision count: 1
- Scope classification: **Local**

## Trigger

Real failed e2e run run_386e4f07c70d4f61be9cafbf82edcc55, resume after the
guard gate, terminal rejected / candidate_idempotency_failed. Diagnosis Record
8 (diagnosis-8-runtime-idempotency.md) attributes the failure to the
framework-rendered design-driven runtime lacking keyed idempotency.

## Evidence

- agent_world/runtime.py:753-756 — `_run_recipe` calls
  `process.call(payload)` twice with the same idempotency_key and raises
  `candidate_idempotency_failed` when `first != second`.
- agent_world/candidate.py:275-341 — `do_invoke` evaluates each transition's
  `when` against live `_state`, applies effects that mutate
  `current[field]`, and returns `{"status": "ok", "result": dict(current)}`.
  There is no cache keyed by `idempotency_key`; a state-changing conditional
  transition therefore returns a different result on the second invoke.
- agent_world/candidate.py:206 — `_init()` rebuilds `_state` (reset clears
  state) but currently clears no cache (none exists).
- agent_world/candidate.py:1269 — `compile_candidate` unconditionally writes
  `root/runtime.py` with `_render_design_driven_runtime(design)`, so the
  runtime is framework-owned and overwritten regardless of the skill digest.
- docs/agent-world-environment-generation.zh.md:734 — "重复 idempotency key 不得
  重复副作用" (a repeated idempotency key must not repeat side effects).

## Affected trust boundary

The framework-owned design-driven runtime body (`_DESIGN_RUNTIME_BODY` in
`agent_world/candidate.py`) and the framework's own `_run_recipe`
double-invoke assertion. The judge invokes with distinct keys, so its path is
unaffected. No design, artifact-envelope, package, Registry, or Judge contract
changes.

## Product target (repeated)

Turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded
executable environment, independently verify it in a real isolated boundary,
publish an immutable Registry EnvironmentPackage, and expose only safe facts
through Observe. This plan advances that target only by restoring the runtime's
idempotency invariant so the design-driven runtime can pass framework
verification; it does not by itself reach judge/package/registry completion.

## Impact chain

_DESIGN_RUNTIME_BODY (producer) -> rendered runtime.py (changed handoff) ->
_run_recipe double-invoke (immediate consumer, framework) -> judge (later
consumer, unchanged: distinct idempotency keys). Package/Registry/Observe are
downstream but not modified by this change.

## Owners

- Framework owns the rendered runtime (compile_candidate overwrites it).
- Framework owns the idempotency assertion in `_run_recipe`.
- The judge retains independent verification authority; the cache does not
  grant any model authority over reward/termination/release.

## Compatibility facts

- Protocol shape unchanged: invoke(tool_id, arguments, idempotency_key),
  handshake operations list, snapshot, reset all remain identical.
- A repeated key returning the cached response implements the
  source-of-truth contract ("不得重复副作用") framework-side without changing
  state semantics for distinct keys.
- `dict(current)` already returns a shallow copy; the proposed "response dict
  copied on return" is naturally satisfied and should be asserted in the test
  to guard against the cached dict being mutated by the caller.
- The skill-digest change re-invalidates candidate_build on pure resume; this
  is harmless because compile_candidate re-renders and overwrites runtime.py
  anyway.

## Unproved consumers

Handles for the branch where `do_invoke` returns an error (unknown op,
malformed request) should bypass the cache (cache only success-shaped
`{"status":"ok",...}` responses) so repeated-key semantics remain exact; the
plan's "invokes without a key bypass" must extend to "error responses are not
cached". Judge/package/registry terminals remain unproven and are explicitly
out of scope.

## Smallest allowed implementation and proof plan

Implement exactly:

1. agent_world/candidate.py `_DESIGN_RUNTIME_BODY`: add
   `_idempotency_cache = {}` cleared in `_init()`; in `do_invoke`, before
   applying effects, read the cache by `request.get("idempotency_key")`;
   on hit return a `dict()` copy of the cached response; on miss compute,
   cache the success response keyed only when a non-null idempotency_key is
   present, and return a copy. Missing key and error responses bypass the cache.
2. agent_world/runtime_skills/engineer-environment-codegen/SKILL.md: document
   the contract (same idempotency_key -> identical response, no repeated side
   effects) for materializer/runtime authors.
3. tests: rendered-runtime test — two invokes with the same key and a
   state-changing transition return identical results; a new key advances
   normally; reset clears the cache.

No change to runtime.py, judge, package, Registry, or materializer.

## Deterministic checks

- pytest full suite green, including the new rendered-runtime idempotency test
  with a state-changing transition under a repeated key.

## True-boundary proof

- Real: `agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55`
  and observe the terminal (read Observe after the terminal). This exercises the
  real `_run_recipe` double-invoke against the actual rendered runtime.

## Non-claims

- Passing the idempotency assertion is not judge/package/registry completion.
- No claim that downstream terminals pass; further terminals are new
  observations.

## Next permitted gate

agent-world-real-execution-proof (after implementation), then Observe.
