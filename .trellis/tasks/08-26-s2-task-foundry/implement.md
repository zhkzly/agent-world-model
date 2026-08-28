# S2 Goal-First Task Foundry — Implementation Plan

## 1. Execution boundary

This is the complete production implementation plan, not a demo/MVP plan. Each
section is a dependency checkpoint; no checkpoint may be described as S2
completion. Completion requires both contrasting real releases, preregistered
Task-yield/structure floors, held-out transfer and the Good Task gates in the PRD.

The work is a clean break:

- publish `EnvironmentRelease v2` only;
- do not implement v1 compatibility/migration;
- do not preserve mandatory Graph/Programmatic Task lanes;
- do not add hidden setup, LLM final judging or domain framework branches.

The user explicitly waived `plan-document-write` Patrol for this planning update.
Normal code review, tests and causal failure attribution remain required.

## 2. Code versus model responsibilities

### Framework code that must be implemented directly

```text
release parsing/preparation/process isolation
public/protected proxies and Host journal
TaskSemantics schemas/validation
identity/canonical serialization
StartCase iteration and Blueprint enumeration
GoalProgram/checker compilation and execution
canonical instruction rendering/audits
Responses tool dispatch/trace capture/provenance
fresh witness and challenge verdicts
TaskDefinition/TaskPack/TaskAssessment/CorpusManifest
semantic deduplication and deterministic selection
```

None of these may be replaced by “tell the model to be careful”.

### Codex SDK code-generation tasks

```text
Environment Builder
  writes actor uv project in its own workspace

Semantics Author
  writes protected TaskSemantics uv project in a fresh independent workspace
```

Both receive immutable Host files, run bounded repair turns and are accepted only
by deterministic checks plus real native/public evidence.

### Responses Agent tasks

```text
public witness search
independent TaskAssessment trials
```

The Host owns the episode loop and ToolSpec-derived function dispatch. These are
acting-policy tasks, not Codex code-writing tasks.

## 3. Initial package ownership

Start with the smallest modules that have distinct consumers:

```text
src/agent_env_foundry/
  existing modules
  preparation.py
  semantics.py
  qualification.py        # extend, do not create a second Agent organization
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

New runtime Skills/contracts:

```text
src/agent_env_foundry/runtime_skills/task-semantics-codegen/SKILL.md
src/agent_env_foundry/runtime_skills/task-semantics-codegen/TASK_SEMANTICS_CONTRACT.md
src/agent_task_foundry/runtime_skills/witness-agent/SKILL.md
```

Do not pre-create plugins, graph packages, workflow engines, services or a
Registry. Split files only after an observed ownership/test boundary.

## 4. Ordered implementation checkpoints

### Checkpoint 1 — Freeze types, identities and failing contract tests

#### Framework work

Implement immutable dataclasses/protocols and canonical serialization for:

```text
PreparedRelease / PreparedSession public+trusted projections
StartCase
CapabilitySpec / FacetSpec / ConditionSpec / AnswerFieldSpec / RenderingSpec
BindingCandidate / AtomCheckRequest / AtomCheckResult
SelectorSpec
AtomGoal / AllGoal / IfGoal / ForEachGoal
ReportSpec / TaskBlueprint
CheckerArtifact / TaskDefinition
WitnessRun / AdmissionReport / TaskPack
TaskAssessment / TaskFingerprint / CorpusManifest
all typed non-success outcomes
```

Create tests that fail against current v1 releases and prove:

- no circular identity preimages;
- TaskDefinition excludes witness/model/corpus evidence;
- TaskPack excludes TaskAssessment;
- public projections cannot deserialize protected fields;
- four Goal nodes only; selection/report are attributes;
- initial ordering event model can prove checker and instruction freeze before a
  model call.

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

- a model/object has no named producer and consumer;
- one identity changes because a model trial or log formatting changes;
- public/protected projections rely only on developer convention.

---

### Checkpoint 2 — S1 v2 immutable release preparation and isolated opening

#### Framework work

Implement:

```python
prepare_release(release_path: Path, cache_root: Path) -> PreparedRelease
PreparedRelease.open(instance_directory: Path) -> PreparedSession
```

- define clean outer/inner v2 descriptors binding actor and semantics projects;
- prepare exact locked dependencies from directory/ZIP;
- launch one isolated child interpreter per opened exact release/session;
- expose typed actor/trusted proxies over the existing subprocess/journal style;
- keep load/attach separate from explicit reset;
- bind runtime identity and reject byte/mode/digest tampering;
- delete same-process import-cache assumptions; add no v1 loader.

#### Files

```text
src/agent_env_foundry/preparation.py
src/agent_env_foundry/release.py
src/agent_env_foundry/publication.py
src/agent_env_foundry/_release_runner.py
tests/test_release_v2.py
tests/test_preparation.py
```

#### Required real cases

- prepare two generated releases that use the same Python package name;
- keep sessions live simultaneously and prove no import/state aliasing;
- relocate ZIPs and reopen them;
- reload an instance without implicit reset;
- tamper actor and semantics bytes separately and reject both.

#### Validation

```bash
uv run pytest -q tests/test_release_v2.py tests/test_preparation.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- S2 needs a development checkout/private cold helper;
- child process can import another release accidentally;
- preparation rewrites published bytes or dependency locks.

---

### Checkpoint 3 — Extend independent S1 Qualification to author TaskSemantics

This checkpoint contains both Codex SDK work and deterministic Host work.

#### 3A. Host expected-semantics freeze

Extend the current independent Qualification preparation to produce and freeze:

```text
EXPECTED_TASK_SEMANTICS.json
  Requirement/workflow coverage
  actor role and user intent
  expected precondition/outcome/refusal/collateral relations
  candidate Taskable/NotTaskable/Unsupported disposition

PUBLIC_SURFACE.json
  public docs, start/reset schemas, ToolSpecs and selected public probe facts

TASK_SEMANTICS_CONTRACT.md
  exact protected protocol, schemas and forbidden imports/authority
```

Expected relations are frozen before source/native decoding is exposed. Host
validates every core Requirement disposition.

#### 3B. Codex SDK Semantics Author

Implement `run_semantics_author(...)` using the same hardened pattern as
`run_builder(...)`:

```text
fresh Codex home/thread/workspace
approval denied, full workspace sandbox
immutable Host inputs
read-only candidate view staged only after relation freeze
bounded repair turns from factual Host failures
```

Codex writes a complete standalone semantics uv project implementing:

```text
start_cases
inspect
capabilities
enumerate_bindings
evaluate_atom
evaluate_condition
```

It owns no Host digest, manifest, verdict or actor code.

#### 3C. Host semantic qualification

Extend `qualification.py` rather than introducing another Agent pipeline.
For every Taskable capability, execute and prove:

```text
eligible StartCase exists
inspect agrees with independent native read
bindings/public descriptors identify intended referents
public success flips atomic truth
no-op/wrong-target/boundary remain false
required effects and forbidden collateral differ
answer fields are grounded
public facets/conditions are observable
fresh reset preserves predicates
physical inspector/evaluator mutants are killed while executable
```

#### Failure routing

```text
actor relation wrong        -> EnvironmentDefect -> Builder repair -> regenerate semantics
semantics decoding wrong     -> SemanticsDefect -> same semantics thread repair
expected relation unsupported-> Research/Brief disposition
provider/dependency failure  -> identical retry or InfrastructureFailure
```

Any actor byte change invalidates the semantics project and reruns all semantic
checks.

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

- a new Researcher/Critic/Arbiter organization appears;
- semantics imports/calls actor business functions as oracle;
- marker/syntax/crash mutants count as semantic evidence;
- a core Requirement disappears silently;
- framework contains domain capability templates.

---

### Checkpoint 4 — Publish and cold-verify EnvironmentRelease v2

#### Framework work

- assemble actor + semantics projects into one immutable v2 artifact;
- bind both digests, public docs/schemas and semantic Qualification evidence;
- build/install both exact distributions in cold unrelated directories;
- run public actor calls and protected semantics checks from exact archived bytes;
- expose v2 verify/prepare commands through the existing direct CLI;
- remove old v1 publication success path on this branch.

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

- the wheel alone is treated as the release;
- cold verification cannot reproduce semantics evidence;
- actor/trusted projections are mixed in the public CLI/runtime.

---

### Checkpoint 5 — Deterministic S2 compiler, checker and canonical instruction

#### Framework work

Implement in `agent_task_foundry`:

1. exact v2 release admission;
2. StartCase/fact/binding materialization;
3. deterministic selector generation;
4. bounded four-node GoalProgram enumeration;
5. cross-capability composition only through shared qualified workflow IDs and
   compatible scopes;
6. TaskChecker compilation and canonical digest;
7. initial-goal-false, cardinality/tie and hidden-operand gates;
8. deterministic canonical instruction/answer schema rendering;
9. slot coverage, leakage, tool/path/answer and cardinality audits.

No model call occurs in this checkpoint.

#### Required compiler order test

```text
compile checker
-> freeze checker digest
-> render/audit instruction
-> freeze TaskDefinition
-> emit model-call permission event
```

A test model factory must fail if invoked before this event.

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

#### Semantic-negative cases

- unqualified capability/condition;
- `AllGoal` without shared workflow;
- incompatible write scopes;
- unique selector tie;
- empty/vacuous selector;
- duplicate/redundant child;
- already-satisfied goal;
- hidden target descriptor;
- missing/extra/strengthened instruction constraint;
- answer/tool/native/path leakage.

#### Stop conditions

- arbitrary Python is needed for a supported checker;
- an LLM is needed to enumerate/validate a Blueprint;
- standalone Select/Report nodes reappear without a demonstrated need;
- the compiler branches on domain labels/fields.

---

### Checkpoint 6 — Public Responses episode runner and constructive witnesses

#### Framework work

Implement one neutral Host-owned public episode runner:

```python
run_public_episode(
    session_actor,
    instruction,
    reset_context,
    tool_specs,
    answer_schema,
    route,
    budget,
) -> EpisodeRun
```

- build strict Responses function tools from ToolSpecs;
- preserve exact model output items/function results across turns;
- Host dispatches and validates every call/observation;
- record canonical trace, usage, final answer and runtime identities;
- expose no trusted/checker fields to the policy;
- validate load-bearing argument provenance;
- classify agent-generated free inputs separately from protected/public operands;
- reject protected-only guesses and prose/error scraping;
- run two fresh successful witnesses for every TaskDefinition;
- do not implement WitnessRecipe, expression DSL or removal replay.

#### Responses Skill

`witness-agent/SKILL.md` gives method guidance only: understand the instruction,
inspect public tools/results, recover dynamic IDs publicly, handle business
refusals and return the declared answer schema. Host checks every property.

#### Files

```text
src/agent_task_foundry/runner.py
src/agent_task_foundry/runtime_skills/witness-agent/SKILL.md
tests/task_foundry/test_runner.py
tests/task_foundry/test_provenance.py
tests/task_foundry/test_witness.py
```

#### Validation

- two fresh runs may use different IDs/routes but pass the same checker;
- policy cannot access protected proxies even by serialization/introspection;
- a guessed native ID is rejected;
- `contract.*` errors provide no value/truth;
- a free commit message is allowed only as non-load-bearing AgentChoice;
- final answer schema is enforced;
- `NoPublicWitness` is distinct from logical impossibility.

```bash
uv run pytest -q tests/task_foundry/test_runner.py \
  tests/task_foundry/test_provenance.py \
  tests/task_foundry/test_witness.py
```

#### Stop conditions

- Codex SDK is used as the acting witness loop;
- successful model text without real tool execution counts;
- checker/native failure details leak back to the policy;
- tool count becomes a difficulty label.

---

### Checkpoint 7 — Admission, TaskPack, TaskAssessment and corpus

#### 7A. Intrinsic admission

Implement:

- positive witness #1/#2;
- no-op;
- wrong/near-miss target where reachable;
- partial All/ForEach;
- collateral action where reachable;
- wrong/stale/malformed answer;
- valid alternative action signature;
- process violation where declared;
- checker mutation generation and kill report;
- typed `not_applicable(reason)` without score inflation.

Seal:

```text
TaskDefinition
+ two WitnessRuns/provenance
+ AdmissionReport
-> TaskPack
```

No independent actor trial/difficulty/corpus policy enters TaskPack identity.

#### 7B. Model-relative TaskAssessment

Reuse `run_public_episode` with an independent route/policy identity. Record
pass/failure attribution, calls, tokens, latency and reliability. Pure model
failure excludes the TaskPack from a target corpus; only causal evidence of an
intrinsic defect invalidates the TaskPack.

#### 7C. Corpus selection

- compute model-independent structural fingerprint;
- deduplicate exact TaskDefinition/checker semantics;
- text-near-duplicate filter inside structural groups;
- apply capability/Goal/start budgets;
- combine separate assessment reliability/cost;
- produce immutable `CorpusManifest` and audit surplus/rejections.

#### Direct API/CLI

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

No service layer is introduced.

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

- TaskPack ID changes because another model is assessed;
- empirical difficulty appears in structural fingerprint;
- unreachable/crashing challenges improve mutation kill rate;
- a valid Task is relabeled defective only because a weak model fails;
- corpus size is inflated by paraphrases/parameter-only duplicates.

---

### Checkpoint 8 — Real cross-domain verticals, held-out transfer and paper gates

#### 8A. Regenerate the two conformance releases

1. SQLite-backed ocean-container dispute world;
2. filesystem/Git repository-maintenance world.

For each exact release:

```text
Need/Research
-> actor Codex project
-> independent TaskSemantics Codex project
-> semantic physical Qualification
-> cold EnvironmentRelease v2
-> deterministic Blueprints/checkers/instructions
-> two public witnesses
-> challenge admission
-> TaskAssessment and CorpusManifest
-> S3-shaped cold recreation
```

#### Anti-demo floors per conformance release

```text
>= 20 admitted TaskPacks after semantic deduplication
>= 4 canonical Goal/selector structure signatures
>= 2 qualified StartCase regimes
every core Taskable capability represented or newly dispositioned Unsupported
```

Parameter-only changes and paraphrases do not satisfy structure floors.

#### 8B. Freeze and held-out transfer

Freeze framework code, contracts and Skills before selecting a new Need. Without
framework domain edits, require:

```text
>= 10 admitted TaskPacks
>= 3 canonical structure signatures
>= 2 taskable capabilities or an explicit method-falsifying result
complete public-solvability/checker/leakage/cold evidence
```

#### 8C. Matched baselines and ablations

Baselines:

1. LLM writes Tasks from docs/tools;
2. successful public traces are abstracted into Tasks;
3. old Graph/Programmatic proposal;
4. new qualified-capability compiler;
5. bounded human-authored Task/checker quality reference.

Ablations:

```text
remove Brief/workflow anchors
checker built after witness
remove physical semantic negatives
remove public-provenance gate
text-only diversity
merge TaskAssessment into TaskPack policy
```

Metrics:

```text
capability disposition and admitted yield
fresh public witness success
hidden-operand rejection
checker mutation kill/false acceptance
valid-alternative false rejection
instruction defects
structural redundancy/diversity
actor reliability/calls/tokens/runtime
held-out Task/tool/state-regime generalization
matched-budget downstream SFT/RL or Agent evaluation
```

Fatal PRD criteria are reported, not hidden by larger models, relaxed gates or
extra generation attempts.

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

The held-out run repeats the same public commands after freeze.

## 6. Causal review and rollback

For every failure, assign the first incorrect owner before editing:

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
TaskAssessment/corpus policy
Infrastructure
```

Rollback means reverting the current checkpoint changes; no dual v1/v2 path is
kept.

Completion boundaries:

- before Checkpoint 4: no v2 release;
- before Checkpoint 6: no constructive public solvability evidence;
- before Checkpoint 7: no admitted TaskPack;
- before Checkpoint 8A floors: no cross-domain S2 completion;
- before Checkpoint 8B/C: no held-out/generalization/training claim.

## 7. Planning readiness checklist

- [x] product goal and Good Task contract are explicit;
- [x] framework, Codex SDK and Responses responsibilities are function-level;
- [x] S1 v2 and TaskSemantics contracts are typed;
- [x] Goal/checker/instruction/witness order is unambiguous;
- [x] TaskPack and model-relative assessment identities are separated;
- [x] overdesigned Graph/Program/WitnessRecipe/LLM-Judge paths are deleted;
- [x] real cross-domain, anti-demo and held-out gates are preregistered;
- [x] implementation/check manifests contain real context;
- [x] user waived plan-document Patrol for this planning update;
- [ ] user approves this latest coherent plan and activates implementation.
