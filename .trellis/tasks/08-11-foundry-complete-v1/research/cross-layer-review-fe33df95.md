# Cross-Layer Review: fe33df95 (Direct-completion slice F1-F4 + resume hardening)

## Decision

**allow** — the plan is the largest honest slice that actually completes the Direct
path, coordinates every genuinely affected framework boundary, and does not weaken
any Judge/release invariant or the fixed SFT/RL interface. All six frontier facts
(F1-F4 + E) are independently verified against frozen artifacts and framework code;
the proposed semantics make the reachability gates satisfiable WITHOUT weakening
them, and the prompt-id bump invalidation contract is grounded in the real
semantic-revision mechanism.

## Identity

- Plan digest (sha256 of plan file bytes): fe33df958e76f902 (short fe33df95), re-verified.
- Plan revision: R1 (no prior review under this digest; it folds three diagnosis records + the c8d540d0 correction).
- Revision count: 1 (skill permits at most 2 revisions per lineage).
- Reviewed file: research/plan-direct-completion-slice.md.

## Scope classification

Larger slice, Direct only. Changes the Designer framework language (F3/F4), the
Builder design-driven runtime renderer (F1/F4d) and resume materialization (E), and
the Judge-side checker/task evaluator (F2/F4). Expand/Consumer untouched and recorded
as explicit non-claims; Repair reuses the same bounded correction loop. Honest: the
four frontiers are one coupled producer->consumer semantic contract, not four
independent local patches.

## Trigger

Real e2e run_386e4f07c70d4f61be9cafbf82edcc55 (need=用户预订宾馆, config/agent-world.example.toml)
rejected at candidate_teardown_failed after the c8d540d0 repair. Observe scene
(read-only CLI, run this review) confirms terminal candidate_teardown_failed, release
not_published, three block_release findings: local_tool_semantics_mismatch
(b7d139db7142fd72), candidate_dependency_metadata_missing (b7d139db7142fd72),
candidate_teardown_failed (864bb43a22bcb3e4). judge/package/registry all not_run.

## Diagnosis / Observe evidence (independently verified)

- F1 teardown: both main() loops (candidate.py _DESIGN_RUNTIME_BODY; candidate_templates/runtime.py)
  reply to close with status ok but never break; CandidateProcess.close() (runtime.py ~172-199)
  waits 5s then kills -> nonzero exit -> candidate_teardown_failed. Verified.
- F2 checker heuristic: _run_recipe (runtime.py ~660-767) uses selected_rules =
  preconditions[:1] + transitions[:1]. The branch-rule defect (search_room_offers.transitions[0]
  = unavailable branch) is structurally real. /tmp/bench_patch.py installs the exact
  reference-composition semantics: every precondition guard positive-form; simulate matching
  transitions in order over a running copy; reject-on-success -> composition mismatch; no-fire ->
  mismatch; composed == observed post_state. Not self-fulfilling: a blind all-transitions runtime
  yields composed != actual post_state (still caught), while the branch case is handled correctly.
- F3 inverted guards: frozen design:tool_semantics:submit_reservation has preconditions with
  when=[not_exists guest_id/offer_id/contact_email] AND reject effects, while all three argument_fields
  are required=true and rationale says required; postconditions carry preserve. Exactly the named anti-pattern.
- F4 task rules: frozen design:task_requirement:preview_to_offer_workflow initial_rules[0] carries set effects
  against semantic indexes 14/45/24/25 = post_state bindings (last-binding-wins in _name_to_index,
  design.py ~407); failure_rules carry reject/preserve + not_exists; success/terminal rules carry preserve. Confirms F4a/b/c.
- F4d reset: _DESIGN_RUNTIME_BODY reset branch calls _init() (category defaults only) and ignores
  request initial_config; _run_recipe sends initial_config in the reset payload, so reset state never matches
  the materialized task context.
- E persistence: candidate_build compiled_json manifest = {entrypoint, files(9 x {path,digest,size,mode}),
  materializer_entrypoint, source_digest} — NO content bytes. _source_bodies (candidate.py ~2555) reads bytes
  from the live root only; resume --from integration skips candidate_build -> empty workspace ->
  candidate_dependency_metadata_missing. max_files=10 / max_total_bytes=160000 admission bounds real (candidate.py ~415-425).
- Id-bump contract: NodeSpec.prompt_id is a declared string (tool-semantics@1, task-requirement@1, graph.py ~325/~358),
  NOT a text hash. semantic_revision() (graph.py ~593-610) hashes prompt_identity=node.prompt_id but not raw prompt text;
  should_skip reuses a head only on digest match. Editing prompt text without bumping the id leaves the digest unchanged
  -> silent stale reuse. Bumping to @2 is the correct and only invalidation contract. Verified.

## Affected trust boundary

Designer framework compile + Direct tool_semantics/task_requirement prompt language (F3/F4) -> Builder framework
design-driven runtime renderer + resume workspace materialization (F1/F4d/E) -> Judge-side integration checker
and task evaluator (runtime._run_recipe shared by integrate+judge; _task_outcome) (F2/F4) -> package/Registry
(unchanged shape).

## Repeated product target

Natural-language EnvironmentRequest -> evidence-grounded design -> real isolated runtime -> independent Judge
(all required hard claims) -> immutable Registry EnvironmentPackage -> safe Observe; released packages later feed
SFT/RL through the fixed Consumer episode protocol.

## Impact chain (producer -> consumer)

tool_semantics/task_requirement prompts -> frozen ToolDraft/TaskRequirement (types unchanged; contracts.py 551-573/868+
carry no emptiness cross-validation) -> design.json projection (shape unchanged) -> Builder renderer (reset honors
initial_config) -> integration/judge checker semantics -> package world/rule_ir.json (same RuleDraft schema) -> Registry
(manifest shape untouched) -> future framework-owned Consumer (rule_ir evaluator, s12.3; training side only sees
PublicTask/reward/termination, s12.4). Fixed SFT/RL interface untouched.

## Owners

- F1: Builder framework (candidate.py + candidate_templates/runtime.py close-break).
- F2/F4: Judge framework (runtime.py _run_recipe composition + reset_state; _task_outcome; task_rule_ambiguous).
- F3/F4: Designer framework (design.py tool_semantics + task_requirement prompt/compile + prompt-id bumps).
- E: Builder/Controller (candidate.py + supply_chain.py resume materialization).
- The runtime Codex agent is NOT an owner (candidate.py overwrites runtime.py).

## Compatibility facts (verified, not assumed)

- RuleDraft/EffectDraft/TaskRequirement/ExecutableTaskContract types unchanged; changes are compile-time semantics
  (when-only for success/failure/terminal, reset-view bindings for initial_rules) + runtime-recorded reset_state.
- Package manifest source_files entries remain {path,digest,size,mode} (via _entry, candidate.py ~2169); E's content_base64
  belongs to the candidate ARTIFACT payload only and must NOT leak into the package manifest/Registry projections
  (plan states manifest shape untouched — implementer must keep the two keys distinct).
- envpkg v3 already declares a <candidate source closure> (s12.1), so persisting source bytes is aligned with the
  release closure contract, not a new leak; content already admitted/scanned/digest-verified (max_total_bytes=160000);
  no secrets enter (closure = candidate's own materializer/runtime/pyproject/uv.lock/LICENSE).
- 283 tests collected (uv run pytest --collect-only -q), matching the plan's existing-suite claim.

## Unproved consumers

- Future Consumer evaluator over rule_ir.json not implemented here; interface-level claim holds, but consumption of
  regenerated when-only task rules is the Consumer child's proof.
- Regenerated shards: plan honestly does NOT claim regenerated F3/task-rule output is correct until the real judge passes.
- Expand/Consumer/auto-capture remain unimplemented (explicit non-claims).

## Smallest allowed implementation and proof plan

1. F1: break the protocol loop after reply to close in both runtime scaffolds (exit 0).
2. F2: replace the selected_rules heuristic in _run_recipe with reference-composition semantics; record trace reset_state.
3. F3: sharpen tool_semantics prompt (positive-form statement + example; name the two anti-patterns) with actionable
   violated_condition; bump prompt_id tool-semantics@1 -> @2.
4. F4: task_requirement compile when-only for success/failure/terminal; initial_rules resolve against reset-state bindings;
   runtime reset honors initial_config; _task_outcome checks initial rules against reset_state and raises
   task_rule_ambiguous on success+failure; bump task-requirement@1 -> @2.
5. E: persist source closure bytes (source_files + content_base64, bounded by max_total_bytes) in the candidate artifact;
   materialize the workspace from committed closure on resume that skips candidate_build.
6. graph.py: bump the two prompt ids only; add allow record to implement.jsonl/check.jsonl; Product Alignment Checkpoint at proof terminal.

## Deterministic checks

- Rendered runtime exits 0 after close over JSONL (extends test_rendered_runtime_applies_only_matching_when).
- reset applies initial_config over category defaults.
- Composition unit tests: only matching branch applied; no-fire mismatch; reject-on-success mismatch.
- _task_outcome reset-view initial rules + success/failure ambiguity.
- New language gates: task rules with effects rejected; inverted guards rejected at compile with actionable violated_condition.
- Full 283-test suite green except enumerated language-encoding fixture updates.

## True-boundary proof (smallest real)

1. Offline bench (/tmp/e2e-driver.py + /tmp/bench_patch.py) full pass: integrate passed and judge all-reachability-passed,
   zero LLM calls.
2. Real run: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55 (pure resume; bumped ids regenerate
   the F3 shard + task rules with real LLM; evidence reused) -> integration passed, judge passed, package+registry released;
   Observe after terminal.
3. Product Alignment Checkpoint recorded at the proof terminal.

## Explicit non-claims

- Regenerated model output correctness is NOT claimed until the real judge passes.
- Expand, Consumer, and auto-capture are NOT implemented here.
- Legacy frozen artifacts that fail under the corrected checker regenerate via the prompt-id bump; no compatibility path added.

## Reviewer notes (non-blocking)

- E must keep candidate-artifact source_files (with content_base64) strictly separate from package-manifest source_files
  (which stay {path,digest,size,mode}); leaking content_base64 into the manifest/Registry breaks _source_bodies/_entry.
- Inverted guards are a semantic (not syntactic) defect: correct that the plan relies on prompt+example as primary lever and
  the composition checker as backstop rather than compile-time auto-rejection. The current checker already rejects the
  frozen inverted shard (predicates fail), so regeneration is required, not optional.
- Implementer should enumerate the exact test fixtures updated for the new language gates.

## Next permitted gate

Implementation dispatch after the allow record lands in implement.jsonl and check.jsonl, then the smallest real proof via
agent-world-real-execution-proof, then Observe. A new failed scene starts a new diagnosis and does not inherit this
review's hypothesis. This allow expires if the plan digest, affected trust boundary, or latest relevant real scene changes.

