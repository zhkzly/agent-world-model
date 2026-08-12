# Research: Cross-layer review — TaskRequirement source slimming

- Query: Independently review revision 2 of the TaskRequirement-only source-projection/compiler repair after the failed public Direct E2E.
- Scope: internal, read-only cross-layer critic.
- Date: 2026-08-12
- Decision: allow
- Plan digest: `sha256:c013eb6ef26f717920b22228476ce883cdebc558bb97ae42de92f0c6694c1e85` (verified against the complete plan bytes).
- Plan revision / count: 2 / 2.
- Scope classification: local Direct-LLM source projection and Designer compiler handoff; no committed Artifact ABI or downstream graph contract changes.

## Trigger and product target

The public run `run_a4cc77f4344e4aeba96ad081223bca70` safely stopped at
`task_requirement[member_registration]` after two strict rejections of a
non-error task rule's model-supplied `error_kind`; Candidate, Integration,
Judge, Package, and Registry did not run. The persisted Diagnosis identifies
the first deviation as making a framework-fixed `null` a repeated model-owned
field, compounded by duplicated input material.

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in
an isolated boundary, publish an immutable Registry `EnvironmentPackage`, and
expose only safe facts through Observe. This repair advances only the failed
Direct TaskRequirement transaction; it is not a claim of Design completion,
Runtime/Judge validity, Registry release, Repair, Expand, or Consumer success.

## Evidence reviewed

- Diagnosis and plan: `/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-task-requirement-redundant-source-fields.md` and `task-requirement-source-slimming-plan.md`.
- Governing contracts: `docs/agent-world-environment-generation.zh.md` §§6–9,
  `docs/direct-rewrite-execution-map.zh.md`, task `prd.md`, `design.md`,
  `implement.md`, and `node-contracts.md`; the relevant product rule is that
  framework compiles task semantics, Reward, Termination, and Verification
  requirements before CandidateBuild.
- Code facts: the current TaskRequirement compiler uses the generic RuleDraft
  shape at `agent_world/design.py:1938-2015`; its visible projection duplicates
  the family DifficultySchema and global bindings through each ToolDraft at
  `agent_world/design.py:2017-2029`. The generic compiler remains strict at
  `agent_world/design.py:349-532`.
- No external reference is needed. `implement.jsonl` and `check.jsonl` were
  intentionally not read by this research role.

## Impact chain and ownership

```text
Direct LLM task-only source JSON
  -> Designer task-local closed parser + framework `error_kind=None`
  -> existing RuleDraft validation/compiler
  -> unchanged committed TaskRequirement
  -> Modeling Gate / EnvironmentDesign
  -> Candidate / isolated Runtime / independent Judge
  -> Package / Registry / safe Observe
```

Designer remains the sole owner of the source projection, fixed-null injection,
validation, and TaskRequirement Artifact commit. Luna retains only semantic
choices in predicates, effects, rationale, citations, public-goal references,
and the four task-rule sections. No model gains Gate, retry, Candidate, Judge,
or release authority.

The changed raw proposal never crosses a graph edge: `GraphRunner.execute`
compiles before committing an Artifact (`agent_world/graph.py:469-510`), and
the TaskRequirement edge into Modeling Gate remains unchanged
(`agent_world/graph.py:353-364`). The projection/output-shape material is
already part of the semantic-revision calculation
(`agent_world/design.py:648-716`, `agent_world/graph.py:449-467`), so an old
task commit cannot be adopted as the revised node's result.

## Compatibility facts

- `TaskRequirement` retains the same six compiled rule tuples and family index
  (`agent_world/contracts.py:805-822`); all injected task-rule values therefore
  remain `RuleDraft.error_kind is None` without changing the committed shape.
- Runtime evaluates those committed tuples rather than source JSON
  (`agent_world/runtime.py:622-642`). Candidate planning receives committed task
  summaries (`agent_world/candidate.py:787-797`), and Registry cold-read
  validates the same TaskRequirement field set (`agent_world/candidate.py:2632-2646`).
- A family already owns exactly one `DifficultySchema`
  (`agent_world/contracts.py:768-801`), and each ToolDraft currently embeds the
  same global bindings catalog used by TaskRequirement
  (`agent_world/design.py:1460-1585`). Removing only those duplicate
  presentations loses no rule, binding, scope, citation, or difficulty meaning.
- ToolSemantics, WorldRules, error rules, ArtifactEnvelope, NodeSpec/EdgeSpec,
  WorkRecord, Candidate, Judge, Registry, Repair, Expand, and Consumer are
  unchanged consumers. This is compatible only if their generic RuleDraft wire
  contract remains strict and untouched.

## Smallest allowed implementation and proof

Implementation is allowed only for the plan's task-local boundary:

1. Define a TaskRequirement-only rule source shape with exactly
   `when`, `effects`, `rationale`, and `citation_indexes`. Any supplied
   `error_kind`—including `null`—must be rejected as an extra field before the
   framework adds `error_kind=None` to an internal compiler input. This avoids
   a hidden tolerant compatibility path.
2. Reuse the existing strict RuleDraft compiler after that injection. Do not
   relax or generalize `_compile_rules`, alter ToolSemantics/WorldRules source
   behavior, alter the committed RuleDraft/TaskRequirement classes, or add a
   node, retry, fallback, parser tolerance, or source ABI bridge.
3. Replace only the TaskRequirement visible projection with the stated exact
   one: family semantic fields with its single schema; one SemanticCatalog;
   each relevant tool's surface and four rule sections; WorldRules;
   CitationCatalog; and reachability policy. Exclude duplicate bindings/schema
   copies and framework artifacts/digests. Preserve the existing Artifact input
   closure and all semantic facts once.
4. Reconcile the task-specific source wording in `node-contracts.md` without
   rewriting the shared generic RuleDraft contract.

The minimum deterministic evidence is:

- absent task-source `error_kind` compiles to committed `None` in all four task
  sections; explicit `null` and every non-null value fail closed;
- ToolSemantics and WorldRules still require their existing generic field, and
  Tool error rules still require a bounded error kind;
- the captured model-visible projection has exactly one DifficultySchema and
  one bindings catalog, retains every required tool/world-rule/citation fact,
  and contains no Artifact or digest metadata;
- the revised source shape/projection changes the TaskRequirement semantic
  revision while the compiled TaskRequirement, Modeling inputs, and downstream
  ABI remain unchanged; and
- focused Design/Graph tests plus the planned full static suite pass.

The smallest real proof is one real Luna invocation at the exact frozen
`member_registration` TaskRequirement boundary using the committed parents of
`run_a4cc77f4344e4aeba96ad081223bca70`, the production Direct adapter, the
actual compiler, and immediate Observe. It must not add a production leaf CLI
or simulate the model. A terminal begins a new Observe-led diagnosis; a passed
leaf only permits the subsequent fresh public Direct E2E and its immediate
Observe.

## Non-claims, caveats, and next gate

- This allow proves neither a successful leaf nor a full Direct E2E. It makes
  no claim about CandidateBuild, isolated Runtime, Judge, Registry, release,
  Repair, Expand, Consumer, or model reliability.
- The plan/diagnosis presently reside in the clean worktree named above; the
  coordinator must provide this exact digest and this record to the target
  implementation/check context before dispatch. This reviewer makes no JSONL
  or source-file edits.
- The superseded digest
  `sha256:5b99f04d54bb9233ee50320dafadc0e6e7ba46dc28f9417d7be39cc4fb5e13de`
  cannot authorize implementation. This allow expires if the current digest,
  trust boundary, or relevant real scene changes.

Next permitted gate: the coordinator may add this matching allow record and
the exact revision-2 plan to the implementation/check context, then dispatch
the scoped implementer. Any scope expansion or new terminal returns to
Observe -> Diagnosis -> revised plan -> fresh critic.

