# Diagnosis Record 14: first Judge run fails required gates on design-level semantic defects

Date: 2026-08-14 (session)
Trigger: e2e resume terminal `judge_required_gate_failed` on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆) — the FIRST run to
reach the Judge. All 10 task_materialization gates passed; reachability/
verifier gates exposed design-phase defects plus one framework verifier-case
defect.

## Evidence (verified by exact offline reproduction)

Judge gate evidence (20 gates): 9 passed, 11 failed.

- 8 x `task_initial_rule_failed` (families 1, 2, 5, all tools):
  task initial_rules disagree with the actual reset state. Actual reset
  (rendered candidate runtime, /tmp/judge-repro): tool1 status="" (text),
  landing_page_id="" ; tool2 availability_status="available" (enum
  values[0]) ; tool3/4 status="requested" (enum values[0]). Frozen task
  rules instead assert: family1 status="not_ready", landing_page_id=None;
  family2 availability_status="unknown"; family5 status/landing_page_id/
  price_source/price_accuracy_score/reservation_id=None, availability_status
  ="unknown". The reset values are FRAMEWORK-DETERMINISTIC defaults
  (rendered scaffold _default: boolean False, integer 0, number 0.0,
  list [], enum values[0], timestamp "1970-01-01T00:00:00Z", else "")
  because world_rules.initial_rules is EMPTY — yet nothing disclosed those
  defaults to the model and no compile check verified the guesses.
  Family 4 (fresh shard from the previous repair) wrote NO initial rules
  and passed vacuously.

- 2 x `task_not_terminal_success_reward_plus_one` (family 3 baseline +
  verifier-3 idempotency case): submit_reservation transitions are
  degenerate — THREE transitions with IDENTICAL when
  (lodging_id+rate_id+guest_name+guest_contact all exist) setting status to
  requested / confirmed / failed. Sequential application = last one wins ->
  status always "failed"; reservation_id/confirmation_reference are never
  set by any effect. Success (confirmed + reservation_id exists +
  confirmation_reference exists) is unreachable -> reward 0.

- 1 x `local_tool_semantics_mismatch` (verifier-2, family2/tool2,
  alternate_difficulty): reproduced exactly
  (/tmp/verifier2-exact.py): detail {"failed": "precondition_guards",
  "tool": "search_rate_options", "rationale": "Require a positive adult
  count and a nonnegative child count."}. The framework's private verifier
  case passes RAW category-default arguments (adults=0) as varied_arguments
  for the action tool, violating the tool's own precondition guards; the
  composition checker correctly requires every guard to hold on the
  success trace. candidate.py _private_verifier_cases (1598-1649) must use
  guard-satisfying arguments (runtime._guard_arguments, runtime.py 703).

- Latent (verified by simulation reading): family 1 preview_lodging
  transitions key status off `information_ready` (result field) which NO
  transition ever sets -> status can never become "ready"; family 1
  success (status eq ready) would be unreachable even after the initial
  rules are fixed. Same class as family 3: model-written transitions have
  no path to the task success pattern. The Judge has no correction channel
  back to the design; design-time deterministic gates are the only honest
  convergence mechanism.

## Root cause

Model-written design semantics (task initial rules + tool transitions) are
checked for SHAPE but not for CONSISTENCY against the framework-owned
deterministic reset semantics and the recipe's reachable outcomes. Three
deterministic facts the framework already owns are neither disclosed nor
verified: (1) reset defaults, (2) transition degeneracy (identical whens /
when-referencing immutable result fields), (3) whether the simulated action
sequence can satisfy a success pattern. Plus one framework bug: verifier
private cases pass guard-violating arguments.

## Five-lens status

1. Project Agent view — not implicated.
2. Effective Prompt/input — SUPPORTED gap: semantic_catalog.fields rows
   carry source/tool/field/category but NOT the deterministic reset value;
   no disclosure that reset = scaffold defaults when world rules are empty.
3. Runtime Skill / Direct no-Skill — not implicated (Direct LLM nodes).
4. Code/execution boundary — SUPPORTED: (a) task_requirement compile
   (design.py 2438-2555) verifies goal names but not initial-rule values;
   (b) tool_semantics compile accepts identical-when transitions;
   (c) candidate.py 1598-1649 builds guard-violating verifier arguments;
   (d) the rendered scaffold owns reset defaults (candidate_templates
   runtime _default) that nothing else references.
5. Feedback/observability — SUPPORTED gap: judge.gate_evidence persists
   only gate_id/status/code/binding (candidate.py 1705-1714) — the
   runtime's detail (expected vs actual post_state, guard rationale) is
   dropped, so post-hoc attribution required offline reproduction.

## Alternatives rejected

- Weakness of the Judge: gates are honest and exact; failures reproduce
  offline 1:1.
- Candidate/materializer defect for initial rules: reset state equals the
  framework scaffold defaults, not materializer output; materializer only
  supplies arguments/initial_config.
- One-off re-roll without gates: model nondeterminism would repeat the
  same class of guesses; the frozen defective shards need both disclosure
  and deterministic verification.
- Design-time reachability as a new standalone node: rejected; the check
  belongs to the existing task_requirement compile (has tools+rules+family)
  with its local_corrections loop for model feedback.

## Owner / boundary

Framework compiler/validator (design.py _direct_tools + _direct_tasks),
prompt disclosure (same nodes), verifier-case construction (candidate.py).
The Judge and release authority stay untouched.

## Smallest next proof

After implementation: pure `--resume` must re-roll the tool_semantics and
task_requirement shards (prompt ids bumped), compile them under the new
gates, and the Judge must pass all 20 gates — then the run continues to the
Registry. Stop at the first new terminal and re-attribute.

## What remains unknown

- Whether the re-rolled model output converges under the new gates within
  the local correction budget (2 per shard).
- Registry/package gates beyond the Judge have never run in this run.
