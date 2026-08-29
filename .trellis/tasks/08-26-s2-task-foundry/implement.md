# S2 Goal-First Task Foundry — Implementation Plan

## 1. Execution rule

Implement only in the dependency order below. Every checkpoint uses production
interfaces and real processes; an early vertical is not an MVP or completion
claim. A failure returns to its owning checkpoint rather than adding a fallback,
domain branch or compatibility path.

Current baseline:

- v1 code/guidance removed in `9ba397b`;
- v2 release byte verification and two-runtime preparation exist;
- expected-semantics, Semantics Author and Task/S2 identity models exist;
- strict v2 Qualification/Publication and executable S2 do not yet exist.

## 2. Checkpoint A — Freeze corrected contracts

### Work

- Add exact models/decoders for:
  - `QualificationCore` and acyclic identity preimages;
  - verifier request/result and strict Qualification receipt;
  - sealed public-surface/catalog/Requirement-coverage/qualified-StartCase documents;
  - `PublicValueSource` plus run-local `PublicValueOccurrence`;
  - `LogicalBindingRef`, `LogicalSelection` and run-local `ResolvedBinding`;
  - `GoalEvaluationContext` in atomic evaluation.
  - pre-witness `AdmissionPlan` and fresh `EpisodeIdentity`.
- Delete `CapabilitySpec.read_scopes`/`write_scopes` from models, decoders,
  author schema, fixtures and tests. CompositionRule plus the exact selected
  sibling context are the sole composition/collateral authority.
- Replace legacy facet/condition visibility plus tool/pointer fields with the
  single `PublicValueSource`; visibility is derived from source kind and cannot
  contradict it.
- Remove concrete protected bindings from cross-materialization TaskDefinition and
  checker identity.
- Recursively validate Goal→selector/slot/capability/cardinality references and
  require the Goal to consume every frozen binding/selector. Composition and
  ForEach identities live only in their Goal nodes, never duplicate selection annotations.
- Make receipt admission reject arbitrary canonical JSON and fixture verdicts.

### RED tests

- final Release ID cannot appear in Core/Qualification preimages;
- arbitrary/mechanical receipt rejected;
- live ToolSpecs/CapabilitySpecs/StartCases differing from sealed documents rejected;
- concrete protected ID cannot enter TaskDefinition/checker template;
- reset/tool value without exact schema pointer rejected;
- repeated tool calls cannot satisfy provenance without a trace-event occurrence;
- All/ForEach run missing or adding one logical selection member rejected;
- unused selectors/bindings, wrong Goal references/cardinality, duplicate or
  reordered frozen/run members rejected;
- composed/foreach evaluation without exact selected sibling context rejected.
- legacy `read_scopes`/`write_scopes` fields rejected rather than ignored.
- legacy/contradictory visibility/tool/pointer encodings rejected.

### Stop conditions

- new public package format or compatibility reader appears;
- generic state/query/effect DSL appears;
- contracts cannot name one producer and consumer.

## 3. Checkpoint B — Independent verifier authoring

### Work

Implement one fixed standalone uv project authoring route:

```text
EXPECTED_TASK_SEMANTICS.json
PUBLIC_SURFACE.json
QUALIFICATION_VERIFIER_CONTRACT.md
read-only actor view
-> generated_qualification_verifier.release:make_verifier
```

- fresh HOME/CODEX_HOME/thread/workspace;
- no access to TaskSemantics source, outputs, tests or feedback;
- Framework initializes project and owns lock/sync/build/tests/source scan,
  import separation, digest and acceptance;
- model never writes manifest, digest, evidence, receipt or verdict;
- bounded factual repairs stay in the same verifier thread.

### Validation

- verifier source cannot import actor, semantics or Host packages;
- immutable inputs remain byte/mode identical after every turn;
- verifier calls are read-only by before/after tree manifests;
- query/state/process cases exercise distinct axes;
- one real cross-domain verifier project passes its own locked environment.

### Stop conditions

- old three-script Qualifier/native-oracle route returns;
- verifier becomes a public/runtime/S2 tool;
- Framework learns domain field names.

## 4. Checkpoint C — Shared core materialization and v2 Qualification

### Work

- Refactor the existing per-project copy/sync/origin/import logic into one
  internal `materialize_project` primitive.
- Qualification materializes actor, semantics and verifier through it.
- Sealed release preparation continues to materialize actor and semantics only.
- Implement Host-owned physical case runner and evidence manifest.
- Seal exact public-surface, qualified catalog, Requirement coverage and
  qualified StartCase documents from observed accepted evidence.
- Compare TaskSemantics and verifier results axis-by-axis on identical physical
  before/after instances.
- Run positive, no-op, wrong/near-miss target, answer, collateral, process,
  fresh-replay and executable mutation cases as applicable.

### Validation

- no duplicate uv/cache/child-transport implementation;
- public Agent sees no semantics/verifier/checker data;
- verifier sees no protected TaskSemantics binding/facts;
- semantics/verifier call cannot mutate either instance;
- a matched wrong decoder/evaluator mutant cannot pass merely by agreeing with itself;
- missing applicable case or Requirement disposition fails closed.
- S2-visible projections contain no verifier path, native evidence or
  Qualification reference trace.

### First production vertical

Use one real SQLite-backed generated world. The result may establish Checkpoint C
only; it cannot claim S1/S2 completion. Then repeat unchanged Framework code on
the filesystem/Git world before Publication is considered stable.

## 5. Checkpoint D — Strict Publication and cold admission

### Work

- Assemble the frozen actor, semantics, verifier, docs and evidence bytes.
- Write the strict passed receipt from Host evidence.
- Build canonical payload manifest and final descriptor.
- Recompute Core/receipt/payload/Release identities from the assembled directory.
- Produce deterministic directory and ZIP forms.
- Cold install actor/semantics and replay Qualification with archived verifier.
- Expose a direct Python API first; add CLI only after that API is real and tested.

### Validation

- any byte/mode/path/digest/receipt/evidence tamper rejected;
- structural mechanical fixture cannot be admitted or prepared as a release;
- Publication copies frozen bytes and does not rebuild/rewrite projects;
- directory and relocated ZIP resolve to the same Release ID;
- S2 can open exact released bytes without a development checkout.
- admitted runtime ToolSpecs/CapabilitySpecs/qualified StartCases equal their
  sealed digests; audit bytes are reachable only through the cold-audit API.

### Stop conditions

- provisional public release or `allow_unqualified` option appears;
- final Release ID is required to produce Qualification;
- publisher reruns semantic authoring or mutates evidence.

## 6. Checkpoint E — Logical binding and deterministic compiler

### Work

- Implement public source decoders/audits.
- Consume only `AdmittedReleaseView`, its sealed qualified StartCases/catalog and
  live-equality-checked actor/TaskSemantics sessions.
- Build stable `LogicalBindingRef` values and prove fresh rebinding.
- Freeze `LogicalSelection` for every selector, All and ForEach complete set.
- Enumerate bounded Atom/All/If/ForEach Blueprints.
- Compile checker templates with `GoalEvaluationContext`.
- Prove checker false initially.
- Freeze checker, render/audit exact instruction, persist TaskDefinition, then
  permit model calls.

### Validation

- different incidental IDs across fresh starts resolve the same semantic key;
- every fresh run resolves the exact frozen semantic-key set with no missing,
  extra, tie or cardinality drift;
- unresolved/ambiguous/unstable public selector rejects Blueprint;
- All requires exact CompositionRule; If requires qualified public condition;
- ForEach binds the complete selected set;
- permitted sibling effects are not collateral, unrelated effects are;
- compiler contains no domain label/field branches;
- ordering journal makes early model call impossible.

### First production vertical

Compile one real Atom Task from a cold SQLite release and take it through the
same final checker/instruction path later used by every Task. This is a causal
architecture proof, not a Task-yield or completion claim.

## 7. Checkpoint F — Public runner, two witnesses and admission

### Work

- Implement one Host-owned Responses function-tool loop.
- Create a fresh `EpisodeIdentity` and empty conversation state for every
  qualification, witness and assessment run; never reuse previous response IDs.
- Preserve exact prior response/function-result items across turns.
- Validate tool arguments/observations and final answer schemas.
- Resolve every argument leaf to an instruction/reset/tool-output/schema source.
- Run two fresh materializations with independent logical rebinding.
- Derive/freeze `AdmissionPlan` before witnesses and account for every planned
  challenge/mutation in the final report.
- Execute concrete challenges and live checker mutations.
- Seal TaskPack only after complete admission.

### Validation

- no Codex SDK witness loop;
- no checker/native/verifier leakage;
- protected guess, prose/error scraping and load-bearing AgentChoice rejected;
- two witnesses have distinct materialization and resolution evidence;
- same tool/pointer from multiple calls is disambiguated by trace event sequence;
- no Qualification/audit/reference-trace projection reaches compiler or runner;
- valid alternate public route accepted;
- crashing/unreachable mutant gives no credit;
- bounded planner failure remains `NoPublicWitness`.

## 8. Checkpoint G — Assessment, corpus and full paper gates

### Work

- Reuse the public runner with independent model/policy identity for assessment.
- Implement structural fingerprint, semantic deduplication and corpus selection.
- Keep assessment/corpus identities outside TaskPack.
- Run the same frozen framework over SQLite and filesystem/Git releases.
- Freeze code/contracts/prompts, select a held-out Need, and repeat without
  framework domain edits.
- Run matched-budget baselines and downstream SFT/RL or acting-Agent evaluation.

### Required floors

Per conformance release:

```text
>= 20 admitted TaskPacks after semantic deduplication
>= 4 canonical Goal/selector structures
>= 2 qualified StartCase regimes
every core Taskable capability represented or newly Unsupported with evidence
```

Held-out:

```text
>= 10 admitted TaskPacks
>= 3 canonical structures
>= 2 taskable capabilities or an explicit method-falsifying result
```

Completion additionally requires full solvability/checker/leakage/cold evidence
and matched-budget downstream value. Parameter swaps/paraphrases do not count as
new structures.

## 9. Validation commands

Every checkpoint:

```bash
UV_CACHE_DIR=/tmp/foundry-s2-uv-cache uv lock --check
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
git diff --check
```

New deterministic enforcement requires RED/GREEN and a mutation licence. Real
provider/process evidence is mandatory for authoring, Qualification, witness and
assessment claims; fake clients prove transport shape only.

## 10. Causal rollback

Attribute the first incorrect owner before editing:

```text
Research/Brief
Environment Builder
Expected semantics
TaskSemantics Author
Verifier Author
Core materialization
Qualification
Publication/preparation
logical binding/compiler
checker/instruction
public runner/provenance
admission
assessment/corpus
Infrastructure
```

Rollback the current checkpoint. Never add a v1 path, alternate reader,
`allow_unqualified`, domain patch or relaxed gate.

## 11. Completion boundaries

- Before D: no EnvironmentRelease v2 product claim.
- Before F: no publicly solved Task.
- Before complete admission: no TaskPack.
- Before G cross-domain floors: no S2 completion.
- Before held-out/downstream gates: no generalization or paper-value claim.
