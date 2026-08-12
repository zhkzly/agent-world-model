# Implementation plan revision 9 — node-first Direct foundation, closure lineage C5

> **Current execution authority (2026-08-11):** the active repair is
> `research/direct-design-semantic-closure-plan.md`, digest
> `abbab652bfbd389bde56d4c9879948e0c6436faa4eb5ef2a72c8d1f220a3c219`, allowed by
> `research/cross-layer-review-abbab652-design-semantic-r2.md`. Earlier C5–C8
> and live-repair sections below are retained only as completed audit history;
> they are not alternative implementation plans. The task is the Direct child
> of `08-11-foundry-complete-v1`.

## Scope and gates

Revision 8 is expired because it coupled CandidateBuild to VerifierIntent and
did not define model-visible inputs, Prompt/Skill contracts or routing
authority before implementation.

This task implements the first honest Direct vertical slice of the R9
architecture: DesignGraph + CandidateGraph, canonical generated-environment
protocols, independent execution/Judge/release and read-only Observe. It does
not implement ExpandCampaign, multi-parent source reuse, training adapters or a
general repair scheduler. Those use the frozen seams in separate children.

The user authorized continuing the complete-v1 sequence autonomously. C5
retains the C1 schema/owner, C2 difficulty, C3 verified-flat-store and C4
hashed-pip-sync decisions. It closes only the C4 full-scope review's finite
lock-closure, empty-requirements and project-discovery facts; it does not reopen
graph shape, routing, repair, Expand or training scope.

No product code may change until:

1. this exact R9-C5 plan digest receives a fresh independent full-scope cross-layer
   `allow`;
2. the matching allow record replaces expired review entries in both JSONL
   manifests; and
3. the current complete-v1 parent digest receives a fresh independent `allow`
   because its shared Direct/Expand/Consumer difficulty handoff changed.

Implementation occurs only in `/home/kelong/pycodes/foundry-direct-graph` on
branch `foundry-direct-graph`. The dirty legacy/root worktree is not a source of
production modules. Existing cleanroom code is edited or deleted in place so a
second orchestration path cannot accumulate beside it.

## Ordered implementation

### 1. Re-anchor and measure the cleanroom

- Record the clean baseline commit and current production/test line counts.
- Confirm public imports and CLI have no legacy StateGraph, scheduler, replay,
  ExpansionCampaignRunner or compatibility authority.
- Record a Product Alignment Checkpoint: the proof target is still natural
  language -> executable isolated environment -> independent Judge -> Registry
  package -> Observe; graph completion alone is not success.
- Keep existing Artifact, Invocation, Runtime, config and Registry behavior
  unless a later step names the exact changed contract.

### 2. Freeze node contracts before executors

- Encode the static R9 Node Contract Cards from `design.md` as tests/closed
  declarations before moving orchestration code. The closed input projections,
  output roots and handoff schemas in `node-contracts.md` are binding.
- For every model-facing node, fix the exact graph inputs, model-visible
  projection, route, Prompt objective, closed output shape, Skill/tools,
  validation, local correction packet and downstream consumer.
- Recursively reject model-facing output schemas that can reach Gate, Finding,
  target node, budget, manifest, hash, Judge or release authority.
- Bind Prompt/input projection/output model/runtime Skill materialization to the
  node semantic revision. Store only safe digests/provenance, never Prompt body,
  credential or private transcript in run state.
- Do not implement a node whose card is incomplete; revise the plan and critic
  if an unplanned model input or consumer appears.

### 3. Add the smallest domain graph kernel

- Add one immutable `NodeSpec`, one `EdgeSpec`, graph identity and typed port
  declarations.
- Give every Node one explicit `execution_kind` from
  `FRAMEWORK/DIRECT_LLM/AGENT/CANDIDATE_PROCESS`; Integration/Judge use the
  untrusted process boundary without transferring validation/commit authority.
- Add one deterministic runner that validates graph/port closure, resolves
  exact ArtifactRefs, executes nodes in a fixed topological order, records node
  revision/status/dependencies and stops unreachable descendants.
- Change Artifact writes to an immutable `ArtifactEnvelope` that binds producer
  graph/node/shard/revision, semantic revision digest and exact ordered
  dependencies. Write one terminal `WorkRecord` per node revision with exact
  inputs/direct dependencies/outputs, validation/assurance/Finding refs,
  execution kind, safe status and immutable `invalidated_by=null`. DirectRun
  stores ordered WorkRecord refs instead of treating coarse stage events as
  provenance.
- Keep model proposal, framework validation/assurance and Artifact commit as
  observable phases of one Node transaction. Raw proposal output is never an
  Edge payload.
- Represent bounded Design node families with explicit Python loops and stable
  coordinates; do not add dynamic scheduling or concurrency in this slice.
- Do not add Node subclasses, YAML/TOML graph DSL, handler plugins, callbacks,
  event bus, SubgraphNode, distributed queue or generic workflow API.
- Prefer a compact implementation; if graph/control code grows beyond the
  existing orchestration it replaces, stop and simplify before continuing.

### 4. Make runtime model inputs explicit

- Retain the cleanroom `openai-codex==0.144.4` integration as one thin
  `CodexAgentBackend`; do not replace it with copied legacy invocation code.
  `AgentRoute` remains exactly `model/base_url/api_key_env`, and the adapter
  directly creates one ephemeral `AsyncCodex` thread, uses
  `wire_api="responses"`, top-level request/stream retries `0`, constant
  `Sandbox.full_access`, and the existing `InvocationResult/InvocationError`.
  Primary/fallback is the only adapter recovery.
- Move the four product runtime Skill bundles out of string literals and out of
  `.agents/skills/` into a small product-owned runtime resource directory:
  `research-world-evidence`, `engineer-build-planning`,
  `challenge-agent-world`, `engineer-environment-codegen`.
- The Codex backend mounts exactly one bundle read-only for each Agent node and
  no ambient project/global Skills, Hooks or MCP.
- For each turn, create one disposable `CODEX_HOME`, copy exactly one complete
  bundle, compute its closure digest before and after, close the SDK session and
  delete the directory. Do not add a `ProfileResolver`, capability/permission
  matrix, configurable sandbox, hook/MCP loader, SDK worker protocol, callback
  lifecycle or profile/plugin DSL. Temporary `CODEX_HOME` is only the SDK Skill
  discovery root, not a project access-control abstraction.
- Direct LLM nodes receive only model + rendered prompt/input + response
  transport; they receive no Skill, tool, workspace or hidden instruction.
- Keep configuration minimal: existing `direct` and `agent` routes plus
  Search/Fetch/Extract provider settings. Skill choice and node authority are
  code contracts, not user-configurable plugin/profile DSL.
- Add backend-spy tests proving the exact visible files/fields and absence of
  disallowed context for every Agent/Direct node.
- Add one real SDK preflight with a public nonce marker present only inside its
  mounted bundle. The text prompt does not contain the marker. The turn must
  return the initial `Available skills` names as the exact singleton and the
  marker; framework also checks the physical singleton closure/digest,
  non-ambient `CODEX_HOME`, session close and cleanup. Any mismatch is
  `agent_skill_surface_unverified`, never a fallback to ambient configuration.

### 5. Implement DesignGraph as bounded semantic transactions

- Replace the current single `_research`/`_design` blob with the DesignGraph
  sequence in `design.md`.
- Run `research_plan` Agent -> framework `research_acquire` Search/Fetch/Extract
  -> `research_synthesis` Agent. Framework exposes one-based citation catalogs,
  maps indexes to persistent source refs, validates provenance and commits
  EvidenceGraph/CoverageMap.
- Run prompt-only semantic transactions for WorldArchitecture, optional shared
  tool groups, one ToolSemantics coordinate per frozen tool, WorldRules,
  CurriculumPlan and one TaskRequirement coordinate per task family.
- CurriculumPlan proposes 1..6 ordered difficulty dimensions per family, each
  with 2..5 ordered semantic levels. Framework validates stable unique names,
  finite levels and order, compiles `DifficultySchema`, and makes
  TaskRequirement consume that exact schema read-only. No later node or
  candidate may redefine it.
- Each node exposes only the minimum committed predecessor projection. Model
  output contains business source IR/RuleDraft only; framework compiles IDs,
  schema, references, Reward, Task Materializer protocol,
  VerificationRequirements and ImplementationContract.
- Use fixed bounded tool/task counts and deterministic order for the first
  proof. Do not copy old Designer/Scheduler modules from the root worktree.
- Modeling Gate commits one complete EnvironmentDesign or an honest terminal
  non-release. A partial model response cannot become a Design checkpoint.

### 6. Implement CandidateGraph with independent branches

- Run BuildPlan and VerifierIntent as sibling nodes from the same exact Design.
- CandidateBuild receives Design, ImplementationContract and BuildPlan only.
  Delete `.foundry-challenge.json` and all Challenger/Verifier input from the
  codegen Skill, prompt, workspace and dependency list.
- VerifierIntent receives Design/Task/public contract projections and no
  candidate source. Framework compiles case IDs, seeds, public/sealed split and
  closed VerifierBundle.
- CandidateBuild writes a fresh workspace containing Task Materializer, Runtime
  and required dependency/source files. It returns only a bounded completion
  statement; framework scans physical bytes, paths, modes, hashes, sizes and
  dependencies and commits EnvironmentCandidate.
- Direct supplies `origin=direct`, empty semantic/implementation parent lineage
  and no parent source roots.
- Start Integration immediately after Candidate commit. V1 may execute the
  sibling branches in stable order, but dependency declarations and tests must
  prove Integration does not depend on VerifierIntent.

### 7. Enforce the canonical candidate process contract

- Execute Task Materializer and Runtime out of process; never import candidate
  code into framework/Judge.
- Materializer implements
  `materialize(seed, task_type, actor, difficulty)` and returns exact echoes,
  closed `public_goal` data and bounded `initial_config`; it cannot return an
  instruction, evaluator goal, expected solution, reward or termination.
- Framework validates exact echoes and closed schemas, renders
  `PublicTask.public_instruction` from the compiled TaskRequirement template,
  binds a private `EvaluatorGoalBinding`, and uses compiled Rule IR/RewardSpec/
  TerminationSpec for trusted reachability and Judge evaluation.
- Runtime advertises exactly `handshake/reset/invoke/snapshot/close`, binds
  seed/actor/initial config at reset and enforces idempotency keys.
- `snapshot` remains private to Integration/Judge/future Consumer. Candidate
  code never computes evaluator goals, reward, termination, Gate or release.
- Before `uv`, canonical-parse candidate `pyproject.toml`/`uv.lock` and enforce
  the rejection matrix in `node-contracts.md`: no build backend/sdist,
  workspace/group/editable, custom index, Git/URL/path/local source, unlocked
  wheel or missing trusted wheel. Copy only exact hash/size-matched wheels into
  an empty framework-owned run-local wheel directory, keep uv's run-local cache
  separate, and compile the complete admitted transitive lock closure into a
  finite `AdmittedLockClosure`. Each entry contains canonical distribution name,
  exact version and the admitted wheel filename/hash/size set. Derive one
  unambiguous complete transitive closure only; reject markers, extras, forks,
  duplicate/multiple versions or any shape that would require framework
  resolution. Compile that closure into a temporary framework-owned
  requirements file. Every line is normalized `name==version` and carries the
  admitted hash set; candidate text is never copied verbatim.
- Require the tested framework binary `uv 0.11.29`; another version fails the
  current assurance rather than silently changing installer semantics. Invoke
  only these two argv lists, never a shell or candidate project install:

  ```text
  uv venv --no-project --python <framework-python> --no-python-downloads
    --config-file <empty-framework-uv.toml> <fresh-venv>

  uv pip sync --python <fresh-venv-python> --offline --no-build --strict
    --allow-empty-requirements --require-hashes --no-index
    --find-links <run-local-verified-wheel-store>
    --config-file <empty-framework-uv.toml>
    --cache-dir <run-local-verified-wheel-cache>
  ```

  Both commands use `cwd=<fresh-framework-work-dir>` outside the candidate root.
  The final positional input to `uv pip sync` is the framework-owned hashed
  requirements file. `--find-links` is the sole selected ingestion surface and
  always pairs with `--no-index`; `uv pip sync` never reads candidate
  `pyproject.toml`, `uv.lock` or config. Pass only a minimal environment with a
  fixed PATH; remove candidate/ambient `UV_*`, index, proxy, credential,
  Python-path and config variables. Empty requirements are valid only when the
  admitted closure is empty. Rehash candidate source, lock, requirements and
  verified wheel store after sync and enumerate the fresh venv distributions;
  canonical `(name, version)` pairs must equal the admitted closure exactly,
  with no duplicate, missing, extra or candidate-root distribution. Missing
  wheels, mutation,
  attempted network or attempted build is a terminal Integration failure,
  never a relaxed retry.
- Do not implement a wheel downloader or dependency configuration subsystem.
  The first live Direct proof may be stdlib-only; an operator-provided trusted
  wheel store is a composition-root dependency, and a missing requested wheel
  fails honestly.
- Integration then executes unknown seed/actor/difficulty,
  materialize/reset/invoke/idempotency/snapshot, restart and teardown checks.
- Exercise at least two valid selections for one task family and prove changing
  one level changes `public_goal` or `initial_config`; reject missing, extra,
  duplicate, reordered and out-of-domain selections before Judge/release.
- Persist IntegrationReport bound to exact Design and Candidate. Any non-passed
  result stops the graph before Judge, Package and Registry; downstream nodes
  remain `not_run`.

### 8. Keep Judge evidence-only and release framework-owned

- Judge receives exact Design, Candidate, passed Integration and VerifierBundle
  refs and launches fresh untrusted processes.
- JudgeReport contains claim/gate status, subject/evidence refs, safe codes and
  metrics. It contains no target node, retry count, invalidation set, repair
  budget or release action.
- Persist framework Findings for failed claims with a framework-derived owner,
  expected condition and blocking effect but no route/control fields; this
  slice terminates honestly rather than adding a partial automatic repair loop.
- Controller's `package` handler is the single framework ReleaseKernel: only it
  converts the exact passed hard-claim closure into a ReleaseDossier/Package.
  Registry may independently reject or atomically publish that package, but it
  cannot reinterpret Judge or create another release verdict.
- PackageWriter binds Design, candidate source closure, Materializer/Runtime
  protocols, passed Integration, Judge evidence and a pre-package release
  dossier. Derive one minimal pre-publish TelemetryReleaseSummary from exact
  WorkRecords/operation evidence; missing usage remains `unknown`, not zero.
  PackageWriter writes the exact `envpkg.toml`, typed `manifest.json`,
  `pyproject.toml`/`uv.lock`/`LICENSE`, world/rule, task/protocol,
  provenance/assurance/fidelity, recompiled SBOM and scanned source closure
  specified in `node-contracts.md`; a `manifest.json + runtime.py` zip is
  rejected. It
  excludes sealed cases, evaluator instances, expected output corpus, solution,
  secret, transcript, absolute workspace path and mutable parent dependency.
- Registry stages and cold-reads every physical package file, canonical-parses
  metadata, recompiles SBOM, rehashes source/package bytes and verifies Artifact producer/
  dependency closure. It must bind the exact passed Integration for the same
  Design/Candidate, Judge/Verifier evidence, pre-package dossier and mandatory
  TelemetryReleaseSummary before atomic publication. Preserve `origin=direct` and canonical
  `parent_package_refs=[]`.
- After the Registry cold-read and atomic publication, emit one closed
  `EnvironmentPackageRef` binding package/manifest digests, Registry receipt,
  exact Design/Candidate/passed Integration/Judge refs and separate semantic/
  implementation lineage refs.

### 9. Make Observe project the real graph facts

- Replace coarse stage events with a safe ordered projection of graph ID, node
  coordinate/revision, dependencies, owner, execution kind, status and committed
  Artifact IDs.
- Show Findings and terminal non-release codes without Prompt, Skill body,
  credential, sealed data, evaluator goal, raw source or workspace path.
- Independently re-check Registry receipt/package before displaying
  `released`.
- Do not create dormant campaign, repair scheduler or training projections.

### 10. Deterministic validation

Add focused tests for:

- exactly two graph definitions, one Node/Edge abstraction and no forbidden
  generic graph/plugin mechanisms;
- every Node Contract Card: exact graph input/output, minimum model projection,
  Prompt/Skill binding, output schema and validation/commit rule;
- Direct nodes mount zero Skills; Agent nodes mount exactly one expected bundle;
- the Codex backend remains one direct `AsyncCodex` adapter with the three-field
  route, fixed full access and no profile/capability/permission framework;
- closed `FieldDeclarationDraft`, `ArgumentStrategyDraft` and framework owner
  matrix reject unknown branches, out-of-bound values and a second release
  owner;
- CandidateBuild cannot receive VerifierIntent/Challenge/sealed/Judge/release
  data, and Integration has no Verifier dependency;
- framework, not Agent, computes candidate/package hashes and manifests;
- Artifact envelopes and WorkRecords reject missing/wrong producer,
  execution kind, semantic revision, direct dependency order or non-framework
  invalidation; Integration/Judge preserve candidate-process isolation without
  transferring commit authority;
- Findings reject absent/mismatched framework owner, expected condition,
  evidence, blocking effect or any route/control field;
- Registry cannot publish a package whose physical closure disagrees with those
  records, and released `EnvironmentPackageRef` cold-read rejects changed
  package/manifest/receipt or closure/lineage refs;
- bounded Design node-family materialization and exact dependency closure;
- separate Materializer, exact five-operation Runtime, unknown seeds/actors/
  difficulties, deterministic reset and idempotent invoke;
- Curriculum-to-TaskRequirement dependency closure, closed ordered difficulty
  mappings, exact Materializer echo, paired-level semantic change, and rejection
  of missing/extra/duplicate/reordered/unknown levels; cold-read must preserve
  the same schema digest and future `EpisodeRequest` must validate against it;
- exact offline `uv` argv/environment plus hostile build-backend, custom-index,
  Git/URL/path/editable and sdist-only candidates; each fails before a marker
  build hook, network request or candidate process executes, while a trusted
  locked-wheel case installs without installing/mutating the candidate root;
- Integration failure leaves Judge/Package/Registry `not_run`;
- a poisoned/malformed VerifierIntent still allows CandidateBuild and
  Integration to commit, while Judge/Package/Registry remain `not_run`; no
  challenge/verifier file or field reaches CandidateBuild;
- malicious Materializer outputs (wrong echoes, extra/private authority fields,
  invalid goal/config shape or nondeterminism) fail before Judge/release;
- mismatched passed Integration evidence and tampered package metadata/source
  fail Registry cold-read;
- required real invocation and research operation categories are present in the
  pre-publish TelemetryReleaseSummary, and unknown token/cost usage is never
  rewritten as zero;
- Judge output has no routing/release authority and Registry binds exact passed
  evidence;
- safe Observe, empty Direct parent lineage and zero legacy imports.

Run:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy agent_world
uv run python -m compileall -q agent_world
```

### 10A. R9-C6 blocked-contract closure

The first whole-diff `trellis-check` is preserved at
`research/direct-c5-check-block.md` with decision `block`. Before any real
provider proof, implement the exact minimal correction plan in
`research/direct-c6-contract-closure-plan.md`: enforce graph port/Edge
bindings, one model/Agent output-contract correction, complete frozen Builder
protocol inputs, executable private Verifier cases, evidence-derived telemetry,
physical dependency/SBOM/package/Registry closure, and a secret-free candidate
process/source boundary. Delete hard-coded telemetry and stdlib-only Skill
contradictions. Add no third graph, scheduler, repair loop, generic verifier,
permission system or later-child path.

This C6 section is part of the Direct implementation gate. Recompute the plan
identity over the existing Direct plan inputs plus the C6 plan and blocked
check record, obtain a fresh independent Terra cross-layer `allow`, then
implement and rerun an independent whole-diff check. The proof order below is
unchanged and remains forbidden until that check allows it.

### 10B. R9-C7 final contract closure

The independent C6 whole-diff check is preserved at
`research/direct-c6-whole-diff-check-block.md`. Before any real proof, implement
only `research/direct-c7-final-contract-plan.md`: make each declared model/Agent
local correction carry an exact path/condition/category into the second call,
and make the frozen Builder ABI plus Runtime supervisor reject missing or extra
fields for all five response envelopes. Reuse the existing packet, runner,
Agent adapter and Runtime functions. Add no feedback subsystem, schema engine,
new node/graph, general retry facility or later-child path.

Recompute the exact Direct and parent plan identities including the C6 block
and C7 plan, obtain a fresh independent Terra cross-layer `allow`, implement,
and repeat the whole-diff check. The proof order in section 11 is unchanged.

### 10C. R9-C8 exact port provenance closure

The independent C7 whole-diff check is preserved at
`research/direct-c7-final-whole-diff-check-block.md`. Before any real proof,
implement only `research/direct-c8-port-provenance-plan.md`: commit the existing
logical output-port tuple in each Artifact envelope, validate the exact Edge
source port, and add the omitted direct Artifact bindings at ResearchSynthesis,
TaskRequirement, ModelingGate, Package and Registry. Registry must bind the
actual dossier/telemetry/lineage/package-closure refs rather than using the
Package envelope as a fake dossier value.

Reuse `ArtifactEnvelope`, `NodeSpec`, `EdgeSpec`, `GraphRunner` and the existing
fixed executors. Add no `PortRef`, split-output protocol, node, graph, scheduler,
media/plugin system or later-child path. Recompute the Direct and parent plan
identities, obtain a fresh independent Terra cross-layer `allow`, implement and
repeat the whole-diff check. The proof order in section 11 is unchanged.

### 11. Small true-boundary proofs

Run proofs in increasing cost order:

1. one real Direct LLM node with its exact Prompt/input/output contract;
2. one real read-only Codex Agent SDK preflight proving the initial exact-one
   `Available skills` surface, bundle-only nonce marker, physical closure
   digest, isolated `CODEX_HOME`, session close and cleanup;
3. one real CandidateBuild Agent producing Materializer + Runtime in a temporary
   workspace, followed by framework scan, exact offline wheel-only install and
   isolated Integration that materializes two admitted difficulty selections
   and rejects one invalid selection before release;
4. one fresh public Direct E2E from an unfixed natural-language need through
   DesignGraph, CandidateGraph, Judge, Registry cold-read and terminal Observe.

If a proof fails, read Observe before acting and follow Debug -> Diagnosis
Record -> revised repair plan -> fresh critic -> implementation -> smallest
proof -> Observe. Do not patch prompts, Skills, contracts or retries directly
from a terminal symptom.

The successful Direct E2E does not prove automatic repair, Expand, parent-code
reuse, multi-parent synthesis, policy quality, Consumer/SFT/RL or universal
model reliability.

### 12. Check and publish

- Dispatch fresh Critic/research, implementation and check workers separately
  with explicit `--provider codex --model gpt-5.6-terra`, exact task manifests,
  exact diff scope and proof evidence. Do not inherit a main-session model;
  this development-only choice does not alter product runtime routes.
- Run the legacy-reference firewall and verify changed graph code replaced,
  rather than wrapped, monolithic orchestration.
- Append Product Alignment Checkpoints at DesignGraph, CandidateGraph, true
  proof and release boundaries.
- Commit only intended cleanroom files and push `foundry-direct-graph`. Never
  commit credentials, E2E state, model transcripts or generated temporary
  workspaces.

## Sibling handoff

The parent `08-11-foundry-complete-v1` owns the later deliverables. After this
child passes, persist one handoff with the exact clean-worktree commit, shared
contract digest, real Direct package/Registry receipt, safe Observe scene and
explicit non-claims. The following siblings consume that frozen handoff:

- `08-11-foundry-bounded-repair`;
- `08-11-foundry-expand-multiparent`;
- `08-11-foundry-consumer-sft-rl`.

Do not implement their dormant control paths here. Do not retain the stale
`afad1826...` allow in dispatch manifests; obtain a new allow for this child
under the complete-v1 parent architecture.

Before dispatch, synchronize the approved parent/child task artifacts and the
minimally updated execution index into the clean worktree. A worker may not rely
on another worktree's uncommitted task files or inherited chat context.
