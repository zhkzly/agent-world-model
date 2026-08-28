# S2 Goal-First Task Foundry — Implementation Plan

## 1. Execution boundary

This is the complete production implementation plan, not a demo/MVP plan. Each
checkpoint is a dependency boundary; none may be described as S2 completion.
Completion requires both real conformance releases, preregistered Task-yield and
structure floors, held-out transfer and every Good Task gate in the PRD.

Clean break:

- publish `EnvironmentRelease v2` only;
- no v1 compatibility/migration;
- no mandatory Graph/Programmatic Task lanes;
- no hidden setup, LLM final judge or domain framework branches.

The user explicitly waived `plan-document-write` Patrol for this planning update.
Code review, deterministic tests and causal semantic evidence remain required.

## 2. Code versus model responsibilities

### Framework code implemented directly

```text
v2 release parsing/preparation/two-runtime isolation
public/protected proxies, no-mutation checks and Host journal
TaskSemantics schemas/validation
canonical identities/serialization
StartCase iteration and deterministic Blueprint enumeration
selector/composition/condition rules
GoalProgram/checker compilation and execution
canonical instruction rendering/audits
Responses tool dispatch/trace/provenance
fresh witnesses and challenge verdicts
TaskDefinition/TaskPack identities
TaskAssessment and CorpusManifest
semantic deduplication/corpus selection
```

None may be replaced by “tell the model to be careful”.

### Codex SDK code-generation tasks

```text
Environment Builder
  writes actor uv project in its own workspace

TaskSemantics Author
  writes protected semantics uv project in a fresh independent workspace
```

Both receive immutable Host inputs, run bounded factual repair turns and are
accepted only by deterministic checks plus public/native physical evidence.

### Responses Agent tasks

```text
public witness search
independent TaskAssessment trials
```

The Host owns the ToolSpec-derived function loop. These are acting-policy tasks,
not Codex code-writing tasks.

## 3. Initial package ownership

```text
src/agent_env_foundry/
  existing modules
  preparation.py
  semantics.py
  qualification.py        # extend existing independent route
  release.py
  publication.py

src/agent_task_foundry/
  __init__.py
  models.py
  compiler.py
  runner.py
  admission.py
  corpus.py
  api.py
```

Runtime Skills/contracts:

```text
src/agent_env_foundry/runtime_skills/task-semantics-codegen/SKILL.md
src/agent_env_foundry/runtime_skills/task-semantics-codegen/TASK_SEMANTICS_CONTRACT.md
src/agent_task_foundry/runtime_skills/witness-agent/SKILL.md
```

Do not pre-create plugins, graph packages, workflow engines, services or a
Registry. Split only after a real ownership/test boundary appears.

## 4. Ordered implementation checkpoints

### Checkpoint 1 — Freeze contracts, identities and failing tests

#### Framework work

Implement immutable dataclasses/protocols and canonical serialization for:

```text
PreparedRelease / PreparedSession actor+trusted projections
StartCase
CapabilitySpec / CompositionRule / FacetSpec / ConditionSpec
AnswerFieldSpec / RenderingSpec
BindingCandidate / AtomCheckRequest / AtomCheckResult
SelectorSpec
AtomGoal / AllGoal / IfGoal / ForEachGoal
ReportSpec / TaskBlueprint
CheckerArtifact / TaskDefinition
WitnessRun / AdmissionReport / TaskPack
TaskAssessment / TaskFingerprint / CorpusManifest
all typed non-success outcomes
```

Key type rules:

- `IfGoal.then_goal` and `else_goal` may be `None`, but at least one is a goal and
  any goal-less branch requires a qualified condition report field;
- `AllGoal` contains a `composition_rule_id`;
- `FacetSpec.public_tool` contains an explicit ToolSpec output-schema pointer;
- TaskDefinition excludes witness/model/corpus evidence;
- TaskPack excludes TaskAssessment.

#### Tests

- current v1 release fails the v2 contract;
- no circular identity preimages;
- public projection cannot deserialize trusted fields;
- four Goal nodes only; selection/report are attributes;
- semantics no-mutation event model exists;
- ordering journal can prove checker/instruction freeze before model call.

#### Files

```text
src/agent_env_foundry/semantics.py
src/agent_task_foundry/models.py
tests/test_semantics_contract.py
tests/task_foundry/test_models.py
```

#### Validation

```bash
uv run pytest -q tests/test_semantics_contract.py tests/task_foundry/test_models.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- an object has no named producer/consumer;
- model trial/log formatting changes Task identity;
- public/protected separation is convention-only;
- cross-capability composition lacks an explicit rule ID.

---

### Checkpoint 2 — S1 v2 immutable preparation and separate runtimes

#### Framework work

Implement:

```python
prepare_release(release_path: Path, cache_root: Path) -> PreparedRelease
PreparedRelease.open(instance_directory: Path) -> PreparedSession
```

- clean outer/inner v2 descriptors binding actor and semantics projects;
- exact locked preparation from directory/ZIP;
- separate actor and semantics runtimes/child interpreters;
- actor runtime has actor package and instance read/write;
- semantics runtime has semantics package, no actor package import and trusted
  calls wrapped by before/after instance tree manifests;
- Host-owned public/trusted call journals and runtime identities;
- loading/attaching does not reset;
- actor/semantics byte/mode/digest tampering rejected;
- no v1 compatibility path.

Use the existing subprocess/Host-journal design. Internal stdin/stdout messaging
is private implementation detail, not a product service/protocol.

#### Files

```text
src/agent_env_foundry/preparation.py
src/agent_env_foundry/release.py
src/agent_env_foundry/publication.py
src/agent_env_foundry/_actor_runner.py
src/agent_env_foundry/_semantics_runner.py
tests/test_release_v2.py
tests/test_preparation.py
```

#### Real cases

- prepare two releases sharing the same generated package name;
- keep both actor and semantics sessions live without import/state aliasing;
- prove trusted calls leave instance tree unchanged;
- prove semantics runtime cannot import actor business package;
- relocate/reopen ZIPs;
- reload instance without implicit reset;
- tamper actor/semantics separately and reject.

#### Validation

```bash
uv run pytest -q tests/test_release_v2.py tests/test_preparation.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- S2 needs development checkout/private cold helper;
- actor imports alias across releases;
- trusted call can mutate state or import actor oracle;
- preparation rewrites published bytes/locks.

---

### Checkpoint 3 — Extend independent S1 Qualification to author TaskSemantics

This checkpoint contains Codex SDK authoring and deterministic Host work.

#### 3A. Host expected-semantics freeze

Extend current independent Qualification preparation to create/freeze:

```text
EXPECTED_TASK_SEMANTICS.json
  complete Requirement disposition
  actor/intents/preconditions/outcomes/refusals/collateral
  workflow IDs
  explicit CompositionRules
  public ConditionSpecs and branch licenses

PUBLIC_SURFACE.json
  public docs/start-reset schemas/ToolSpecs/public probe facts

TASK_SEMANTICS_CONTRACT.md
  exact protocol/schemas/output-path/import/no-mutation rules
```

Expected records are produced in a fresh typed model context, validated by Host
for complete Requirement/workflow coverage and frozen before candidate/native
source decoding is staged.

#### 3B. Codex SDK Semantics Author

Implement `run_semantics_author(...)` using the hardened `run_builder(...)`
pattern:

```text
fresh Codex home/thread/workspace
approval deny-all, full own-workspace sandbox
immutable Host inputs
read-only candidate view only after relation freeze
bounded repair turns from complete factual Host failures
```

Codex writes a standalone semantics uv project implementing:

```text
start_cases
inspect
capabilities
enumerate_bindings
evaluate_atom
evaluate_condition
```

It owns release-specific decoding and semantics records, but no actor bytes, Host
digests/manifests/verdicts or concrete Task instances.

#### 3C. Host semantic Qualification

For every Taskable capability prove:

```text
eligible StartCase exists
inspect agrees with independent native reader
bindings/public descriptors identify intended referents
public success flips atomic truth
no-op/wrong target/boundary remain false
required effects and collateral differ
answer/report values are grounded
public_tool facets/conditions have explicit output-schema paths and real output
CompositionRules/condition branches map to accepted Brief workflow relations
fresh reset preserves predicates
trusted calls do not mutate instance
semantics runtime cannot import actor package
physical inspector/evaluator mutants are killed while executable
```

Marker/declaration-only and syntax/import/crash mutants do not count.

#### Failure routing

```text
actor relation wrong         -> EnvironmentDefect -> rebuild actor -> regenerate semantics
semantics decoding wrong      -> SemanticsDefect -> same semantics thread repair
expected relation unsupported -> Research/Brief disposition
provider/dependency failure   -> identical retry or InfrastructureFailure
```

Any actor byte change invalidates the semantics project and all semantic evidence.

#### Files

```text
src/agent_env_foundry/qualification.py
src/agent_env_foundry/semantics.py
src/agent_env_foundry/runtime_skills/task-semantics-codegen/*
tests/test_semantics_authoring.py
tests/test_semantic_qualification.py
```

#### Validation

```bash
uv run pytest -q tests/test_semantics_authoring.py \
  tests/test_semantic_qualification.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- new Researcher/Critic/Arbiter product organization;
- semantics imports/calls actor business functions as oracle;
- broad ToolSpec schema authorizes hidden nested public fields;
- marker/crash mutants count;
- core Requirement disappears;
- framework contains domain templates.

---

### Checkpoint 4 — Publish and cold-verify EnvironmentRelease v2

#### Framework work

- assemble actor + semantics projects into one immutable v2 artifact;
- bind both digests, schemas/docs and semantic evidence;
- build/install both exact distributions in cold unrelated directories/runtimes;
- replay actor public calls and protected semantic checks from archived bytes;
- expose v2 verify/prepare through existing direct CLI;
- remove v1 publication success path on this branch.

#### Files

```text
src/agent_env_foundry/release.py
src/agent_env_foundry/publication.py
src/agent_env_foundry/api.py
src/agent_env_foundry/cli.py
tests/test_publication_v2.py
tests/test_cold_release_v2.py
```

#### Validation

```bash
uv run pytest -q tests/test_publication_v2.py tests/test_cold_release_v2.py
foundry verify-release --release <v2-directory-or-zip>
```

#### Stop conditions

- wheel alone treated as release;
- cold semantics evidence not reproducible;
- actor/trusted projections mixed.

---

### Checkpoint 5 — Deterministic S2 compiler, checker and instruction

#### Framework work only

1. exact v2 release admission;
2. StartCase/fact/binding materialization;
3. deterministic selector generation;
4. bounded four-node GoalProgram enumeration;
5. explicit CompositionRule and ConditionSpec enforcement;
6. optional report-only If branch only through condition report field;
7. TaskChecker compilation/canonical digest;
8. initial-goal-false, cardinality/tie and hidden-operand gates;
9. deterministic canonical instruction/answer schema rendering;
10. slot coverage, schema-path, leakage, tool/path/answer/cardinality audits.

No model call occurs.

#### Required order

```text
compile/freeze checker
-> render/audit/freeze instruction
-> persist TaskDefinition
-> emit model-call permission event
```

Test model factory fails if invoked earlier.

#### Files

```text
src/agent_task_foundry/models.py
src/agent_task_foundry/compiler.py
tests/task_foundry/test_instantiation.py
tests/task_foundry/test_compiler.py
tests/task_foundry/test_checker.py
tests/task_foundry/test_instruction.py
```

#### Validation

```bash
uv run pytest -q tests/task_foundry/test_instantiation.py \
  tests/task_foundry/test_compiler.py \
  tests/task_foundry/test_checker.py \
  tests/task_foundry/test_instruction.py
uv run mypy src
uv run ruff check src tests
```

#### Semantic negatives

- unqualified capability/condition/composition;
- shared workflow but no CompositionRule;
- composition rule set mismatch/incompatible scopes;
- unlicensed If branch or goal-less branch without report field;
- unique selector tie/empty/vacuous selector;
- duplicate/redundant child;
- initially satisfied goal;
- hidden target descriptor;
- missing/extra/strengthened instruction constraint;
- broad/missing public output-schema path;
- answer/tool/native/path leakage.

#### Stop conditions

- arbitrary Python needed for checker;
- LLM needed to enumerate/validate Blueprint;
- standalone Select/Report AST reappears without real need;
- compiler branches on domain labels/fields.

---

### Checkpoint 6 — Public Responses runner and two constructive witnesses

#### Framework work

Implement:

```python
run_public_episode(
    actor,
    instruction,
    reset_context,
    tool_specs,
    answer_schema,
    route,
    budget,
) -> EpisodeRun
```

- strict Responses function tools from ToolSpecs;
- exact prior output/function-result items across turns;
- Host dispatch/observation schema validation;
- canonical trace, usage, answer/runtime identities;
- no trusted/checker projection;
- load-bearing provenance validation;
- `public_tool` values only at qualified schema paths;
- AgentChoice only for non-target/non-answer/non-fixed free inputs and never a
  protected-only binding;
- protected guess and prose/error scraping rejection;
- two fresh successful witnesses per TaskDefinition;
- no WitnessRecipe/expression/removal-replay subsystem.

#### Responses Skill

`witness-agent/SKILL.md` gives method guidance only. Host enforces all properties.

#### Files

```text
src/agent_task_foundry/runner.py
src/agent_task_foundry/runtime_skills/witness-agent/SKILL.md
tests/task_foundry/test_runner.py
tests/task_foundry/test_provenance.py
tests/task_foundry/test_witness.py
```

#### Validation

- fresh runs may use different IDs/routes but same checker;
- actor cannot access trusted proxy through serialization/introspection;
- guessed protected ID rejected;
- `contract.*` provides no value/truth;
- free commit message allowed only as non-load-bearing AgentChoice;
- missing output-schema path rejects load-bearing public-tool operand;
- answer schema enforced;
- `NoPublicWitness` distinct from impossibility.

```bash
uv run pytest -q tests/task_foundry/test_runner.py \
  tests/task_foundry/test_provenance.py \
  tests/task_foundry/test_witness.py
```

#### Stop conditions

- Codex SDK used as witness loop;
- model text without real tools counts;
- checker/native failure details leak;
- tool count becomes difficulty.

---

### Checkpoint 7 — Admission, TaskPack, TaskAssessment and corpus

#### 7A. Intrinsic admission

Implement:

```text
witnesses #1/#2
no-op
wrong/near-miss target
partial All/ForEach
collateral action
wrong atom/condition report
valid alternative signature
process violation
checker mutations: child/set/selector/condition/collateral/answer/process
not_applicable(reason) without score inflation
```

Seal:

```text
TaskDefinition + two WitnessRuns/provenance + AdmissionReport -> TaskPack
```

No model trial/difficulty/corpus policy enters TaskPack identity.

#### 7B. TaskAssessment

Reuse `run_public_episode` with independent route/policy. Record reliability,
failure attribution, calls, tokens and latency. Pure model failure excludes a
TaskPack from a target corpus; only causal intrinsic defect evidence invalidates
TaskPack.

#### 7C. Corpus selection

- model-independent fingerprint including composition rule IDs;
- exact TaskDefinition/checker dedup;
- text-near-duplicate filter inside structural groups;
- capability/Goal/start budgets;
- separate assessment reliability/cost;
- immutable CorpusManifest and surplus/rejection audit.

#### API/CLI

```python
synthesize_tasks(
    release_path: Path,
    *,
    policy: CorpusPolicy,
    budget: SynthesisBudget,
    routes: ModelRoutes,
) -> SynthesisResult
```

```bash
foundry synthesize-tasks \
  --release <environment-package-v2.zip> \
  --policy <corpus-policy.json> \
  --output <task-store>
```

No service layer.

#### Files

```text
src/agent_task_foundry/admission.py
src/agent_task_foundry/corpus.py
src/agent_task_foundry/api.py
src/agent_env_foundry/cli.py
tests/task_foundry/test_admission.py
tests/task_foundry/test_identity.py
tests/task_foundry/test_corpus.py
```

#### Validation

```bash
uv run pytest -q tests/task_foundry/test_admission.py \
  tests/task_foundry/test_identity.py \
  tests/task_foundry/test_corpus.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- assessment changes TaskPack ID;
- empirical difficulty in structural fingerprint;
- unreachable/crashing challenges improve kill rate;
- weak-model failure relabeled Task defect without cause;
- paraphrase/parameter duplication inflates corpus.

---

### Checkpoint 8 — Real cross-domain, held-out and paper gates

#### 8A. Regenerate conformance releases

1. SQLite-backed ocean-container dispute world;
2. filesystem/Git repository-maintenance world.

For each:

```text
Need/Research
-> actor Codex project
-> independent TaskSemantics Codex project
-> physical semantic Qualification
-> cold v2 release
-> deterministic Tasks/checkers/instructions
-> two public witnesses
-> challenge admission
-> TaskAssessment/CorpusManifest
-> S3-shaped cold recreation
```

Anti-demo floors per release:

```text
>= 20 admitted TaskPacks after semantic deduplication
>= 4 canonical Goal/selector structure signatures
>= 2 qualified StartCase regimes
every core Taskable capability represented or newly Unsupported with evidence
```

Parameter-only changes/paraphrases do not count.

#### 8B. Freeze and held-out transfer

Freeze framework/contracts/Skills before selecting a new Need. Without framework
domain edits require:

```text
>= 10 admitted TaskPacks
>= 3 canonical structure signatures
>= 2 taskable capabilities or explicit method-falsifying result
complete solvability/checker/leakage/cold evidence
```

#### 8C. Baselines and ablations

Baselines:

1. LLM writes Task from docs/tools;
2. successful trace abstraction;
3. old Graph/Programmatic proposal;
4. qualified-capability compiler;
5. bounded human-authored quality reference.

Ablations:

```text
remove Brief/workflow/composition anchors
checker after witness
remove physical semantic negatives
remove public provenance/schema-path gate
text-only diversity
merge TaskAssessment into TaskPack
```

Metrics:

```text
capability disposition and yield
fresh witness success
hidden operand rejection
checker mutation kill/false acceptance
alternative false rejection
instruction defects
structural redundancy/diversity
actor reliability/calls/tokens/runtime
held-out Task/tool/state-regime generalization
matched-budget downstream SFT/RL or Agent evaluation
```

Fatal PRD outcomes are reported rather than hidden by larger models or relaxed
gates.

## 5. Full validation gate

```bash
uv sync --frozen --all-groups
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest -q

foundry generate --need-file <sqlite-need> --run-store <run> --release-store <store>
foundry generate --need-file <git-need> --run-store <run> --release-store <store>
foundry verify-release --release <release-v2>
foundry synthesize-tasks --release <release-v2> --policy <policy> --output <store>
```

Held-out repeats the same commands after freeze.

## 6. Causal review and rollback

Assign first incorrect owner before editing:

```text
Research/Brief
Environment Builder
TaskSemantics Author
Semantic Qualification
release/preparation
Blueprint/compiler
checker
instruction
public runner/provenance
admission
TaskAssessment/corpus
Infrastructure
```

Rollback means reverting current checkpoint; no dual v1/v2 path.

Completion boundaries:

- before Checkpoint 4: no v2 release;
- before Checkpoint 6: no public solvability evidence;
- before Checkpoint 7: no TaskPack;
- before Checkpoint 8A floors: no cross-domain S2 completion;
- before Checkpoint 8B/C: no held-out/generalization/training claim.

## 7. Planning readiness checklist

- [x] Good Task contract explicit;
- [x] framework/Codex/Responses responsibilities function-level;
- [x] S1 v2 and TaskSemantics typed;
- [x] explicit composition/condition and output-schema contracts;
- [x] checker -> instruction -> witness order unambiguous;
- [x] TaskPack and assessment identities separated;
- [x] overdesigned Graph/Program/WitnessRecipe/LLM-Judge paths deleted;
- [x] real cross-domain/anti-demo/held-out gates preregistered;
- [x] implementation/check manifests curated;
- [x] user waived plan-document Patrol for this planning update;
- [ ] user approves latest coherent plan and activates implementation.
