# Cross-Layer Review: c8d540d0 (precondition effects + conditional design-driven runtime)

## Decision

**allow** — the plan is the smallest coherent scope (coordinated cross-node, Direct
slice only) and makes the required downstream compatibility and proof explicit. It
fixes the actual framework-owned semantic defect (design language, runtime renderer,
checker) instead of weakening a validator, and it does not change the fixed SFT/RL
consumer interface.

## Identity

- Plan digest: c8d540d0422be195398a407c223f2e455cd32628c91c5bb1d1e6f652fd5b41a7
  (short form c8d540d0). Re-verified by sha256 of the plan file bytes.
- Plan revision: R1 (first submission of this plan lineage; no prior review record
  exists for c8d540d0 in this research directory).
- Revision count: 1 (skill permits at most 2 revisions for the same Diagnosis Record
  and plan lineage).
- Reviewed plan file: research/plan-precondition-conditional-runtime.md (lineage
  root: research/diagnosis-integration-local-tool-semantics-mismatch.md).

## Trigger

Real e2e failure run_386e4f07c70d4f61be9cafbf82edcc55 (need=用户预订宾馆,
config/agent-world.example.toml). Observe scene (read-only CLI) confirms:
design graph 19 works all passed incl. modeling_gate; candidate_build passed
(build.environment_candidate:b7d139db7142fd72); integration FAILED with finding
owner=builder, blocks_release, code=local_tool_semantics_mismatch (evidence
control.attempt:ac2a92d5d28e5bd5 + candidate.integration.failure:61f3f39f9e58d6f4);
judge/package/registry not_run; release not_published. A later resume attempt
terminates credential_missing / needs_human because the retry re-dispatches
verifier_intent (agent node) before integration and needs OPENAI_API_KEY — matches
the diagnosis note and the plan's "credentials exported" proof requirement.

## Diagnosis / Observe evidence (independently verified)

- Frozen artifact design.tool_semantics (shard 0d67a8dde88c1b81..., tool preview_lodging):
  preconditions[0/1] each carry effects=[preserve status (semantic index 15)] with
  when=[lodging_id exists] / [request_id exists]; transitions[0] carries
  effects=[set information_ready=true (14), set status="ready" (15)] with
  when=[lodging_id exists, request_id exists]. On one success trace the contract
  demands both "status preserved" and "status='ready'" on the same field — a
  contradiction no candidate can satisfy. Verified from the frozen artifact JSON.
- Framework-rendered candidate runtime (candidate_source/runtime.py, framework
  overwrite confirmed at candidate.py compile_candidate ~1126-1140): _DESIGN embeds
  each tool's result_fields + a FLAT effects list; all when predicates, tool
  arguments and preconditions are dropped; do_invoke applies every transition
  unconditionally. Verified byte-for-byte.
- Checker coupling (runtime.py _run_recipe ~663-752): selects first precondition +
  first transition and calls _predicates AND _effects for both (lines 728-746);
  failure detail shape matches the observed scene exactly (failed=effects,
  rule_type=precondition, effect field=status preserve previous="" actual="ready").
- Language cause (design.py): _compile_rules compiles effects via
  _array(raw["effects"], 1, 6, ...) (line 500) for every section; the tool_semantics
  prompt (line 1853) applies the shared rule shape to preconditions without defining
  precondition-effect semantics (line 383: effects array[1..6] at least one). The
  modeling gate (lines 1811-1821) only requires transitions to have a state-changing
  effect and accepts the contradictory pair. Verified.
- Deterministic reproduction claim: resume --from integration re-runs integration
  with zero LLM calls for integration itself (verifier_intent is re-dispatched
  first; needs credentials). Plan's proof correctly requires credentials exported.

## Affected trust boundary

Designer framework compile + Direct tool_semantics prompt language (C1) -> Builder
framework design-driven runtime renderer (C2) -> Judge-side integration checker
(runtime.py _run_recipe, shared by integrate and judge) (C3'). These are the three
framework-owned boundaries that interpret precondition/transition semantics on the
Direct path. Unchanged boundaries: candidate process protocol (handshake/reset/
invoke/snapshot/close), result projection, Task Materializer v3, verifier IR, graph
wiring, agent skills, package, Registry, Consumer.

## Repeated product target

Natural-language EnvironmentRequest -> evidence-grounded design -> real isolated
runtime executing state transitions -> independent Judge -> immutable Registry
EnvironmentPackage -> safe Observe; released packages later feed SFT/RL through the
fixed Consumer/RPC episode interface. The plan advances the Direct first-package
path (unblocks Integration) and preserves — without implementing — the
Repair/Expand/Consumer handoffs.

## Impact chain

tool_semantics Direct node -> frozen ToolDraft.preconditions (contracts.py RuleDraft,
unchanged type) -> design.json projection (_rules_for_llm) -> Builder renderer
(candidate.py _design_runtime_data/_DESIGN_RUNTIME_BODY) -> candidate runtime.py ->
integration checker (runtime.py _run_recipe) -> judge (same function) -> package
world/rule_ir.json -> (future, unproved) Consumer evaluator. Upstream assumption
that created the broken value: the rule language required per-rule effects for every
section including preconditions without defining their verification semantics.

## Owners

- C1: Designer framework (design.py prompt text + _compile_rules effects-min gate).
- C2: Builder framework (candidate.py renderer + embedded runtime body).
- C3': Judge framework (runtime.py _run_recipe precondition check).
- Tests: test_design_semantics.py compile fixtures + new renderer regression test.
- The runtime Codex agent is NOT an owner of any of these (candidate.py overwrites
  runtime.py after the agent; verified at lines 1126-1140).

## Compatibility facts (verified, not assumed)

- contracts.py RuleDraft/PredicateDraft/EffectDraft types need no change: RuleDraft
  carries no validation on effects emptiness, so empty precondition effects fit the
  existing contract (verified at contracts.py 550-573).
- rule_ir.json schema keys unchanged: _verify_package_metadata (candidate.py 2727+)
  and _local_rule_digest (96-125) require the same key sets; only content of a
  field's effects array changes for new designs. world_spec.json ships only
  {schema_version, architecture}; the when guards ship in rule_ir.json["tools"]
  (note: the plan's phrase "world_spec.json/rule_ir.json" is imprecise — world_spec
  carries architecture only; this does not change the substance).
- Judge task evaluation (_task_outcome, runtime.py 781-801) consumes TaskRequirement
  rules, not precondition effects; verifier IR has no precondition consumer
  (repo-wide grep confirms preconditions appear only in design compile/projection/
  digest, candidate _local_rule_digest, contracts ToolDraft, and runtime _run_recipe).
- Task Materializer v3 and the RPC episode protocol are untouched by the plan and by
  this slice (Consumer service not implemented here; source-of-truth 12.3/12.4
  define the framework-owned evaluator + start/step/result/close RPC with a closed
  schema; training side never receives Rule IR or evaluator data).
- The C3' checker change is required for the resume proof: committed design heads
  are reused on resume and still carry legacy preserve precondition effects, so
  without dropping the precondition effects check the integration would fail again
  without regenerating the design (which the plan correctly refuses to require).
- 281 tests collected (uv run pytest --collect-only -q -> "281 tests collected"),
  matching the plan's full-suite claim. No existing test asserts the rendered
  _DESIGN shape or executes the rendered design-driven runtime, so the C2 shape
  change breaks no current assertion; the plan's new renderer test fills that gap.

## Unproved consumers

- Future Consumer evaluator over rule_ir.json (not implemented in this slice): the
  interface-level claim holds (framework compiles the evaluator; RPC exposes only
  PublicTask/reset/action/result/reward/termination), but no code consumes the new
  empty-effect preconditions yet; that consumption is the Consumer child's proof.
- Resumed first package: because committed design heads are reused, the first
  released package's rule_ir.json still carries legacy preserve precondition effects
  (only new designs get effects=[]). Schema-valid and ignored by checker/runtime,
  but a future evaluator's interpretation is unproved — recorded as a plan non-claim.
- Judge with a condition-faithful runtime: first time the run reaches judge; plan
  explicitly does not claim judge passes (new failure there = new diagnosis).
- "Precondition failure => reject + preserve" is documented as framework-fixed
  semantics but has no deterministic check and no rejection-path verification in
  this plan (explicitly non-claimed).

## Smallest allowed implementation and proof plan

1. C1 — design.py: document preconditions in the tool_semantics prompt as guard
   rules with effects MUST be []; the wording must state MEANING, not just shape:
   a precondition is a guard ("when may this tool be called") and precondition
   failure is framework-fixed semantics (reject the invoke and preserve state),
   with an explicit "behavior belongs elsewhere" clause (state changes belong in
   transitions, rejection behavior in errors) so the model does not displace the
   confusion into other sections. Include one positive precondition example
   (when=[...], effects=[]) and name the observed anti-pattern (the preserve-no-op
   precondition effect from the frozen preview_lodging contract) as forbidden.
   Add an effects-min parameter to _compile_rules; compile preconditions with
   effects array[0..0] and reject any non-empty precondition effects with
   tool_semantics_invalid at $.preconditions[i].effects, with an actionable
   violated_condition text (paraphrase: preconditions are guard rules — effects
   must be the empty array; put state changes in transitions and rejection
   behavior in errors) so the existing CorrectionPacket
   (code/path/violated_condition/expected_category) loop steers the model on the
   first retry. Keep preserve legal in world invariants, initial rules,
   postconditions.
2. C2 — candidate.py: _design_runtime_data embeds per-transition rules as
   {when: [name-based predicates], effects: [...]}; the when-predicate names MUST
   resolve through the same tool.bindings name map that already projects the
   design artifact (binding.name), so the generated runtime's names are identical
   to the frozen contract names by construction (context fidelity requirement,
   made explicit). A name bound at multiple semantic indexes (e.g., a field bound
   as tool_result AND pre_state/post_state, as price_source is in preview_lodging)
   collapses to the documented resolution rule: request arguments first, then the
   invoked tool's pre-invoke state; only transitions[0] is integration-checked
   today. _DESIGN_RUNTIME_BODY do_invoke evaluates each transition's when against
   request arguments then the invoked tool's pre-invoke state before applying
   effects, using the closed operator set
   (exists/not_exists/eq/ne/lt/le/gt/ge/contains/not_contains) via a generic
   evaluator (no hardcoded tool names/values); an unresolvable when field evaluates
   false (rule not applied). No changes to handshake/reset/snapshot/close, result
   projection, or the materializer contract.
2a. Builder context (candidate.py, in scope): one sentence in the candidate_build
   operation prompt stating that preconditions are guard rules and the framework
   runtime owns the reject+preserve semantics, so the builder agent does not
   re-invent precondition behavior in materializer.py. Do NOT alter design.json
   structure (preserves the plan's unchanged-shape claim). The verifier agent
   (challenge-agent-world) needs NO change: its public-design.json projection
   contains task_families/tools/checkable_recipes/task_rule_summaries only — no
   preconditions (verified) — so the plan's chain claim "builder/verifier agents
   see preconditions with empty effects" is accurate for the builder but
   imprecise for the verifier.
3. C3' — runtime.py _run_recipe: keep selecting first precondition + first
   transition, check the precondition via _predicates only (drop _effects for
   preconditions); transitions keep predicates + effects.
4. Tests: update design_semantics compile fixtures that feed non-empty precondition
   effects (they encode the old language) to empty effects; add the new renderer
   regression test; keep the rest of the 281-test suite green.
5. Add the matching allow record to implement.jsonl and check.jsonl before
   dispatching implementation or checking.
6. At the true-boundary proof terminal, append the required Product Alignment
   Checkpoint in the active task (AGENTS.md obligation; the plan should treat this
   as part of the proof step even though its Files-touched list omits it).

## Deterministic checks

- Preconditions with effects=[] compile; non-empty precondition effects are rejected
  at the right path ($.preconditions[i].effects).
- New in-process renderer test: render the design-driven runtime for a frozen tool
  contract; drive handshake/reset/invoke/snapshot; assert a false when is not
  applied and a true when is applied (falsifiable).
- Full suite (281 tests) stays green except the enumerated language-encoding
  fixture updates (the plan says "enumerated in Checks below" without listing them;
  the set is well-defined: compile-path fixtures feeding non-empty precondition
  effects — a non-blocking clarity note).

## True-boundary proof (smallest real)

Resume run_386e4f07c70d4f61be9cafbf82edcc55 --from integration with credentials
exported: integration must pass; then judge/package/registry execute for the first
time; read Observe after the terminal. No e2e run was performed for this review.

## Explicit non-claims

- Judge passing is NOT claimed (its task-rule semantics run against the new
  conditional runtime for the first time; a failure there is a new diagnosis).
- Rejection-path verification is NOT implemented (C1 documents framework-fixed
  reject+preserve semantics; the runtime does not reject and the checker does not
  verify the rejection path in this plan).
- Cross-tool when references and post_state/tool_result when resolution beyond the
  pre-invoke state are NOT implemented (documented limitation; only transitions[0]
  is integration-checked today; the checker remains the backstop for semantic
  mismatch, catching e.g. not_exists-on-unresolvable-field deviations
  deterministically).
- No Repair/Expand/Consumer features are implemented; their handoffs are preserved.
- The resumed first release ships legacy precondition effects in rule_ir.json
  (design heads are not regenerated).

## Next permitted gate

Implementation dispatch, after the allow record lands in implement.jsonl and
check.jsonl. Then the smallest real proof above via agent-world-real-execution-proof,
then Observe. A new failed scene after any proof terminal starts a new diagnosis and
does not inherit this review's hypothesis. This allow expires if the plan digest, the
affected trust boundary, or the latest relevant real scene changes.

## Supplementary lens: prompt/context engineering (added at plan-writer request; decision unchanged)

Scope note: the plan writer asked whether C1 is sufficient as prompt/context
engineering. Findings below sharpen implementation guidance only; the decision
remains **allow** and the digest/filename are unchanged (plan stays c8d540d0).
All four points are implementable as details of the already-approved C1
"prompt text change" / C2 renderer requirement — none is scope broadening and
none requires a new plan digest.

1. **Semantics-first prompt — COVERED as written, sharpen the "where behavior
   belongs" clause.** The plan's C1 wording already states MEANING, not just
   shape: preconditions are guard rules ("when states the required
   inputs/state") and precondition failure is framework-fixed (reject the
   invoke and preserve state), never per-rule effects. To prevent the model
   from displacing confusion into transitions/errors, the prompt should also
   say explicitly where behavior belongs: state changes belong in
   transitions, rejection behavior in errors. Without that clause the
   constraint is still semantic (not bare), but the placement guidance closes
   the displacement risk the plan writer names.

2. **Positive/negative examples and actionable violated_condition — MISSING as
   written, add within C1.** The plan specifies the rejection path
   ($.preconditions[i].effects) but not the violated_condition TEXT nor any
   example. The framework already has the correction loop
   (CorrectionPacket code/path/violated_condition/expected_category; the
   Direct node retries on DesignError with the packet), so feedback quality is
   free leverage: give the compile rejection an actionable violated_condition
   (paraphrase: preconditions are guard rules — effects must be the empty
   array; put state changes in transitions and rejection behavior in errors)
   and add one positive precondition example (when=[...], effects=[]) plus a
   named anti-pattern: the preserve-no-op precondition effect, which is
   exactly the observed failure in the frozen preview_lodging contract.
   Naming the observed failure in the prompt/feedback is the cheapest way to
   steer the model away from the exact defect that produced this run.

3. **Downstream context consistency — PARTIALLY applicable; builder yes,
   verifier no.** The builder agent (engineer-environment-codegen) reads
   name-based preconditions in inputs/design.json (verified in the skill and
   in the plan's chain claim) and after C1 sees preconditions with effects=[].
   The skill already frames runtime.py as framework-provided and
   design-driven, so there is no code risk, but the plan does not carry the
   fixed rejection semantics into the builder's context even once. Add one
   sentence to the candidate_build operation prompt (candidate.py, already in
   scope): preconditions are guards; the framework runtime owns
   reject+preserve; do not model precondition behavior in materializer.py.
   Do NOT change design.json structure (keeps the plan's unchanged-shape
   claim). The verifier agent (challenge-agent-world) needs no context change:
   its public-design.json contains only task_families/tools/checkable_recipes/
   task_rule_summaries — no preconditions (verified) — so no agent can
   re-invent precondition behavior there; the plan's "builder/verifier agents
   see preconditions with empty effects" is imprecise for the verifier.

4. **C2 name fidelity — implied by construction, make it explicit.** The
   renderer already resolves names via the tool.bindings binding-name map
   that projects the design artifact, so name-based when predicates in the
   generated runtime are identical to the frozen contract names. State this as
   a renderer requirement ("when-predicate names MUST resolve through
   tool.bindings") and restate the source-collapse rule for names bound at
   multiple semantic indexes (e.g., price_source bound as tool_result AND
   pre_state/post_state): resolution order is request arguments, then the
   invoked tool's pre-invoke state; only transitions[0] is integration-checked
   today. This is a spec-line clarification, not new code.

Judgment on absence: findings 2 and 3 are absent from the plan as written, but
their absence does not change the decision. The plan still fixes the actual
framework-owned defect, names real consumers/owners/evidence, and does not
hide the failure; the missing items are feedback quality and context
completeness within the already-approved C1/C2 scope. If the plan writer
implements them (as recommended above), they do not broaden the approved plan
and do not require a new digest or re-review.

## Reviewer notes (non-blocking)

- The plan's "world_spec.json/rule_ir.json" wording for where guards ship is
  imprecise (world_spec.json carries architecture only); guards ship in
  rule_ir.json["tools"][*].preconditions[*].when.
- The test-update enumeration is promised but not listed; recommend the implementer
  enumerate the exact fixtures updated in the commit.
- The Product Alignment Checkpoint at the proof terminal should be executed as part
  of the proof step (AGENTS.md + skill guardrail).
