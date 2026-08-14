# Cross-Layer Review — plan-guard-conflict-gate (3fd312545ad4fa32)

Decision: **allow**

## Identity

- Plan digest (sha256, re-verified): 3fd312545ad4fa324eb804c5baeb86a1380b634f2320c0f48e4a0adc5b69aafa (short 3fd312545ad4fa32).
- Plan revision: R1 (new lineage; continues the direct-completion lineage after the fe33df95 -> 0ff3ae1d -> 58a29e92 allows, all spent on separate scopes).
- Revision count: 1 (skill permits at most 2 per lineage).
- Reviewed file: research/plan-guard-conflict-gate.md.

## Scope classification

**Local.** Producer: Designer framework tool_semantics compile gate (agent_world/design.py); consumer: the Direct LLM (correction feedback) and integration (which then sees only satisfiable contracts). No RuleDraft/schema, artifact-envelope, package, or Registry change. No runtime checker semantics change (the existing local_tool_semantics_mismatch precondition_guards reject already catches this defect — the plan moves detection earlier, to compile time, so a defect is rejected at the source instead of surfacing only at integration).

## Trigger

Real failed Direct/E2E run run_386e4f07c70d4f61be9cafbf82edcc55 (need=用户预订宾馆), terminal rejected / local_tool_semantics_mismatch, failed=precondition_guards, tool preview_lodging. Diagnosis Record 7 (diagnosis-7-unsatisfiable-guards.md) attributes it to a design-language gap: the model expressed an ALTERNATIVE (any of three channels) as three separate AND-ed eq guards, and neither the prompt nor any static gate rejected the mutually exclusive set.

## Diagnosis / Observe evidence (independently verified, read-only)

- Frozen design:tool_semantics:preview_lodging compiled_json.preconditions contains exactly four rules; rules [1..3] are: [1] when=[left_semantic_index=6 op=eq right=google_search] [2] when=[left_semantic_index=6 op=eq right=google_maps] [3] when=[left_semantic_index=6 op=eq right=youtube], and surface.argument_fields.google_channel declares enum values [google_search, google_maps, youtube]. Index 6 is google_channel. Confirmed against heads.json.
- AND semantics: runtime.py _run_recipe iterates every tool.precondition rule and raises local_tool_semantics_mismatch if any fails (lines ~765-775); _predicates (runtime.py 429-470) ANDs every `when` predicate and, for eq, requires type(left) is type(right) and left == right. A single google_channel value cannot equal three distinct strings, so rules [1..3] are jointly unsatisfiable regardless of argument value. The checker is honest.
- Compile site confirmed: agent_world/design.py tool_semantics compile already computes pre = _compile_rules(raw.preconditions, ...) at path $.preconditions, resolving predicate left_semantic_index/operator/right from field names via _name_to_index (lines ~1786-1806; _compile_rules ~415-489). The post-compile point immediately after that call is the correct, minimal owner for a static conflict gate.
- Correction loop confirmed: graph.py _eligible_local_correction (850-888) re-prompts the Direct LLM with the CorrectionPacket whose violated_condition is the actionable message, when the DesignError is non-retryable and carries a correction. A compile-time rejection with an actionable violated_condition is fed back by the existing loop; no new retry machinery is needed.
- Prompt-id invalidation confirmed: graph.py:325 declares tool_semantics prompt_id tool-semantics@2; semantic_revision (graph.py:593-610) folds prompt_identity=node.prompt_id into the revision digest (prompt TEXT itself never enters an artifact), so bumping @2 -> @3 re-invalidates the frozen preview_lodging shard on pure resume. Verified.

## Repeated product target

Natural-language EnvironmentRequest -> evidence-grounded design -> real isolated runtime -> independent Judge (all required hard claims) -> immutable Registry EnvironmentPackage -> safe Observe facts. This plan advances the Direct first-package path by preventing the Designer from emitting contracts that the independent checker must later reject as unsatisfiable.

## Affected trust boundary

Designer framework compile gate / Direct tool_semantics prompt language -> frozen ToolDraft preconditions -> Builder runtime -> integration checker. The change owns satisfiability at the framework (deterministic), not in the LLM or the untrusted candidate. Package/Registry/Judge/release meaning unchanged.

## Impact chain (producer -> consumer)

tool_semantics prompt (@2 -> @3, guards are AND-ed; alternatives belong in transitions) -> design.py compile (new static pair-conflict gate) -> local correction loop re-prompts -> regenerated ToolDraft -> Builder design-driven runtime renderer unchanged -> runtime _run_recipe checker unchanged -> package world/rule_ir.json (same RuleDraft schema) -> Registry manifest shape untouched -> future Consumer unchanged.

## Owners

- Designer framework (design.py): the new static gate; deterministic, not the LLM.
- Direct LLM correction (graph.py): unchanged mechanism, new message.
- Judge/checker (runtime.py): UNCHANGED — it already rejects the defect; no checker logic is touched (no weakened validator, no compatibility path, no fixture).
- The candidate Codex agent is NOT an owner.

## Compatibility facts (verified, not assumed)

- RuleDraft/PredicateDraft/EffectDraft/ToolDraft/TaskRequirement types unchanged; the gate only rejects a previously-admitted (but transitively-rejected) input. No schema, artifact-envelope, package-manifest, or Registry exact-key change.
- Satisfiable guards still pass: eq on DIFFERENT fields (different left_semantic_index) is never compared; identical constants on the same field (a redundant-but-satisfiable duplicate) is not rejected by the different-right-value condition. Existence predicates (exists/not_exists) carry no `right` and are unaffected by the eq-only comparison.
- materializer_protocol.json, public_goal_leaf_map, Task Materializer v3 response shape, _validate_materialization, Judge gates, and package manifest are outside this plan and untouched.
- The prompt-id bump re-invalidates tool_semantics shards (and their downstream design nodes) on pure resume — intended, consistent with the id-bump contract verified in the fe33df95 review.

## Unproved consumers

- Regenerated preview_lodging (and sibling) shards passing integration is NOT claimed; the next terminal is a new observation.
- Expand/Consumer/auto-capture remain unimplemented (explicit non-claims); their fixed handoffs are unaffected by a compile-time design gate.

## Smallest allowed implementation and proof plan

1. design.py tool_semantics compile: after pre = _compile_rules(...), scan pairs of rules in `pre`; for any two rules carrying eq predicates with the same left_semantic_index and different (non-equal) right constants, raise DesignError(tool_semantics_invalid, path=$.preconditions, violated_condition=precondition guards are AND-ed and must be jointly satisfiable; express alternatives as transitions, not as multiple eq guards on one field).
2. tool_semantics prompt: add one statement that guards are AND-ed and must hold together; alternatives/variants belong in transitions (named anti-pattern: multiple eq guards on the same field with different values).
3. graph.py: prompt_id tool-semantics@2 -> @3 only.
4. tests: compile-gate test (two conflicting eq guards rejected with the actionable message; satisfiable guards accepted — different-field eq and identical-constant eq), plus full pytest suite green.

## Deterministic checks

- New unit test: conflicting eq guards rejected with the exact actionable violated_condition; satisfiable guards (eq on different fields; identical constants on one field) accepted.
- Full pytest suite green (283 tests collected, matching prior review; enumerate any prompt-language fixture updates).

## True-boundary proof (smallest real)

1. Deterministic gate test proves the compile-time rejection offline (zero LLM calls).
2. Real run: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55 (bumped id regenerates the frozen shard with real LLM; evidence reused) -> observe the terminal. A regenerated shard that still fails is a new observation, not proof. Product Alignment Checkpoint at the proof terminal.

## Explicit non-claims

- Regenerated model output correctness is NOT claimed until the real judge passes.
- The plan does NOT weaken the integration checker or add any compatibility path for legacy frozen artifacts; conflicted artifacts regenerate via the id bump.
- Expand/Consumer/auto-capture remain unimplemented.

## Next permitted gate

Implementation dispatch after the main planner adds this allow record (digest 3fd312545ad4fa324eb804c5baeb86a1380b634f2320c0f48e4a0adc5b69aafa) to implement.jsonl and check.jsonl, then the smallest real proof via agent-world-real-execution-proof, then Observe. A new failed scene starts a new diagnosis and does not inherit this review's hypothesis. This allow expires if the plan digest, affected trust boundary, or latest relevant real scene changes.
