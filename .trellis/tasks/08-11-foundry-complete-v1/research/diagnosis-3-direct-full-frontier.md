# Diagnosis Record 3: Direct 剩余全链路前沿（offline bench 完整复现）

Date: 2026-08-14 (session)
Method: offline single-node bench (/tmp/e2e-driver.py + /tmp/bench_patch.py) driving
the REAL framework functions (integrate/judge) against the FROZEN design
(heads.json compiled_json) + FROZEN candidate source. Repo untouched.

## Frontiers found (all deterministic, all framework-owned semantics)

F1  candidate_teardown_failed (integration): both runtime scaffolds
    (_DESIGN_RUNTIME_BODY and candidate_templates/runtime.py) reply to close
    but never exit the stdin loop; CandidateProcess.close() waits 5s, kills,
    sees nonzero exit -> teardown_failed. Bench-verified fix: break after close.

F2  checker "first transition must fire" heuristic (runtime._run_recipe
    selected_rules = preconditions[:1] + transitions[:1]) is wrong for branch
    rules: search_room_offers.transitions[0] is the "unavailable" branch
    (when offers not_exists), so a CORRECT conditional runtime is rejected.
    Bench-validated replacement: reference-composition semantics —
      * every precondition guard must hold (positive form),
      * simulate all transitions whose when holds (in order) over the
        pre_state copy and require the result to EQUAL the observed post_state,
      * reject effect fired on the success trace -> mismatch,
      * no transition fired -> mismatch.
    With close-break + composition, integrate() PASSES all 6 recipes offline.

F3  submit_reservation precondition guards are INVERTED: rationale says
    "guest_id is required" but when=[guest_id not_exists]. One shard of the
    pre-C1 language ambiguity. Regenerate under the sharpened prompt.

F4  judge task rules: preview_to_offer_workflow (and others) fail
    task_initial_rule_failed / task_not_terminal_success_reward_plus_one.
    Root causes:
      a. initial_rules were compiled with field names collapsed to POST_STATE
         bindings ("last binding wins" in _name_to_index), while the model
         meant the initial/reset state; the checker matches them against the
         post-action trace -> guaranteed failure.
      b. failure_rules are written as rejection-path double negatives
         (reject/preserve effects, not_exists guards) — the task language
         never defined section semantics.
      c. success/failure/terminal rules carry effects at all; task rules
         should be when-only pattern matchers over the post-action view.
      d. the design-driven runtime's reset IGNORES initial_config; reset
         state = category defaults, not the materialized task context the
         initial rules describe.
    Bench: after normalizing F3 (bench-only), integrate passed and judge
    reached 2/6 reachability gates; the 4 failures are exactly (a)-(d).

## Five-lens status

Lens 4 (code/execution) is the supported cause everywhere: checker semantics,
task-rule compiler name resolution, runtime reset/close behavior, and the
design-language prompts (lens 2, sharpening needed). No agent/skill/model
fault. Lenses 1/3/5 healthy.

## Coordinate with previous records

- C1/C2/C3' from cross-layer-review-c8d540d0 stay correct; F3 shows the
  pre-C1 frozen shard must be regenerated (prompt_id bump required — prompt ids
  are static declared ids, not text hashes: changing prompt text WITHOUT
  bumping the id would silently reuse stale artifacts).

## Bench evidence paths

/tmp/e2e-driver.py, /tmp/bench_patch.py, /tmp/e2e-repro/ (workspace), the
frozen run: config/.agent-world-runs/runs/run_386e4f07c70d4f61be9cafbf82edcc55
