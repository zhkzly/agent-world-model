# Cross-Layer Review Record

- **Decision:** allow
- **Plan digest:** 5ea84b4d2f536f14
- **Plan revision:** 1 (of max 2 for this lineage)
- **Revision count:** 1
- **Scope classification:** Local
- **Trigger:** real failed Direct/E2E run — offline bench + resume design
  run_386e4f07c70d4f61be9cafbf82edcc55 produced 8 recipes with value-constrained
  precondition guards; the success path violated them.
- **Diagnosis/Observe evidence:** diagnosis-10-guard-satisfying-arguments.md.
  Confirmed in frozen design: tool_semantics shard for search_rate_options
  (artifact bb1f617e165e2414, semantic_revision b31d1c3964) holds precondition
  `when: [{left_semantic_index:35, operator:"ge", right:1}]` over
  argument[2].adults (adults >= 1). Confirmed in agent_world/runtime.py:
  `_value(integer) -> 0` (line ~406), `_run_recipe` builds arguments purely
  from `_value` (line ~734) and never consults `tool.preconditions` before
  invoke, so adults=0 fails the later guard check (line ~768,
  `precondition_guards`).

## Product target (restated)

Turn an arbitrary natural-language EnvironmentRequest into an
evidence-grounded executable environment, independently verify it in a real
isolated boundary, publish an immutable Registry EnvironmentPackage, and expose
only safe facts through Observe. This plan advances the Direct first-package
path at the isolated-Runtime trust boundary; it does not touch Expand or
Consumer.

## Affected trust boundary

producer = `_run_recipe` argument construction (agent_world/runtime.py);
immediate consumer = the runtime invoke + precondition-guard check inside the
same function; later consumers = integration/judge success-path driving. No
design, schema, artifact, package, Registry, or Observe change.

## Impact chain

_run_recipe argument values -> invoke payload -> candidate runtime -> snapshot
post_state -> precondition guard -> integration pass / judge task_reachability.
Upstream assumption: guards are correct design content (confirmed via the
frozen tool_semantics); the driver was the incomplete link.

## Owners

- Argument construction / _guard_arguments: framework integration driver
  (agent_world/runtime.py), owned by the runtime/integration node family.
- Grached constraint content: design tool_semantics (frozen, unchanged).
- Validation (guard OR semantics, candidate_argument_schema_mismatch,
  rule_ir_*): unchanged framework paths retain their owners.

## Compatibility facts

- Trace shape unchanged; `_value` category mapping unchanged (helper only
  adjusts values after defaults are produced).
- Private-case `varied_arguments` override preserved: it is applied as a full
  dict replacement after `_value` (runtime.py line 735-736); the new helper
  runs only on the `_value`-generated arguments and does not rewrite the
  `varied_arguments` branch.
- No design/schema/artifact change; frozen design regenerated and frozen stays
  authoritative.
- No solver loops, no LLM, no new runtime node, no Judge/Registry/Observe
  change.

## Smallest allowed implementation

1. In agent_world/runtime.py add `_guard_arguments(tool, arguments)`: after
   `_value` defaults, adjust each argument field per `tool.preconditions`
   predicates that bind to `argument` source: eq -> set constant; ne -> vary
   if equal; ge/gt -> raise into range; le/lt -> lower into range;
   exists/not_exists -> presence semantics already satisfied by category
   defaults. Deterministic, bounded (~30 lines), leaves jointly-satisfiable
   guards satisfiable.
2. Apply it in `_run_recipe` before the invoke payload for both the target
   tool and prefix actions, and before the `candidate_argument_schema_mismatch`
   category check (or equivalently re-run category check after adjustment).
   Do not apply when `varied_arguments` is set (that branch replaces
   arguments wholesale).

## Deterministic checks

- New unit test: a tool with an `adults ge 1` guard is driven with adults=1
  (not 0) through integrate().
- pytest full suite green (regression only; not product proof).

## True-boundary proof

- Offline bench: integrate() against the frozen regenerated design for
  run_386e4f07c70d4f61be9cafbf82edcc55 must pass all 8 recipes (isolated
  runtime boundary).
- Real: `agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55`
  and read observe terminal. (Not run during review.)

## Non-claims

- We do not claim judge/package/registry pass.
- Guard adjustment does not prove the EnvironmentPackage target; a committed
  node or green test alone is not product completion.
- No claim that every future guard is satisfiable; only that the current
  satisfiable guards are driven into range deterministically.

## Next permitted gate

Implementation only; afterward agent-world-real-execution-proof (real resume +
observe terminal), then Observe. A Product Alignment Checkpoint at the proof
terminal must restate the canonical goal and name what remains unproven.