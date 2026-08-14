# Diagnosis Record: integration local_tool_semantics_mismatch (e2e 用户预订宾馆)

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55 (config/agent-world.example.toml, need=用户预订宾馆)
Terminal: rejected / local_tool_semantics_mismatch, release not_published.

## Safe Observe facts

- DesignGraph 19 works all passed (research -> evidence -> architecture -> tool
  semantics x4 -> rules -> curriculum -> tasks x5 -> modeling_gate).
- CandidateGraph: build_plan passed, verifier_intent not_run, candidate_build
  passed (build.environment_candidate:b7d139db7142fd72), integration FAILED,
  judge/package/registry not_run.
- Finding: control.finding (finding_44b53d1adabbe2f6), owner=builder, blocks_release,
  code=local_tool_semantics_mismatch; evidence: control.attempt:ac2a92d5d28e5bd5 +
  candidate.integration.failure:61f3f39f9e58d6f4.
- Failure detail (frozen): tool=preview_lodging, rule_type=precondition,
  rationale="A lodging identifier is required to locate the property for preview.",
  failed=effects, effect={field: status, operation: preserve, value: null,
  previous: "", actual: "ready"}.

## Frozen contract evidence

design.tool_semantics artifact (preview_lodging, shard 0d67a8dde88c1b81c...):

- precondition[0]: when=[lodging_id exists], effects=[preserve status(post, idx15)]
- precondition[1]: when=[request_id exists], effects=[preserve status(idx15)]
- transition[0]: when=[lodging_id exists, request_id exists],
  effects=[set information_ready=true, set status="ready"]

=> On one success trace (all required arguments present) the contract demands
   BOTH "status preserved" (precondition effect) AND "status='ready'"
   (transition effect) on the same field. Contradiction: no candidate runtime
   can satisfy both. Failure is fully determined by frozen artifacts + framework
   code; no LLM randomness involved.

## Deterministic reproduction

- `generate --resume run_386e4f07... --from integration` re-runs the node path
  with zero LLM calls for integration and fails identically
  (local_tool_semantics_mismatch). NOTE: the retry first re-dispatches
  verifier_intent (an agent node, not upstream of integration, never committed)
  and needs OPENAI_API_KEY; without credentials the terminal becomes
  credential_missing/needs_human before integration is reached.
- Candidate runtime.py that ran integration is NOT agent-written: it is the
  framework-rendered "design-driven runtime" (candidate.py
  _render_design_driven_runtime). compile_candidate overwrites the agent's
  runtime.py with it.

## Causal chain (ordered, all framework deterministic)

C1 (design language): tool_semantics prompt requires every rule, including
   preconditions, to carry effects: array[1..6]. It defines no semantics for
   precondition effects and no consistency check against transitions. The
   Direct LLM responded with preserve no-ops -> self-contradictory frozen
   contract. modeling_gate only checks "transitions have >=1 state-changing
   effect"; it accepts the contradictory pair.
C2 (runtime renderer): _design_runtime_data + _DESIGN_RUNTIME_BODY flatten all
   transitions' effects and drop every `when` predicate, tool arguments, and
   preconditions. do_invoke applies ALL transitions unconditionally. The claim
   "correct by construction" is false for any design with conditional rules.
C3 (checker coupling): runtime._run_recipe checks precondition[0].effects on the
   success trace (selected_rules = first precondition + first transition, an
   ad-hoc selection). With C1 fixed (preconditions carry no effects) this check
   passes trivially; no checker change needed.

## Five-lens status

1. Project Agent view: supported (observe scene + candidate_source preserved;
   no broad search needed).
2. Effective Prompt/input: SUPPORTED CAUSE — tool_semantics prompt forces
   effects on preconditions without defining their verification semantics
   (design.py _RULE_DRAFT_SHAPE / _direct_commit output text).
3. Runtime Skill / Direct no-Skill: tool_semantics is Direct (no-Skill invariant
   held); engineer-environment-codegen correctly told the agent not to write
   runtime.py and the agent's file was overwritten anyway -> not the cause.
4. Code/execution: SUPPORTED CAUSE — candidate.py design-driven runtime renderer
   drops when/arguments/preconditions; runtime.py checker enforces the
   contradictory pair. Boundary: Builder-owned renderer + Judge-owned checker
   interpreting the Designer-owned contract.
5. Feedback/observability: supported — failure detail names tool/rule_type/
   effect/expected/actual; recipient can act. (The 47-binding dump is noise but
   not blocking.)

## Owner / boundary

- C1: Designer (Direct tool-semantics language) — design.py prompt + compile.
- C2: Builder (candidate runtime renderer) — candidate.py.
- C3: no change.
The runtime Agent (Codex) is NOT the owner of any of these.

## Rejected strategies

- Re-running integration / candidate_build without a code change (deterministic
  same failure; runtime gets overwritten by the same broken renderer).
- Prompting the codegen agent to implement preconditions in runtime.py (framework
  overwrites runtime.py; also contradicts the skill's contract).
- Making the checker lenient (skipping precondition effects) while the contract
  language still emits contradictory rules: hides the defect instead of fixing
  the contract.
- Per-tool special cases / fixture success paths (forbidden by AGENTS.md).

## Smallest next proof

1. Offline: unit-level proof that the new tool_semantics compile accepts a
   precondition with zero effects and rejects a precondition whose effect
   contradicts a transition on the same field (if we add the gate; otherwise at
   least zero-effect acceptance).
2. Offline: render the design-driven runtime for the frozen design and drive
   handshake/reset/invoke/snapshot locally; assert preview_lodging applies only
   the transition whose `when` holds (price_source stays "cache").
3. Real: resume run_386e4f07... --from integration (credentials exported) and
   expect integration passed; then judge/package/registry.

## Still unknown

- Whether judge's task rules pass with a condition-faithful runtime (first time
  the run reaches judge); any judge failure will be a new attribution.
- Whether other frozen designs contain additional rule-language abuses that only
  surface under a faithful interpreter.

## Proposed minimal repair (for the repair-plan revision, NOT yet approved)

- C1: preconditions compile with effects: array[0..6] (prompt text says effects
  are forbidden/ignored for preconditions); keep RuleDraft schema compatible
  (empty effects tuple). Optional cheap gate: reject a precondition effect that
  targets a field a transition sets (contradiction check) — only if trivial.
- C2: runtime renderer embeds each transition's `when` (name-based, over
  arguments + pre-state) and evaluates before applying effects; support
  exists/not_exists/eq/ne (extend only if a frozen design needs more).
- No change to runtime.py checker, graph wiring, or agent skills.
