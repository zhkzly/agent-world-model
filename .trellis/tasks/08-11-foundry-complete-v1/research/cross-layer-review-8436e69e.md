# Cross-Layer Review — plan-goal-leaf-mapping (8436e69e)

Decision: **block**

Plan digest: 8436e69ee861be7b
Plan revision: 1 (single written revision; lineage continues direct-completion
fe33df95/0ff3ae1d but those allows are spent — this is a new scene)
Scope classification: claimed **Local**; actual minimum coherent scope is not
yet demonstrated (see "Scope honesty").
Revision count: 1

## Trigger

Real failed Direct/E2E run, run_386e4f07c70d4f61be9cafbf82edcc55 (pure resume
after the one-shot transport fix). Terminal: materializer_public_goal_invalid,
subject build.environment_candidate:702c42bc1708. Diagnosis Record 5
(diagnosis-5-goal-leaf-mapping.md) attributes the failure to a missing
index -> field-name/source/category mapping in the Task Materializer contract.

## Evidence (independently confirmed, read-only)

- Frozen materializer (config/.agent-world-runs/runs/run_386e4f07c70d4f61be9cafbf82edcc55/candidate_source/materializer.py)
  derives each public_goal value via semantic_value(task_type, path, category,
  ..., field = path.rsplit('/',1)[-1]). The leaf name is the SEMANTIC INDEX
  (e.g. "24", "25"), so the name-based branches (field == "offers",
  "result_status", etc.) never match and the value falls through to
  category_value(category, ...) — the srcutation that swaps offer list vs status
  enum. Diagnosis is causally supported.
- agent_world/contracts.py: public_goal_fields is tuple[int, ...] (semantic
  indexes). agent_world/design.py ~2586 builds public = ("/goal/{index}",
  categories[index - 1]) for index in task.public_goal_fields. category derives
  from the goal schema path; name/source derive from
  design.architecture.catalog.bindings (validated: public_goal_fields must be a
  subset of catalog_indexes, DesignContract.__post_init__ ~1073).
- agent_world/runtime.py _validate_schema/_validate_materialization enforce
  schema leaf-path equality and _category(pointer, category); the swapped
  values fail category here -> materializer_public_goal_invalid. Backstop is
  correct; the candidate is wrong, not the gate.
- agent_world/graph.py: CANDIDATE_NODES candidate_build mounts skill
  "engineer-environment-codegen" (line ~413); semantic_revision includes
  "agent_skill_digest": runtime_skill_digest(node.skill) (line ~609). So a
  SKILL.md text change re-invalidates candidate_build's semantic_revision and
  re-dispatches it on pure resume. Claim CONFIRMED as to re-dispatch.

## Critical compatibility finding the plan misses

There are TWO distinct projections and the plan targets the wrong one:

1. compile_implementation_contract() -> implementation-contract.json (the
   codegen agent's INPUT). It already carries per-task public_goal_fields (as
   NAMES via goal_field_name) and public_goal_schema in executable_tasks
   (_builder_task) and task_rule_summaries. This is where the agent's
   index-vs-name/category ambiguity lives. It is NOT key-set-validated against
   a closed shape at the task level in the same way.

2. _materializer_tasks() -> tasks/materializer_protocol.json (the runtime
   protocol, PERSISTED into the Registry). The plan's "Changes.1" adds
   "public_goal_fields" to _materializer_tasks. But the Registry re-validation
   path (candidate.py ~2880-3020) enforces EXACT key sets:

     set(protocol) != {"schema_version","operation","request_order",
       "response_order","tasks"} -> registry_design_metadata_invalid

     set(materializer) != {"task_family_index","public_goal_schema",
       "initial_config_schema","evaluator_goal_bindings",
       "instruction_template_digest","assurance_recipes",
       "verification_requirements","verification_digest"}
       -> registry_task_contract_invalid

   Adding a 9th key to each materializer task would break this exact-set
   validation at package/Registry time unless the validator is also amended.
   That makes it a coordinated change (materializer protocol + Registry
   validator + envpkg materializer_protocol_digest), not a Local one. The
   plan's "response shape unchanged / the mapping is input context, not
   output" is FALSE for this location: materializer_protocol.json IS a
   persisted, key-set-checked Registry artifact, not free-form agent input.

## Scope honesty

- Producer/consumer claimed: _materializer_tasks -> codegen agent. Actual
  codegen-agent input is implementation-contract.json (compile_implementation_contract),
  not materializer_protocol.json. The plan does not name the correct producer
  (compile_implementation_contract / _builder_task / task_rule_summaries).
- The change to _materializer_tasks crosses the materializer-protocol ->
  Registry validator boundary and the envpkg digest boundary, which the plan
  declares untouched ("Judge/package/Registry untouched" is internally
  contradictory with Change 1).

## Answers to review questions (brief)

1. Advances product target: partially — it removes a guessable index/name
   ambiguity so the codegen agent can produce a category-correct public_goal.
   Correct aim, wrong landing site.
2. Producer must be compile_implementation_contract (agent input); unchanged
   consumers (Judge, package, Registry) can only remain unchanged if the
   mapping lands in the agent-input projection, NOT materializer_protocol.json.
3. A mapping of (index, name, source, category) is semantically consumable;
   but only if it reaches the projection the agent actually reads.
4. Ownership is preserved only if the value remains bounded by the framework
   projection (deterministic resolution, no LLM authority over indexes); the
   plan keeps framework ownership of resolution but not of the correct artifact.
5. Request/revision/dependency/secrecy/authority: no secrecy change; no
   credentials; fine.
6. NOT honest as Local — the Registry key-set validator and the envpkg digest
   are affected by the proposed change location.
7. Smallest deterministic check = a unit assertion on the agent-input
   projection that each public_goal leaf carries a resolved
   (index, name, source, category); true-boundary proof = real resume
   re-dispatching candidate_build and the regenerated materializer passing
   _validate_materialization on families 2 and 4.

## Actionable feedback to plan writer

1. Move the mapping into compile_implementation_contract()'s per-task
   projections (executable_tasks via _builder_task and/or task_rule_summaries),
   which is the codegen agent's actual input — NOT _materializer_tasks. Source
   name/source from design.architecture.catalog.bindings and category from the
   public_goal_schema path (or categories[index-1]).
2. Either keep materializer_protocol.json byte-stable (strongly preferred, then
   Registry/Judge/package/Registry are genuinely untouched), OR explicitly
   classify this as coordinated and include the Registry validator exact-key
   update AND the envpkg materializer_protocol_digest consequence in the plan.
3. Name the correct producer/consumer pair and cite that
   implementation-contract.json's executable_tasks already exposes
   public_goal_fields (names) + public_goal_schema, so the fix is to make the
   INDEX->NAME->CATEGORY correspondence explicit there, not to duplicate it in
   the runtime protocol.
4. Keep the SKILL.md wording instructing "map each public_goal leaf through the
   declared mapping, never via path suffix" — that part is correct and the
   digest-invalidation re-dispatch is correctly reasoned.
5. Do not weaken the _validate_materialization category gate or add any
   compatibility/fallback branch; the gate is correct.

## Non-claims

- We do not claim the regenerated materializer passes; a further failure is a
  new observation (plan states this correctly).
- This review does not run live e2e or model calls (read-only critic).

## Next permitted gate

After the plan is revised to land in the correct projection (or explicitly
coordinated with the Registry validator), resubmit for review. At most one
further revision for this lineage (revision 2 of 2) before needs_human.
