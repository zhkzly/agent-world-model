# Plan — make the TaskRequirement source projection minimally semantic

## Goal

Advance the same natural-language-request-to-released-EnvironmentPackage path
by repairing only the first failed TaskRequirement handoff. Keep the graph,
committed contracts, strict compiler, correction budget, downstream Candidate
path, and release authority unchanged.

## Minimal implementation

1. Give `task_requirement` a task-only non-error rule source shape that omits
   `error_kind`. Predicates, effects, rationale, citations, all four rule
   sections, and their current bounds remain unchanged.
2. At this task-only compiler boundary, inject `error_kind=None` before calling
   the existing strict RuleDraft compiler. An explicitly supplied non-null
   value remains invalid; no business meaning is synthesized by code.
3. Replace the current dataclass dumps with one explicit task-only input
   projection:
   - `family`: objective, actor/tool scope, one DifficultySchema, sampling
     intent, and family citations;
   - `semantic_catalog`: the one frozen bindings catalog;
   - each relevant `tool`: tool index, surface, and pre/transition/post/error
     business rules, but not its duplicate bindings or computed digests;
   - `world_rules`: initial rules and invariants, without artifact/digest;
   - `citation_catalog` and the existing reachability policy.
   No semantic names, rules, meanings, citations, or scope are summarized or
   removed.
4. Reconcile only the TaskRequirement source contract in `node-contracts.md`
   and focused tests. Do not change the canonical committed TaskRequirement,
   RuleDraft, Artifact envelope, NodeSpec/EdgeSpec, WorkRecord, or Observe ABI.

## Impact chain and ownership

- **Producer:** Luna still proposes one complete TaskRequirement source draft
  for one frozen family; it now owns only fields with semantic choices.
- **Changed handoff:** model-visible source JSON omits deterministic
  `error_kind`, repeated bindings/schema copies, Artifact identities, and
  digests while retaining each upstream semantic fact once.
- **Compiler:** Designer framework injects fixed `None`, then reuses the same
  predicate/effect/citation validation and commits the same typed RuleDraft and
  TaskRequirement shape.
- **Immediate consumer:** Modeling Gate receives the same task family index,
  public-goal indexes, four compiled rule tuples, and Artifact ref.
- **Later consumers:** EnvironmentDesign, BuildPlan, CandidateBuild,
  Integration, Judge, Package, Registry, Repair, Expand, and Consumer contracts
  are unchanged. Prompt projection/shape changes must produce a new semantic
  revision, so old task commits cannot masquerade as current results.
- **Authority:** Luna owns semantic proposals; framework owns deterministic
  null injection, validation, Artifact commit, retry admission, Judge, and
  release.

Scope classification: local model-source/compile-boundary correction. The
external committed meaning and every downstream ABI stay unchanged.

## Checks and true-boundary proof

1. Focused tests prove a task source rule without `error_kind` compiles to
   `RuleDraft.error_kind is None`; a non-null supplied value still fails; the
   model projection has one DifficultySchema and one bindings catalog with no
   Artifact/digest metadata; all tool/rule/citation semantics remain visible;
   the output shape omits the field; and semantic revision changes.
2. Run focused Design/Graph tests, then full pytest, Ruff format/check, mypy,
   compileall, and legacy firewall.
3. Obtain an independent read-only implementation check after code changes.
4. Reuse the exact committed parents from public run
   `run_a4cc77f4344e4aeba96ad081223bca70` and invoke only
   `task_requirement[member_registration]`. Read Observe immediately. A strict
   commit permits one fresh public E2E; any terminal starts a new diagnosis.

## Explicit non-scope

- No new node, graph, generic schema DSL, callback, scheduler, profile, retry,
  parser tolerance, SDK change, model fallback, or compatibility path.
- No TaskRequirement split and no broad RuleDraft redesign.
- No removal of `when/effects`, because downstream Runtime/Judge compilation
  consumes those semantics.
- No Candidate, Repair, Expand, Consumer, Judge, Registry, or release behavior
  change.

## Non-claims

Green deterministic checks prove only source/compile compatibility. A passed
frozen TaskRequirement leaf does not prove the remaining Design suffix,
Candidate, isolated Runtime, Judge, Registry, E2E, Repair, Expand, or Consumer.
