# Coordinated minimal plan — close the remaining Design Direct contracts

- Lineage: `remaining-design-direct-contract-closure`, revision 2/2
- Diagnosis: `diagnosis-e2e-remaining-direct-contract-closure.md`
- Real scene: `run_1bec958e41ae4207beb4a7b40149f9c0`
- Proposed scope: coordinated remaining Design Direct source/validator closure
- Revision feedback addressed:
  `cross-layer-review-7c80f044-remaining-design-direct.md`

## Product target and role ownership

The target remains an arbitrary natural-language need becoming an
evidence-grounded executable environment, independently exercised as an
untrusted candidate and atomically published as an immutable Registry
`EnvironmentPackage`, with safe facts exposed through Observe. This plan closes
the remaining Design semantic handoffs but proves none of Candidate, Judge,
Registry, Repair, Expand or Consumer/SFT/RL.

Direct LLMs own only semantic RuleDrafts, curriculum meanings/scopes and public
goal selections. Framework owns frozen tool/task coordinates, shared contract,
semantic indexes, exact grammar, validation, Rule IR, digests, attempts,
Findings, Judge and release. Agent and candidate-process boundaries are
unchanged.

## One exact shared RuleDraft source grammar

Add one small module-local string constant beside `_compile_rules`; it is the
single shared ADT declaration, not a prompt framework or schema generator:

```text
Right =
  {kind:"literal",value:finite JSON scalar or <=32 finite scalar items} |
  {kind:"semantic_ref",semantic_index:frozen SemanticCatalog index}
PredicateDraft =
  {left_semantic_index:frozen index,
   operator:eq|ne|lt|le|gt|ge|contains|not_contains|exists|not_exists,
   right:Right}; exists/not_exists require literal null
EffectDraft =
  {target_semantic_index:frozen index,
   operation:set|increment|decrement|add|remove|preserve|reject,
   value:finite JSON scalar or <=32 finite scalar items or
         {kind:"semantic_ref",semantic_index:frozen index}};
   preserve/reject require null
RuleDraft =
  {when:0..6 PredicateDraft,
   effects:1..6 EffectDraft,
   error_kind:null in non-error sections;
              [a-z][a-z0-9_]{0,63} (1..64 code points) in errors[],
   rationale:stripped nonempty text <=300 code points,
   citation_indexes:0..8 unique frozen indexes; [] when no catalog is supplied}
```

Append this exact ADT plus a concise “one compact complete JSON object; use only
frozen indexes; recheck the whole object after correction” objective to the
three consumers. Do not ask the model for rule IDs, schema keywords, hashes,
sizes, gates or release facts.

## Node-specific source contracts

1. **SharedToolSemantics** model output drops the exact `tool_indexes` echo and
   each redundant `error_policy[].tool_index` echo. It becomes exactly:

   ```text
   {atomicity|concurrency|idempotency: 1..group_size arrays of 1..group_size
      frozen indexes, with every member appearing exactly once per dimension,
    ordering|compensation: 0..8 stripped nonempty text items <=160 code points,
    error_policy: exactly group_size stripped nonempty policy strings <=280
      code points in frozen order}
   ```

   Framework binds the already-frozen ordered group, zips its members to the
   ordered policies, and includes both in the compiled contract/digest. The
   model still receives the exact group and tool projections as input.
2. **ToolSemantics** model output becomes only:

   ```text
   {preconditions:1..6 non-error RuleDraft,
    transitions:1..6 non-error RuleDraft with >=1 state-changing effect,
    postconditions:0..6 non-error RuleDraft,
    errors:0..6 error RuleDraft}
   ```

   Remove `tool_index` and `shared_contract` from source keys. Compiler binds
   `surface.tool_index` and the already-frozen `selected` contract/digest exactly
   as it does today. Downstream ToolDraft bytes/meaning stay unchanged.
3. **WorldRules** output remains `initial_rules[0..8]` and
   `invariants[0..16]`, both non-error RuleDrafts with `citation_indexes=[]`.
   State explicitly that empty invariants are valid and local Tool rules must
   not be duplicated.
4. **CurriculumPlan** disclose the exact current `families[1..8]` grammar:
   `task_family_id` matches `[a-z][a-z0-9_]{0,63}` (1..64 code points),
   objective <=500, one frozen actor index, 1..tool_count unique frozen tool
   indexes, and 1..6 unique dimensions. Each dimension name and each of its
   2..5 unique level names matches `[a-z][a-z0-9_-]{0,39}` (1..40 code points,
   including the currently accepted hyphen); dimension/level meanings are
   <=300. Sampling intent is <=300 and citations are 1..6 unique frozen
   indexes. Framework derives `task_family_index`, ordered DifficultySchema
   keys and digest. This discloses the current accepted grammar; it does not
   tighten or normalize names.
5. **TaskRequirement** model output becomes only public goal fields plus
   initial/success/failure/terminal RuleDraft sections with current bounds.
   Remove `task_family_index`; compiler binds `frozen.task_family_index`.
   DifficultySchema stays read-only input and cannot be redefined.

Update only these source cards and the shared ADT in `node-contracts.md` to
match runtime names. WorldArchitecture and all Agent/Candidate cards remain
unchanged.

## Deterministic validator closure

Make only these local validation changes:

- Shared atomicity/concurrency/idempotency arrays must contain integer frozen
  members exactly once across each dimension; bind the frozen ordered group and
  ordered error-policy coordinates in framework code and enforce the same
  invariant in `SharedToolContract` so cold typed consumers agree with the
  compiler.
- Before any `set(...)`, first reject non-integer RuleDraft citation indexes,
  Curriculum tool/citation indexes and Task public-goal indexes with the
  existing node-specific DesignError path/category.
- Translate only Curriculum `DifficultyLevel`/`DifficultyDimension`/compiled
  schema `ValueError` into `curriculum_plan_invalid` at the exact family
  dimension path. Duplicate/invalid dimension and level names remain rejected;
  no coercion or normalization is added.

No generic schema engine, exception blanket, new helper module or validator DSL
is permitted.

## Identity and downstream compatibility

Changed model shapes rotate semantic revision for SharedToolSemantics,
ToolSemantics, WorldRules, CurriculumPlan and TaskRequirement. Node IDs, ports,
edges, routes, groups, call counts and correction topology are fixed.

Compiled `SharedToolContract`, `ToolDraft`, `WorldRuleSet`, `CurriculumPlan` and
`TaskRequirement` dataclasses and Artifact kinds remain the downstream ABI.
The SharedTool digest still binds the framework-injected exact ordered group.
ModelingGate, Candidate projection, Package and Registry continue consuming the
same typed values; only invalid overlap and redundant source echoes disappear.

## Deterministic checks

Add focused tests proving:

1. all three RuleDraft recipients see the exact same ADT, including the
   1..64 error-name grammar, and correct section-specific rules;
2. SharedToolSemantics/ToolSemantics/TaskRequirement model outputs contain no
   frozen coordinate echo, SharedTool payload or digest, while compiled outputs
   bind the exact frozen values and retain the same downstream typed ABI;
3. the real failure class receives an actionable exact RuleDraft contract and a
   valid replacement commits; a repeated identical invalid object still stops
   after two calls;
4. WorldRules empty invariants and empty citations remain valid; duplicates of
   local rules remain rejected;
5. Curriculum runtime fields/bounds exactly match its visible grammar and task
   card, including hyphen-permitting 1..40 dimension/level names; duplicate or
   invalid names and malformed indexes become typed corrections, never raw
   Python errors;
6. Shared domains reject duplicate, overlap, unknown and non-integer members,
   and accept an exact split;
7. malformed RuleDraft/Task index arrays return typed node errors;
8. each changed semantic identity rotates while graph/node/edge/route/group and
   two-attempt topology remain unchanged;
9. full DesignContract/ModelingGate and package projections retain the same
   typed compiled fields.

Run focused/full pytest, Ruff format/check, mypy, compileall, diff check and the
legacy-reference firewall. Keep production Python at or below 10,320 lines;
delete obsolete echo validation/string duplication rather than adding layers.

## Real proof sequence

After a fresh independent Terra/max critic `allow` and implementation check:

1. run one diagnostic partial-node suffix using the failed public run's exact
   immutable Architecture/Evidence Artifact references: regenerate strict
   SharedTool, then invoke only `tool_semantics[register_member]`; inspect only
   Work/Artifact/operation facts and safe Observe. This proof may not resume or
   adopt the failed run, publish a package, infer release, or supply evidence to
   Registry;
2. only if both pass within existing correction bounds, run one fresh public
   Direct request to terminal Observe so WorldRules, Curriculum and
   TaskRequirement execute naturally;
3. any different terminal starts a new Diagnosis Record. No blind retry,
   output edit, model/response-mode change, node split or later-child work is
   authorized here.
