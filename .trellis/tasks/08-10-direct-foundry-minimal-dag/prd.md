# Foundry Direct graph foundation — complete-v1 child 1

## Goal

This is the first executable slice of a lightweight, domain-specific graph
design. It creates a clean `foundry-direct-graph` foundation that makes the
verified Direct trust path explicit, inspectable and reusable without creating
a generic workflow platform. The product outcome remains a natural-language
need becoming an independently verified, Registry-released
`EnvironmentPackage`.

The longer-term product is not a collection of one-off environments. It is a
growing, diverse environment library: released packages act as verified
semantic anchors; newly acquired technical documentation supplies evidence for
new tool surfaces and behavior; an Evolve campaign proposes semantic changes,
then sends every candidate through the same complete Design -> Build -> Judge
-> Release path. This is analogous to the useful *loop* in AlphaEvolve, but
the evolving object here is an executable Agent environment, not an algorithm
source file or a single scalar score. Direct E2E is therefore a necessary seed
proof, never a claim that the whole product or its core innovation is finished.

This task is child 1 of `08-11-foundry-complete-v1`. The parent owns the shared
Direct/Repair/Expand/Consumer contracts and final product acceptance. This child
owns only the Direct foundation and must freeze an exact output commit/contract
digest before any dependent child starts. The former `afad1826...` Direct-only
critic allow is stale because the shared system scope changed; a fresh
child-specific allow is required before implementation.

## System invariants — domain graph, not workflow platform

The product has three executable paths plus one read-only plane. Their durable
artifacts and authority boundaries must be designed now, even though this task
implements only the Direct foundation:

| System path | Input and outcome | Authority boundary |
| --- | --- | --- |
| **Direct / seed generation** | `EnvironmentRequest` -> compiled Design -> independently judged `EnvironmentPackage` or honest terminal non-release | Framework controls gates/release; bounded Researcher/Engineer/Challenger Agent and Direct LLM work only propose semantic/code artifacts. |
| **Expand / library evolution** | frozen released package/request anchors + permitted technical-document evidence -> typed semantic change -> a newly compiled Design -> `CandidateOutcome` and possibly a new `EnvironmentPackage` | Framework freezes parents/sources/budget and validates evidence; Policy/Operator control semantic proposals only. Builder may reuse verified parent code after Design is frozen, but no Agent or Policy inherits a parent verdict or publishes. |
| **Consumption / SFT and RL** | exact released package versions -> immutable Suite snapshot -> isolated parameterized Episodes -> SFT examples or online RL transitions | Framework-owned Consumer materializes tasks and computes reward/termination; training code cannot mount package/private evaluator state or alter release facts. |
| **Observe / explanation** | durable Direct, Campaign, Artifact and Registry facts -> safe run/campaign/release scenes | Read-only projection; it never selects, mutates, retries, judges or publishes. |

Both Direct and Expand must converge at the same compiled Design -> candidate
core -> independent Judge -> Registry path. Expand is not a late node appended
to Direct: it is a separate campaign/control loop that supplies a new compiled
Design from parent semantic anchors and technical evidence. Conversely, Observe
is not a dashboard added after the fact: it is the safe explanation surface for
both paths. R9 represents the two reusable generation boundaries as small typed
Python graphs with one Node abstraction and one Edge abstraction; no generic
workflow engine, scheduler product, plugin system or DSL is part of the design.

## Confirmed facts

- The baseline is `foundry-direct-rewrite@9562c05`, which has one real Direct
  E2E release and a minimal read-only Observe implementation.
- The clean `foundry-direct-graph` worktree already pins
  `openai-codex==0.144.4` and has a compact `CodexAgentBackend` built directly
  on `AsyncCodex`: its route is only model/base URL/API-key environment handle,
  it uses a temporary `CODEX_HOME`, constant SDK full access and the existing
  `InvocationResult/InvocationError`. This is the retained baseline; the legacy
  profile/capability/permission stack is not a migration source.
- Its pipeline is currently sequential in `agent_world/foundry.py`; no public
  `expand` path exists in that cleanroom.
- The inspected cleanroom already writes the correct Direct package lineage:
  `origin=direct` and `parent_package_refs=[]` in the framework-built manifest.
  This task must preserve that fact, not add a second lineage mechanism.
- The inspected cleanroom has one real fail-close gap: after persisting an
  `integration` result, `DirectFoundry.generate()` invokes Judge without first
  requiring `integration["status"] == "passed"`. A later Judge normally rejects
  the same bad candidate, but the contract requires Integration failure to stop
  before Judge and Registry.
- The canonical executable-environment contract requires a separate untrusted
  `materialize(seed, task_type, actor, difficulty)` function plus Runtime
  `handshake`, `reset(seed, actor, initial_config)`,
  `invoke(tool_id, arguments, idempotency_key)`, private `snapshot`, and
  `close`. The cleanroom currently advertises only
  `handshake/reset/invoke/close`, calls argument-free reset, omits idempotency,
  generates only `runtime.py`, and has no parameterized Task Materializer.
  Therefore revision 7's promise to leave `runtime.py` unchanged is not
  compatible with the source-of-truth product or later SFT/RL use.
- The canonical contract also requires every `TaskRequirement` to carry both
  difficulty dimensions and levels. The former C1 plan named dimensions but
  gave no node authority to define their finite level domains. C2 closes that
  producer/consumer gap: Curriculum proposes bounded ordered dimensions and
  levels, framework compiles one closed per-family `DifficultySchema`, and
  Materializer, Integration, Judge, package and Consumer only reuse it.
- The canonical source document defines Direct as independent and required;
  Evolve is an optional, separately budgeted coverage/diversity extender.
  It explicitly defines technical-document and tool-ecosystem research as
  ExpansionSource inputs, released packages as Pool/parent anchors, and
  `ToolSurface` / `ToolSemantics` / `TransitionConstraint` / `TaskScope` as
  the Evolve genotype.
- The execution map deliberately limits the first cleanroom slice to Direct,
  minimal Observe, and package lineage facts. It explicitly excludes a generic
  Graph engine as well as a current Campaign implementation.
- The legacy/current-root StateGraph and ExpansionCampaignRunner are not a
  migration source. They embody the duplicate control-plane and oversized node
  taxonomy this rewrite must avoid.
- `docs/plans/stategraph-rewrite.md` and `docs/observe-expand-handoff.zh.md`
  are historical design evidence, not code to transplant.

## Requirements

1. Represent generation with two compact typed domain graphs: `DesignGraph`
   converts a bounded DesignRequest into one compiled EnvironmentDesign;
   `CandidateGraph` converts that Design into an independently judged and
   possibly released package. Use stable node coordinates, declared typed
   ports, Artifact handoffs, owners, execution kinds and terminal effects. One
   small deterministic runner may execute both graphs; no generic workflow
   platform, callback bus, dynamic plugin registry or YAML DSL is allowed.
2. Preserve the trust split: only Direct LLM work performs prompt-only semantic
   design; only explicitly-mounted Codex Agent work performs research
   synthesis/advisory/code generation; candidate processes and framework work
   are neither LLM nor Agent.
3. Preserve real Direct E2E behavior, clean candidate isolation, independent
   Judge, Registry release, and read-only Observe facts. In particular, an
   Integration failure is recorded and terminal before Judge or Registry runs.
   A release must also bind and re-read the exact **passed** Integration Artifact
   for the same compiled Design and Candidate; a run status alone is not release
   evidence.
4. Treat Evolve/Expand as the core second system capability, not an optional
   graph feature. It remains optional and separately budgeted for each Direct
   request, but is non-optional in the system architecture. Keep its correct
   future contract visible at the candidate boundary:
   Direct preparation and Evolve preparation both produce a frozen Design input;
   the shared candidate core then performs Build -> Integration -> Judge ->
   Release. A released parent contributes stable semantic/package lineage facts;
   a technical document contributes real search/fetch/extract evidence; an
   eventual Policy/Operator creates a typed semantic delta; Designer rebuilds
   a complete child Design. Builder may then reuse, adapt or rewrite exact
   released-parent source closures as an implementation strategy. A child never
   inherits a parent's release verdict, and a source-only patch with no semantic
   delta does not count as evolution.
5. Do not reintroduce the old graph engine, legacy scheduler, replay path,
   compatibility ABI, callbacks, generic plugin system, or a second success
   route.
6. Observe remains a read-only projection. It does not select parents, mutate
   a candidate, retry work, or decide release.
7. Preserve one training-compatible environment contract without coupling a
   trainer into Foundry. An `EnvironmentPackage` is a parameterized world, not a
   fixed task or saved trajectory. An exact released package must later support
   reproducible task materialization, isolated `reset`/tool-step Episodes,
   framework-owned reward/termination, and a strict public/private split. SFT
   export and RL adapters consume the same public Episode surface outside the
   package; optimizer/model/token bookkeeping never enters Runtime or release.
8. Design every Node before implementing it. Its purpose determines exact graph
   input/output ports, minimum model-visible projection, execution route,
   Prompt, closed output model, Skill/tools/workspace, framework validation,
   commit rule, feedback, consumers and proof. Prompt/Skill/feedback may not be
   improvised later merely to make a failed E2E pass.
9. Keep model proposal and framework authority distinct inside every node
   transaction. Direct LLM/Agent output never directly becomes a Gate, Finding,
   manifest, repair route or release fact. Raw proposal data does not flow over
   graph edges; only framework-validated committed Artifacts do.
10. Judge evaluates exact claims and produces evidence-backed Findings. It does
    not know graph topology or select a target node. The current task persists
    route-free Findings and stops. The bounded-repair child will use immutable
    Artifact/Work provenance, closed local route rules, dependency invalidation
    and one repair budget; it will not add an LLM Router and will return
    `needs_human` when deterministic attribution is genuinely ambiguous.
11. Persist exact provenance now rather than reconstructing it later: every
    Artifact envelope and terminal WorkRecord binds producer graph/node/shard/
    revision, semantic revision, ordered input/output/dependency refs,
    validation/assurance/Finding refs and safe status. Registry and Observe must
    consume these records, not infer causality from stage names.
12. Keep Agent execution as one thin Codex Python SDK adapter. Pin the existing
    SDK, keep `AgentRoute(model, base_url, api_key_env)`, disable SDK retries,
    use constant `Sandbox.full_access`, mount one product Runtime Skill in one
    disposable `CODEX_HOME`, close the ephemeral session and clean it up. Do
    not add a permission manager, capability matrix, configurable sandbox,
    inherited profile, hooks/MCP loader, callback lifecycle, worker protocol or
    plugin/profile DSL. A real preflight must prove the model-visible initial
    Skill surface and physical bundle digest; filesystem-only spy tests are not
    sufficient.
13. Candidate dependency installation is framework-controlled and executable:
    pre-parse `pyproject.toml`/`uv.lock`, accept only fixed hash/size-verified
    registry wheels from the trusted store, copy them into one verified
    framework-owned local wheel directory, compile the admitted complete lock
    closure into one finite `AdmittedLockClosure` and a framework-owned
    exact-version/hash requirements file, invoke
    the exact offline/no-build/`--require-hashes --no-index --find-links`
    `uv venv` + `uv pip sync` policy in `node-contracts.md`, and fail closed before
    candidate execution for build backends, sdists, custom indexes, Git/URL/
    path/editable/local sources, ambiguous markers/extras/forks/multiple
    versions or missing wheels. Both uv commands run from a fresh framework
    directory and cannot discover the candidate project. No network/build
    fallback is a success path.
14. Give difficulty one framework-owned contract rather than an unconstrained
    mapping or candidate-defined convention. For each task family,
    `curriculum_plan` proposes 1..6 ordered, uniquely named dimensions, each
    with 2..5 ordered, uniquely named semantic levels. Framework validates and
    freezes the schema; every dimension is required exactly once in declaration
    order and every value must be one declared level. `task_requirement`, the
    Materializer protocol, Integration, Judge, `tasks/curriculum.json`, Expand
    child Designs and future `EpisodeRequest` all consume that exact schema.
    Missing, extra, duplicate, reordered or out-of-domain selections fail
    before release. Candidate code may only exact-echo a valid selection; it
    cannot define, widen or coerce the domain.

## Direct composition and reusable graph boundaries

```text
FoundryController.generate:
  intake -> DesignGraph -> CandidateGraph

DesignGraph:
  research_plan -> research_acquire -> research_synthesis
  -> bounded world/tool/task semantic node families -> modeling_gate

CandidateGraph:
  design -> build_plan -> candidate_build -> integration --------+
  design -> verifier_intent --------------------------------------+-> judge
  judge -> package -> registry
```

`build_plan` and `verifier_intent` are siblings. CandidateBuild consumes only
Design and BuildPlan; it cannot see VerifierIntent or sealed/Judge material.
Integration starts after CandidateBuild and does not wait for verifier work.
The first implementation uses a stable deterministic order where concurrency is
not required. Every failed required dependency halts its downstream works.
`observe` is outside both graphs and projects durable framework facts only.

## Intended Evolve topology (not implemented by this task)

```text
released package Pool + request anchor + technical-document sources
  -> frozen parent/source snapshot
  -> Researcher search/fetch/extract evidence
  -> Policy selects parents, clues, semantic operator and budget
  -> typed SemanticDelta
  -> Designer reconstructs a complete, compiled Design
  -> shared candidate core
  -> CandidateOutcome -> policy feedback / pool evolution
```

The selection signal must combine independent validity/release evidence with
coverage, diversity, lineage and cost. It is not a raw LLM self-score. A
candidate may refine an existing package identity or create a new package, but
every released result is independently judged again.

Selection has two separate levels. Hard validity is non-negotiable: failed
Integration/Judge candidates cannot be published or rescued by any score. Among
admissible candidates, the Campaign policy may optimize a user-given direction
using goal alignment, coverage gain, diversity, lineage and cost. Training
feedback can add a measured capability-gap term, but cannot replace the user's
direction or become release evidence.

## Future Evolve start contract

Evolve starts from a framework-created `CampaignRequest`, not from an Agent
prompt. Its minimum meaning is: an optional package/request anchor or eligible
Pool selector; a user direction expressed as target capability/tool/workflow
dimensions plus optional ranking weights; permitted technical-document sources;
a bounded operator allowlist; a named selection policy; a campaign seed;
independent budget; and a release-profile reference. Framework resolves it once
into an immutable Campaign snapshot containing exact released parent manifest
refs, source/catalog revisions, the frozen direction and budget facts.

This direction is conceptually an evolution objective or fitness preference,
not necessarily an RL advantage function. An advantage function is needed only
if the Campaign policy itself is later trained against a baseline. The first
implementation can be deterministic: filter by hard validity, then rank by the
frozen user target and bounded cost/diversity signals. It needs no learned
policy, scalar reward monopoly or new optimization framework.

Policy extensibility uses one narrow, stateful boundary:

```text
ask(frozen_context, checkpoint, budget) -> MutationIntentBatch
tell(checkpoint, CandidateOutcome[]) -> PolicyCheckpoint
should_stop(checkpoint, remaining_budget) -> StopDecision
```

The Campaign loop, Source acquisition, framework admission, Operator,
Designer, candidate core and release path remain fixed. A future random search,
evolutionary archive, MAP-Elites, MCTS, Bayesian, bandit or learned RL policy
may replace only this boundary. `MutationIntentBatch` permits one or many
parents/candidates without changing downstream contracts; `PolicyCheckpoint`
contains the policy/version, iteration and bounded canonical state needed for
deterministic resume.

`CandidateOutcome` remains a multi-objective fact vector containing hard-gate
status, release status, semantic/coverage/diversity descriptors, fidelity/risk,
cost, repair depth, lineage and optional aggregate training metrics. Core never
compresses it into one universal score. Each policy may scalarize, apply Pareto
selection or learn its own value/advantage while release validity remains
independent.

A policy may choose one or multiple exact released parent package refs in one
`MutationIntent`. Policy, Source, Operator and Designer receive only safe
semantic/contract projections; a bounded `CompositeOperator` defines the
intended semantic combination. After framework compiles one complete child
Design, Builder alone may receive independently verified, read-only source
closures from those exact parent package digests. It chooses reuse, adaptation
or rewrite against the child Design and emits one fresh, self-contained child
workspace.

Framework rescans the final source closure, computes `ImplementationLineage`
from physical parent/final digests, carries forward applicable license/SBOM
facts, and packages all required code. The child never imports a mutable parent
at runtime. `SemanticLineage` explains what world/tool/task meaning changed;
`ImplementationLineage` explains which parent code was reused or transformed.
The result is one normal package with all parent refs recorded, not an
EnvironmentFamily, and inherits no parent's release verdict. The first real
Campaign still uses one parent for the smallest proof, while contract tests
cover plural parent refs and read-only Builder parent workspaces.

The first implementation has one production `directed@1` policy selected by a
small closed mapping or explicit dependency injection, not dynamic imports, a
plugin framework or policy DSL. Its boundary is proven with an alternate test
policy; later production strategies implement the same interface and add only
their own versioned checkpoint schema.

The first open-semantic work after that snapshot is `ExpansionSource`:
framework runs bounded Search/Fetch/Extract, then a mounted Researcher Agent
synthesizes evidence-backed clues. Policy, admission and Operator remain
framework work; Designer is a Direct LLM work; the shared candidate core keeps
the existing Agent Builder/advisory works, candidate process, Judge and
Registry boundaries. See `research/evolve-input-output-contract.md` for the
proposed first-Campaign input/output contract.

## Training consumption contract (designed now, implemented separately)

The training seam begins only after Registry release:

```text
exact EnvironmentPackage versions
  -> immutable EnvironmentSuiteSnapshot (weights, curriculum, seed policy)
  -> framework-owned isolated Episode service
       -> SFT exporter: successful public trajectories -> dataset rows
       -> RL adapter: start/reset -> action/step -> reward/termination -> close
  -> optional aggregate CapabilityFeedback -> future Expand priority only
```

The training-facing surface contains only `PublicTask`, agent-visible
observation, tool schema/action, public tool result/error, scalar reward,
termination/truncation and safe reproducibility refs. It never exposes package
source, full state, `snapshot`, `EvaluatorGoal`, Verifier IR, sealed cases,
release thresholds, secrets or Judge traces. Every Episode binds the exact
package/version/digest, task type, actor, difficulty and seed; different
Episodes never share mutable state.

`difficulty` is not a free-form training label. Consumer reads the exact
per-task-family `DifficultySchema` from the released package and admits only a
complete ordered mapping whose keys and levels match it. It does not infer a
new scale, accept a partial selection or let the Materializer choose levels.

SFT and RL do not need separate environment implementations. SFT converts
framework-recorded public Episodes into filtered examples; RL keeps the same
Episode live behind a minimal client protocol. Training feedback may be
aggregated by capability/tool/task/difficulty and offered to Expand as an
optional prioritization term inside the user-authorized direction. “Optional”
means Expand still works from an explicit user direction, package Pool and
technical evidence when no training run exists. Feedback is never world
evidence, a release Gate, or a dependency of Direct/Evolve success.

Training is a separate downstream subsystem and child task. It depends only on
Registry's exact released-package contract and framework-owned Consumer/RPC;
Foundry imports no SFT/RL framework, model, optimizer or trainer configuration.
Deleting all training adapters leaves Direct and Expand behavior unchanged.

## Acceptance criteria

- [ ] Direct research/critic, implementation and check workers are each
      dispatched with explicit `--provider codex --model gpt-5.6-terra` under
      the complete-v1 parent rule; runtime `direct`/`agent` routes remain
      independent product configuration.
- [ ] The cleanroom Direct path has exactly two static typed domain graphs with
      one Node/Edge abstraction and a small deterministic runner. Its durable
      work view records identity, graph, dependencies, owner, execution kind,
      status and Artifact IDs. There is no Node subclass taxonomy, YAML DSL,
      dynamic plugin/handler platform, callback bus, generic scheduler or hidden
      second control plane.
- [ ] Every Direct work declares the correct component owner and execution
      kind plus a complete Node Contract Card. Tests inspect exact model-visible
      inputs, output schemas, Prompt/Skill binding, feedback limit and committed
      outputs, proving Agent/LLM/framework/candidate boundaries are not
      conflated.
- [ ] The owner table is exact: Designer owns DesignGraph and verifier intent,
      Builder owns build planning/build/integration, Judge owns evidence-only
      judging, Controller has the single ReleaseKernel/package decision, and
      Registry only re-verifies and atomically publishes. No second release
      authority exists.
- [ ] Every model-facing Node uses the exact closed input projection/output root
      in `node-contracts.md`, one-based citation/semantic catalogs, recursive
      authority exclusion and bounded correction visibility. Executors are not
      implemented against placeholder `dict[str, Any]` contracts.
- [ ] CandidateBuild receives Design + BuildPlan and no VerifierIntent,
      Challenger output, sealed case, Judge trace or release policy. Verifier
      and Build are independent sibling branches and Integration can complete
      before VerifierIntent.
- [ ] A malformed/failed VerifierIntent does not prevent CandidateBuild or
      Integration from committing, but Judge/Package/Registry remain `not_run`;
      no verifier/challenge file or field reaches CandidateBuild.
- [ ] The public Direct CLI still reaches Registry release through isolated
      candidate execution, and a fresh Observe call reads the resulting work
      facts.
- [ ] A failed Integration persists its safe report and ends the run as
      rejected; neither Judge nor Registry is invoked, and Observe shows the
      failed `integration` work with all downstream works still not run.
- [ ] A released package's dossier and manifest commit the exact passed
      Integration Artifact digest. Release rejects an Integration Artifact that
      is failed, malformed, or bound to another Design/Candidate.
- [ ] ArtifactEnvelope/WorkRecord closure is immutable and content-addressed;
      wrong producer, revision, semantic-revision digest or dependency refs are
      rejected by persistence, Registry cold-read and Observe reconstruction.
- [ ] Package origin/parent-lineage facts are explicit and safe: Direct
      packages carry `origin=direct` and a canonical empty
      `parent_package_refs` list, proven by a focused package-manifest
      regression. This is sufficient for a later Evolve task to start only from
      released semantic anchors; this task does not claim that Campaign, Policy,
      Source, or Expand E2E exists.
- [ ] No secret, sealed value, Agent self-verdict, or candidate-controlled
      release fact crosses a work boundary.
- [ ] Agent invocation still uses one `AsyncCodex` adapter and the three-field
      route; no profile/capability/permission framework is introduced. One real
      turn proves exact-singleton initial Skill visibility, unique bundle marker,
      bundle closure digest, isolated non-ambient `CODEX_HOME`, session close
      and cleanup; mismatch fails closed.
- [ ] JudgeReport/Finding contain failed claims, subject/evidence refs and
      verdict evidence but no target node, retry, invalidation or release
      action. The bounded-repair child consumes this frozen contract; the
      current task does not claim an automatic repair loop or LLM Router.
- [ ] The Direct candidate/package seam uses the canonical parameterized
      environment contract: a separately executed Task Materializer; exact
      five-operation Runtime handshake; seeded actor-bound reset; idempotent
      tool invocation; framework-private snapshot; framework-owned
      reward/termination; and no evaluator/sealed leakage. A four-operation
      protocol or argument-free reset cannot be released.
- [ ] Framework, not candidate code, renders `PublicTask.public_instruction`,
      binds private EvaluatorGoalBinding and evaluates Rule IR/Reward/
      Termination. Wrong echoes, extra authority fields, invalid goal/config
      schemas and nondeterministic Materializer outputs block release.
- [ ] Curriculum is the sole semantic producer of bounded difficulty
      dimensions/levels and framework is the sole schema compiler. At least two
      valid selections for one fresh task family materialize with exact echoes
      and a changed goal or initial state; missing, extra, duplicate, reordered
      and unknown-level selections fail before Judge/release. The same schema
      digest survives package cold-read and is usable by the future Consumer.
- [ ] The physical package contains canonical envpkg/manifest/dependency lock/
      license/world/rule/task/protocol/provenance/assurance/fidelity/SBOM
      metadata plus the complete scanned source closure. Registry stages,
      canonical-parses, recompiles SBOM and rehashes it; it binds the mandatory
      pre-publish TelemetryReleaseSummary and rejects the baseline
      `manifest.json + runtime.py` shape, mismatched passed Integration or
      tampered bytes. Unknown usage remains unknown, never zero.
- [ ] Offline install uses the exact reviewed `uv venv` and `uv pip sync`
      argv/environment, with a framework-compiled fully pinned and hashed
      requirements closure and the
      verified framework-owned wheel directory as the sole
      `--no-index --find-links` ingestion surface, and accepts
      only matching locked wheels under tested `uv 0.11.29`. Deterministic
      hostile candidates containing
      a build hook/backend, custom index, Git/URL/path/editable dependency or
      sdist-only dependency fail before any hook/network/candidate process can
      run; the valid-wheel case installs in a fresh external venv without
      installing or mutating the candidate root. The stdlib-only case uses the
      same command with an admitted empty closure, and installed canonical
      name/version pairs must equal the admitted closure exactly.

## Out of scope unless explicitly selected

- Transplanting or supporting the old `ExpansionCampaignRunner`, old StateGraph,
  old CLI, replay compatibility, or legacy persisted state.
- A generic workflow platform, Node subclass hierarchy, YAML graph DSL,
  callback framework, dynamic plugin system or distributed scheduler.
- A custom Agent permission/capability system, configurable sandbox/profile
  framework, SDK worker protocol or inherited ambient Codex setup.
- A package-index client, wheel downloader or general dependency provisioning
  service. The first live proof may be stdlib-only; missing trusted wheels fail
  honestly.
- A no-op `expand` command, fake Campaign, pool database, policy framework,
  training/Consumer integration, or a source-only patch falsely presented as
  semantic evolution.

## Selected branch progression

The user selected a system-first route without committing to a generic graph
runtime:

1. This task (`08-10-direct-foundry-minimal-dag`) repairs and proves the Direct
   seed foundation, including the two
   lightweight graph boundaries, node-first model contracts, canonical Task
   Materializer/Runtime and reusable CandidateGraph.
2. `08-11-foundry-bounded-repair` proves framework routing,
   revision/invalidation and
   one real CandidateBuild repair without adding an LLM Router.
3. `08-11-foundry-expand-multiparent` implements a documentation-grounded
   `directed@1` single-parent Campaign and one useful real multi-parent
   composition, both through the shared DesignGraph/CandidateGraph and
   `observe campaign`.
4. `08-11-foundry-consumer-sft-rl` consumes exact Registry
   releases, proves isolated unknown-seed Episodes, exports leak-free SFT data
   and drives one online RL episode. It has no code dependency back into Direct
   or Expand.

Direct completion proves only seed generation. Expand completion proves
environment-library growth. Consumption completion proves training usability.
None of these partial proofs is silently substituted for another.
