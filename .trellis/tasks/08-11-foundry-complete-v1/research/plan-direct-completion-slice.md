# Repair Plan: Direct-completion slice (frontier F1-F4 + resume hardening)

Lineage: Diagnosis Records
  diagnosis-integration-local-tool-semantics-mismatch.md (fixed, c8d540d0)
  diagnosis-2-resume-candidate-workspace-materialization.md
  diagnosis-3-direct-full-frontier.md
Trigger: real e2e run_386e4f07c70d4f61be9cafbf82edcc55 rejected at
  candidate_teardown_failed after the c8d540d0 repair; offline bench
  (/tmp/e2e-driver.py) then reproduced and fixed every remaining frontier
  deterministically with zero LLM calls.

## Product target restated

Natural-language need -> evidence-grounded design -> real isolated runtime ->
independent Judge (all required hard claims) -> immutable Registry package ->
safe Observe; released package feeds SFT/RL through the fixed episode
protocol. This plan completes the first Direct release path.

## Scope classification

Larger slice, Direct only. Designer language (F3/F4), Builder runtime
renderer (F1/F4d), Judge checker/task evaluator (F2/F4), and resume
materialization (E). Expand/Consumer untouched; Repair reuses the same
bounded node-local correction loop.

## F1 - runtime teardown (both scaffolds)

candidate.py _DESIGN_RUNTIME_BODY and candidate_templates/runtime.py:
after responding to close, break the protocol loop (exit 0). CandidateProcess
close() then completes without the 5s kill. Deterministic check: rendered
runtime driven over JSONL exits 0 after close (extends the existing
test_rendered_runtime_applies_only_matching_when).

## F2 - checker reference composition (runtime.py _run_recipe)

Delete the selected_rules = first-precondition+first-transition heuristic.
New check (bench-validated, all 6 recipes pass):
  * every precondition guard must hold (positive form; failure semantics
    remain framework-fixed reject+preserve),
  * simulate tool.transitions in order: a rule whose when holds applies its
    effects to a copy of the pre_state; set/increment/decrement/add/remove
    mutate, preserve is a no-op, reject fired on the success trace raises
    local_tool_semantics_mismatch (failed="composition"),
  * at least one transition must fire,
  * the composed state must EQUAL the observed post_state of that tool
    (failed="composition", expected vs actual in the detail).
_task_outcome and verifier IR are unchanged; _run_recipe's trace shape
unchanged except it additionally records reset_state (F4 needs it).

## F3 - regenerate the inverted tool shard (Designer language + id bump)

design.py tool_semantics prompt (already guard-only from c8d540d0) gets:
  * positive-form guard statement + example,
  * the two named anti-patterns observed in frozen artifacts: precondition
    carrying any effect (preserve no-op), and INVERTED guards
    (not_exists when the rationale says "required") — both rejected with the
    existing actionable violated_condition.
  * prompt_id bump tool-semantics@1 -> @2 so pure --resume regenerates the
    frozen shards instead of reusing stale ones (prompt ids are declared
    ids, not text hashes — bumping is the invalidation contract).

## F4 - task-rule language + judge semantics (design.py + runtime.py)

a. design.py task_requirement compile:
   * success/failure/terminal rules compile as WHEN-ONLY pattern matchers
     (effects must be [] — reject non-empty with actionable violation);
   * initial_rules keep effects but their field names resolve against a
     RESET-STATE binding catalog (source "reset_state"), never post_state;
   * success/failure/terminal field names resolve against post_state (+
     argument) bindings.
b. prompt rewrite for task_requirement (semantics per section + example +
   the observed anti-patterns: reject/preserve effects in failure rules,
   initial rules written against post fields) + prompt_id bump
   task-requirement@1 -> @2.
c. runtime.py: _run_recipe records the reset snapshot as
   trace["reset_state"] (all tools); _task_outcome checks every initial
   rule against the reset view; success = any success-rule when holds;
   failure = any failure-rule when holds; terminal likewise; success AND
   failure both holding raises task_rule_ambiguous (a design defect, routed
   to task repair — never a runtime pass).
d. runtime reset honors initial_config: _DESIGN_RUNTIME_BODY reset applies
   request["initial_config"]["tools"] values over category defaults (missing
   fields keep defaults), so reset state matches the materialized task
   context the initial rules describe.

## E - resume workspace materialization (candidate.py + supply_chain.py)

Persist the candidate source closure BYTES in the candidate artifact payload
(new key "source_files": [{path, digest, size, mode, content_base64}],
sizes bounded by the existing max_total_bytes=160000 admission); when
candidate_build is skipped on resume, CandidateExecutor materializes the
workspace from the committed closure before integration/judge. This turns
--from integration retries honest and kills the empty-workspace failure
(diagnosis-2). Content is already scanned/digest-verified at admission;
registry/package projections unchanged (manifest shape untouched).

## Producer -> consumer chain

tool_semantics/task_requirement prompts -> frozen ToolDraft/TaskRequirement
(types unchanged; task rules now when-only, initial rules reset-view) ->
design.json projection (unchanged shape) -> Builder renderer (reset honors
initial_config) -> integration/judge checker semantics -> package/Registry
(untouched). The fixed SFT/RL interface is untouched (rule_ir.json carries
the same RuleDraft schema; Consumer episode protocol unchanged).

## Deterministic checks

* existing 283 tests stay green; updated tests for the new language gates
  (task rules with effects rejected; inverted guards not auto-rejected at
  compile but caught by integration as design defects — prompt+example is
  the primary lever, judge is the backstop).
* new/extended: rendered-runtime close exits 0; reset applies initial_config;
  composition checker unit tests (branch rules: only matching rule applied;
  no-fire mismatch; reject-on-success mismatch); _task_outcome reset-view
  initial rules + success/failure ambiguity -> task_rule_ambiguous.
* full offline bench (/tmp/e2e-driver.py) must show integrate passed AND
  judge all-reachability-passed for the bench-normalized design.

## True-boundary proof

1. offline bench full pass (above).
2. real run: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
   (pure resume: bumped prompt ids regenerate the F3 shard and task rules
   with real LLM; research evidence is reused) -> expect integration passed,
   judge passed, package+registry released. Observe after terminal.
3. Product Alignment Checkpoint recorded at the proof terminal.

## Explicit non-claims

* We do not claim the regenerated model output is correct until the real
  judge passes (if a regenerated shard still fails integration/judge, that
  is a fresh diagnosis, not this plan's failure).
* Expand, Consumer, and auto-capture are not implemented here.
* Legacy frozen artifacts that fail under the corrected checker are expected
  to regenerate via the prompt-id bump; no compatibility path is added.

## Files touched (after allow)

agent_world/candidate.py (runtime body close-break, reset initial_config,
  source_files persistence + resume materialization)
agent_world/candidate_templates/runtime.py (close-break)
agent_world/runtime.py (_run_recipe composition + reset_state,
  _task_outcome semantics, task_rule_ambiguous)
agent_world/design.py (tool_semantics prompt + id bump; task_requirement
  prompt/compile + id bump)
agent_world/graph.py (prompt ids only)
tests/* (language-gate updates + new checker tests)
task JSONL allow records
