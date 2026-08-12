# Diagnosis — remaining Direct Design contracts hide shared source IR

## Expected behavior and owners

After Architecture and SharedTool commit, each ToolSemantics shard is one
prompt-only Direct LLM transaction for one tool's minimum sufficient business
rules. WorldRules, CurriculumPlan and each TaskRequirement are later bounded
Direct semantic transactions. Models own only RuleDraft/task meanings.
Framework code owns frozen coordinates, shared contracts, indexes, digests,
closed grammars, compilation, validation, correction, Work/Finding, Judge and
release. Agents and the untrusted candidate process are not involved in these
nodes.

## Real scene and chronology

Fresh public run `run_1bec958e41ae4207beb4a7b40149f9c0` passed Research,
WorldArchitecture and `shared_tool_semantics[1-2-3-4-5-6-7]`. The first
`tool_semantics[register_member]` Luna proposal was rejected at
`$.preconditions[0]` because the object did not use the compiler's exact
RuleDraft fields. The safe correction reported the same path and condition.
The second complete JSON proposal failed at the identical path/condition.

Both calls completed normally through Luna: 4,781/4,813 input tokens and
1,526/1,833 output tokens. There was no non-JSON response, timeout, truncation
fact, Skill, tool, workspace, Agent or candidate process. Framework committed
no ToolSemantics Artifact, one failed WorkRecord and one blocking Finding;
Observe reports `rejected` and Registry `not_published`.

## Actual recipient defect

The visible shape says only `preconditions[1..6 RuleDraft]` and similar section
names. It never defines RuleDraft, PredicateDraft, EffectDraft, closed
operators, finite literal/reference forms, error-kind rules, rationale or
citations. The correction likewise cannot reveal those missing fields. The
task document defines the ADT for humans, but it is not runtime model input.

The same hidden ADT is referenced by the still-unexecuted `world_rules` and
`task_requirement` shapes. `curriculum_plan` exposes nested field names but not
the compiler's exact text/index/uniqueness bounds, while its task card still
uses obsolete `task_families/name/difficulty_dimensions` names instead of the
runtime `families/task_family_id/dimensions` contract. These are coordinated
producer-contract defects, not four independent model failures.

## Authority and validation audit

Three framework-owned values are incorrectly assigned to model output:

- SharedToolSemantics requires the model to echo the already-frozen group
  `tool_indexes` and repeat each exact member in its ordered error policy;
- ToolSemantics requires the model to echo `tool_index` and the complete frozen
  `shared_contract`, including its framework digest;
- TaskRequirement requires the model to echo `task_family_index`.

Both compilers already possess those immutable inputs and can bind them without
model participation. Removing the echoes changes no compiled ToolDraft or
TaskRequirement meaning and reduces output size.

The canonical document also requires each SharedTool atomicity/concurrency/
idempotency domain set to exactly split the frozen group. Current prompt,
compiler and `SharedToolContract` only check member coverage, allowing duplicate
or overlapping occurrences. The latest real singleton-domain output happens to
satisfy exact splitting, but the framework invariant is missing.

Finally, several remaining validators call `set(...)` before verifying model
items are scalar integers (RuleDraft citations, curriculum tool/citation
indexes, task public-goal indexes, Shared domains). Unhashable malformed input
can therefore escape as a Python `TypeError` instead of a typed DesignError.
Curriculum name/level dataclass validation can similarly leak `ValueError`.
These are deterministic validator defects at the same revised source boundary.

## Minimal coherent repair boundary

Close the remaining Design Direct source contracts together:

- disclose one exact shared RuleDraft grammar to ToolSemantics, WorldRules and
  TaskRequirement;
- disclose the exact current Curriculum source grammar;
- remove only the redundant SharedToolSemantics, ToolSemantics and
  TaskRequirement framework echoes and inject their frozen values in code;
- enforce exact Shared domain splitting and reorder/translate only the listed
  unsafe validation branches into typed node errors;
- align the corresponding task cards and add cross-node regressions.

Do not add nodes, graphs, model calls, prompt/schema frameworks, generic retry,
response modes, model/profile changes, free-form rules, Agent Skills, candidate
paths, IDs/hashes from models, legacy compatibility, or later-child features.
This Diagnosis authorizes no code edit or provider retry.
