# S2 Goal-First Task Foundry — Implementation Plan

## 1. Execution authority

This is a planning artifact. The task remains in Trellis `planning` state.
Product code, task activation and implementation workers require a later user
message explicitly approving the final PRD/design/implementation summary.

The work is a clean break:

- replace the current environment release format with v2;
- do not implement v1 compatibility or migration;
- do not preserve the old mandatory Graph/Programmatic S2 design;
- do not publish partial slices as a completed product, demo or MVP.

Each slice below is an independently checkable engineering checkpoint. S2 is
complete only after the real cross-domain, held-out and Task-quality acceptance
criteria pass together.

## 2. Implementation rules

1. Use one direct imperative coordinator for S1 and one for S2.
2. Add no domain names, table/file field rules or Task templates to framework
   code.
3. Use generated release-local semantics code for domain meaning and Host code
   for schemas, execution, identities, evidence and verdicts.
4. Freeze TaskChecker identity before invoking the public witness planner.
5. Keep every public witness operand provenance-machine-checkable.
6. Fail closed. No LLM Judge, native-state patch, canned Task or compatibility
   fallback may convert a defect into admission.
7. Run real-model and real-release checks in addition to fake-provider/unit
   tests.
8. After every defect, attribute it to Environment, Semantics, Blueprint,
   Checker, Planner, Instruction, Admission, Infrastructure or corpus policy
   before changing code.

## 3. Expected package ownership

```text
src/agent_env_foundry/
  preparation.py               # exact release preparation/process isolation
  semantics_contract.py        # S1 v2 protected protocol and schemas
  semantic_authoring.py        # independent semantics coding route
  semantic_qualification.py    # Host-owned evidence and verdict
  release.py/publication.py     # clean v2 identity and archive

src/agent_task_foundry/
  models.py                     # Blueprint/TaskPack/value objects
  release.py                    # S2 release admission and projections
  blueprint.py                  # bounded GoalProgram compiler
  checker.py                    # checker-before-witness compiler/runtime
  planner.py                    # public-only planner and WitnessRecipe
  instruction.py                # canonical renderer and audits
  admission.py                  # replay/challenge/trial gates
  corpus.py                     # fingerprint/dedup/selection
  api.py                        # direct S2 coordinator
```

This shape may be compressed when implementation proves two modules have no
independent consumer. It may not be expanded into a workflow engine, Registry,
plugin system or custom RPC architecture.

## 4. Ordered implementation slices

### Slice 1 — Freeze executable contracts and failing tests

#### Deliverables

- Python dataclasses/protocols for:
  - `PreparedRelease` and isolated session projections;
  - `SemanticsBundle`, `StartCase`, `CapabilitySpec`, `FacetSpec`,
    `BindingCandidate`, `AtomEvaluation`;
  - `GoalProgram`, `TaskBlueprint`, `StartRecipe`, `TaskChecker`,
    `WitnessRecipe`, `TaskPack` and typed outcomes.
- JSON/canonical serialization rules for identity-bearing objects.
- Tests that fail against the current S1 release because v2 protected semantics
  and preparation/opening are absent.
- Tests proving acting projections cannot reach trusted methods or protected
  values.

#### Validation

```bash
uv run pytest -q tests/test_semantics_contract.py tests/test_task_models.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- a type/object has no named producer and consumer;
- identity preimages are circular;
- public and protected projections cannot be separated mechanically.

No release or Task success is claimed in this slice.

---

### Slice 2 — S1 v2 preparation and isolated opening

#### Deliverables

- clean `environment-package/2` and inner release descriptors;
- exact locked preparation from directory or ZIP;
- one interpreter/process isolation boundary per exact prepared release;
- Python `prepare_release(...).open(instance_directory)` API;
- Host-owned call journal and runtime identity;
- removal of current same-process import-cache assumptions;
- no v1 compatibility path.

#### Validation

- prepare two releases with the same generated Python package name;
- keep both sessions live and prove calls/state remain isolated;
- move release archives to unrelated directories and reopen them;
- tamper with actor or semantics bytes and prove digest rejection;
- reload an instance without implicit reset.

```bash
uv run pytest -q tests/test_preparation.py tests/test_release_v2.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- S2/S3 would need a development checkout or private cold-qualification helper;
- different release imports can alias in one Host;
- preparation silently changes published bytes or dependency locks.

---

### Slice 3 — Independent S1 semantic authoring

#### Deliverables

- a separate semantic-authoring Codex route/thread that receives:
  - accepted Development Brief and Requirement IDs;
  - public environment docs, ToolSpecs and reset observations;
  - decode-only source/native access only after expected semantic relations are
    frozen;
- a generated release-local semantics uv package implementing the protected
  protocol;
- Host-generated semantics manifest, schemas and source digests;
- explicit per-Requirement `Taskable`, `NotTaskable` or `Unsupported` result;
- deterministic `start_cases` and public-descriptor facet declarations.

#### Validation

- the semantics author receives no Builder chat/tests and no S2 Task candidate;
- deleting a required Brief relation prevents semantics closure;
- unknown/unsupported semantics return typed failure instead of a generic
  capability;
- generated semantics contains no Host-authored domain stub or template.

#### Stop conditions

- the semantics package copies candidate business predicates as authority;
- the Author can emit Host digests/manifests/verdicts;
- a core Requirement disappears without a typed disposition.

---

### Slice 4 — S1 semantic qualification and cold publication

#### Deliverables

- Host-controlled semantic qualification runner;
- independent native readers and frozen expected relations;
- public success/refusal probes;
- physical native near misses for inspector/evaluator sensitivity;
- start-case validity, replay and public-facet recoverability checks;
- atomic no-op, wrong-target, boundary and collateral challenges;
- v2 qualification summary and immutable publication binding both actor and
  semantics packages;
- cold relocation and semantic replay from exact archived bytes.

#### Validation

For every declared taskable capability:

```text
eligible start exists
public success passes
no-op fails
wrong target fails
boundary near miss fails
collateral damage fails
public facets are recoverable
fresh reset preserves business predicates
```

A physical mutation counts only when the controlled release still executes and
the matching intended assertion flips. Syntax/import/crash and marker-only
changes are rejected as evidence.

```bash
uv run pytest -q tests/test_semantic_qualification.py tests/test_publication_v2.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- the semantics bundle self-qualifies through candidate functions;
- false capability evidence can pass without a physical behavior difference;
- cold preparation cannot reproduce qualification.

---

### Slice 5 — S2 release admission and native-backed instantiation

#### Deliverables

- exact v2 release admission;
- deterministic StartCase iteration and sampling;
- protected inspection and binding enumeration;
- public/protected binding separation checks;
- TaskInstance materialization with goal-initially-false gate;
- typed rejection for ambiguity, missing candidates, hidden operands and
  unsupported start regimes.

#### Validation

- the same seed/release yields canonical StartCase identities;
- fresh starts align by semantic key/business predicate, not incidental IDs;
- a protected-only value cannot enter a public instruction frame or planner
  input;
- mutation Tasks initially true are rejected;
- query Tasks whose answer is already leaked are rejected.

```bash
uv run pytest -q tests/task_foundry/test_release.py \
  tests/task_foundry/test_instantiation.py
```

---

### Slice 6 — GoalProgram and TaskBlueprint compiler

#### Deliverables

- typed implementations of `Atom`, `Select`, `If`, `All`, `ForEach` and
  `Report`;
- deterministic compatibility, selector, tie, scope and removal rules;
- bounded candidate enumeration from CapabilitySpecs and corpus policy;
- optional typed LLM proposal/ranking adapter whose output is fully validated;
- TaskBlueprint serialization and fingerprints.

#### Validation

- every supported node has positive and semantic-negative tests;
- unrelated `All` compositions, vacuous branches, unresolved selector ties and
  redundant atoms are rejected;
- no domain field names appear in framework compiler code/tests except inside
  generated release fixtures or real release evidence;
- parameter substitutions do not create new structural fingerprints.

```bash
uv run pytest -q tests/task_foundry/test_blueprint.py
uv run mypy src
uv run ruff check src tests
```

#### Stop conditions

- arbitrary Python is required to express a supported Blueprint;
- a node cannot be checker-compiled deterministically;
- the compiler needs release-specific conditionals.

---

### Slice 7 — Checker-before-witness compiler

#### Deliverables

- deterministic `TaskChecker` compilation from GoalProgram and qualified atomic
  evaluators;
- canonical checker artifact/dependency digest;
- hard ordering evidence that checker freeze precedes planner invocation;
- composition rules for selectors, conjunctions, sets, answers and declared
  process constraints;
- `satisfied/failed/abstain` result with typed evidence.

#### Validation

- deliberately alter the later witness and prove checker bytes remain identical;
- remove one checker predicate and prove a targeted mutation test detects it;
- valid alternative facts pass without matching the reference path;
- malformed or insufficient trusted facts produce `abstain`, never success;
- the checker imports no environment business functions.

```bash
uv run pytest -q tests/task_foundry/test_checker.py
```

#### Stop conditions

- reference trace or answer is required to author the checker;
- an LLM verdict is required for deterministic capability outcomes;
- exact-path comparison is used for an outcome Task.

---

### Slice 8 — Public planner, provenance and replay

#### Deliverables

- one bounded public tool-calling planner with Host trace capture;
- public-only planner projection;
- `WitnessRecipe` compiler with `TaskSlotRef`, `ResetObservationRef`,
  `PublicConstant`, `ToolResultRef` and `DeterministicSelect`;
- argument provenance validator;
- fresh recipe replay and removal replay;
- typed `NoPublicWitness` distinct from logical impossibility.

#### Validation

- dynamic IDs differ on replay but semantic outcome remains valid;
- one hidden literal or prose-mined ID rejects the recipe;
- `contract.*` errors cannot provide values or capability evidence;
- deleting a genuinely redundant call preserves success and prunes it;
- business refusal is retained only when Blueprint process/conditional semantics
  require it.

```bash
uv run pytest -q tests/task_foundry/test_planner.py \
  tests/task_foundry/test_witness.py
```

#### Stop conditions

- planner receives checker/native/protected binding data;
- successful model text is accepted without real public execution;
- tool count or chain length is assigned as Task difficulty.

---

### Slice 9 — Instruction rendering and integrity audit

#### Deliverables

- deterministic canonical renderer from `PublicInstructionFrame`;
- structured instruction-frame parser for round-trip checks;
- audits for protected/native/tool/path/answer leakage;
- optional LLM paraphrase adapter behind exact frame equivalence;
- actor-visible reset-context projection and answer-schema rendering.

#### Validation

- deleting or strengthening one constraint causes round-trip rejection;
- a hidden ID, tool name or reference-order phrase is rejected;
- ambiguous public descriptors are rejected or rendered as set-valued intent;
- canonical instructions work without an LLM paraphraser.

```bash
uv run pytest -q tests/task_foundry/test_instruction.py
```

---

### Slice 10 — Admission challenges and shared actor trials

#### Deliverables

- challenge generator from GoalProgram and capability evidence;
- positive/fresh/no-op/wrong-target/near-miss/partial/collateral/wrong-answer/
  alternative-path/process-violation matrix;
- mutation kill report and false-acceptance report;
- reusable public actor-loop runner shared with later S3;
- independent model/policy identity capture;
- typed Task-quality report and final `Admitted`/rejection decision.

#### Validation

- applicable challenge categories must execute and receive expected checker
  results;
- unreachable or crashing mutants do not inflate sensitivity scores;
- independent all-policy failure blocks current corpus admission and triggers
  causal diagnosis;
- actor runner sees no protected projection;
- trials never alter checker truth or create S3 reward records.

```bash
uv run pytest -q tests/task_foundry/test_admission.py \
  tests/task_foundry/test_actor_runner.py
```

---

### Slice 11 — TaskPack identity and corpus selection

#### Deliverables

- canonical public/protected TaskPack projections;
- non-circular TaskPack identity;
- deterministic Task fingerprint;
- Blueprint/checker deduplication followed by text-near-duplicate detection;
- explicit corpus policies for capability/AST/state/difficulty budgets;
- audit records for admitted, rejected and surplus valid Tasks;
- direct API and CLI, tentatively:

```python
synthesize_tasks(release, policy, budget) -> SynthesisOutcome
```

```bash
foundry synthesize-tasks \
  --release <environment-package-v2.zip> \
  --policy <corpus-policy.json> \
  --output <taskpack-store>
```

The final CLI spelling may follow existing `foundry` conventions; it must invoke
the same direct API and not introduce a service layer.

#### Validation

- changing any load-bearing component changes TaskPack ID;
- changing audit-only formatting does not;
- actor projection cannot deserialize checker/witness/protected bindings;
- repeated parameter instances occupy the same structural group;
- policy selection is deterministic for the same identities and seed.

---

### Slice 12 — Real cross-domain verticals

#### Deliverables

Regenerate both current conformance Needs through the exact v2 path:

1. SQLite-backed ocean-container dispute world;
2. filesystem/Git repository-maintenance world.

For each release:

```text
Need
-> Environment + Semantics authoring
-> independent semantic Qualification
-> cold EnvironmentRelease v2
-> capability coverage report
-> atomic and applicable composed TaskPacks
-> frozen checker/public witness/fresh replay
-> challenge matrix
-> independent actor trials
-> S3-shaped recreation
```

#### Required evidence

- exact framework commit and prompt/Skill digests;
- no domain branch or post-run framework patch;
- every core Requirement disposition;
- all admitted Task identities and checker/challenge evidence;
- actual public calls and native facts;
- interaction cost and empirical difficulty.

#### Stop conditions

- framework code changes after seeing one domain merely to make the second pass;
- fixture/mock evidence substitutes for released bytes;
- one Task or one happy path is called cross-domain completion.

---

### Slice 13 — Frozen held-out transfer and paper experiments

#### Deliverables

- freeze framework code, generic prompts/Skills and contracts;
- select a new Need independently after freeze;
- run complete S1 v2 and S2 without framework domain edits;
- matched-budget baselines:
  1. LLM-only Task generation;
  2. execution-filtered trajectory abstraction;
  3. previous Graph/Programmatic proposal;
  4. qualified-capability GoalProgram compiler;
  5. bounded human-authored Task/checker quality reference;
- ablations:
  - remove Need anchors;
  - checker authored after witness;
  - remove physical semantic negatives;
  - remove public provenance gate;
  - text-only diversity selection;
  - no independent actor trials;
- downstream SFT/RL or held-out agent evaluation at matched Task/rollout budget.

#### Metrics

```text
capability disposition and Task yield
public witness success and fresh replay rate
hidden-operand/leak rejection
checker mutation kill rate and false acceptance
valid-alternative false rejection
instruction defect/ambiguity rate
structural diversity and semantic redundancy
actor pass^k/reliability, calls, tokens and runtime cost
held-out Task/tool/state-regime generalization
```

#### Fatal evaluation outcomes

The team does not claim success when the PRD fatal-rejection criteria hold.
Results that refute the approach are reported rather than hidden behind a larger
model, relaxed checker or more generation attempts.

## 5. Full validation commands

Exact real-run commands may acquire additional model/provider flags, but the
final gate includes at least:

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

The held-out run repeats the same public commands after framework freeze.

## 6. Review gates

After each controlled implementation worker turn:

1. inspect the complete diff and raw worker report;
2. run the project Alignment Patrol for the exact next transition;
3. dispatch an independent check worker;
4. attribute every failing gate before repair;
5. rerun affected unit tests and the latest complete real vertical.

Before any commit/release-like transition, run a fresh Patrol check in the same
shell condition as that transition. A stored earlier `ALLOW` is not authority.

## 7. Rollback points

- Until Slice 4 passes, no v2 release is publishable.
- Until Slice 8 passes, no candidate has constructive solvability evidence.
- Until Slice 10 passes, no Task is admitted.
- Until Slice 12 passes, no cross-domain S2 claim is made.
- Until Slice 13 passes, no held-out generality or downstream-training claim is
  made.

Because compatibility is out of scope, rollback means reverting the current
slice/branch changes, not preserving dual v1/v2 production paths.

## 8. Planning completion checklist

Before `task.py start`:

- [x] PRD rewritten against the new product intent;
- [x] technical design defines S1 v2, S2 semantics and deletion list;
- [x] implementation slices and real validation gates are explicit;
- [ ] parent product PRD and accepted decisions reflect the redesign;
- [ ] `implement.jsonl` and `check.jsonl` contain real curated context;
- [ ] fresh plan-document Alignment Patrol has reviewed the complete artifacts;
- [ ] user has reviewed the final summary;
- [ ] a later user message explicitly approves implementation.
