# Design revision 9 — executable, node-first Foundry domain graphs (C5)

Review lineage `C5` supersedes C4 without changing the R9 graph architecture.
C1 closed concrete field/verifier subtypes and framework owners, executable
offline supply-chain policy, a real Codex Runtime-Skill proof with no permission
framework, and review digest identity. C2 adds only the missing framework-owned
difficulty producer/consumer contract identified by the first fresh child
critic. C3 corrects the one installer-ingestion contradiction found before live
execution: verified wheels are exposed through uv's documented local flat-index
boundary (`--no-index --find-links`) rather than by modifying uv's private
cache. C4 corrects the remaining tested-uv contradiction: `uv sync --frozen`
cannot consume that flat store (and rejects `--no-sources`), so framework
compiles the already admitted lock closure into a temporary fully pinned,
fully hashed requirements file and invokes fixed `uv venv` plus
`uv pip sync --require-hashes`. Candidate metadata is never passed to the pip
command. C5 closes the first full-scope C4 review: both commands run from a
fresh framework-owned directory, `uv venv --no-project` forbids project
discovery, `uv pip sync --allow-empty-requirements` preserves the stdlib-only
case, and one finite `AdmittedLockClosure` defines exact pre/post install set
equality while failing closed on marker/extra/fork ambiguity. This adds no
node, graph, downloader, index client, resolver service or control plane.

## 1. Product target and scope

The target is unchanged:

```text
arbitrary natural-language EnvironmentRequest
  -> evidence-grounded EnvironmentDesign
  -> executable Task Materializer + Runtime source closure
  -> real isolated Integration and independent Judge
  -> immutable Registry EnvironmentPackage
  -> safe read-only Observe
```

Direct is the required seed path. Expand is the separately budgeted library-
growth loop that evolves tool/world/task semantics from released packages and
real technical evidence. Training consumes exact released packages downstream;
it is not part of generation or release authority.

Revision 9 replaces revision 8. The current cleanroom is retained as the
implementation baseline, but its monolithic sequential composition is not the
target architecture. In particular, R9 corrects three observed handoff defects:

1. CandidateBuild currently reads Challenger output through
   `.foundry-challenge.json`, coupling Builder to verifier strategy.
2. Integration failure is persisted but does not stop Judge immediately.
3. Agent/LLM proposal, framework validation, Artifact commit and downstream
   routing are hidden inside large methods, so node contracts cannot be reviewed
   before implementation.
4. Curriculum names difficulty dimensions but does not define finite levels,
   leaving Materializer, Judge, package and Consumer without an admissible
   selection domain.

R9 adds a small domain graph kernel and explicit node contracts. It does not add
a generic workflow platform, YAML DSL, plugin registry, callback bus, general
scheduler, distributed queue, dynamic import system or compatibility layer.

## 2. System decomposition

Only two reusable generation graphs are needed:

```text
FoundryController.generate
  -> DesignGraph.run(DesignRequest)
  -> CandidateGraph.run(CandidateInput)
  -> DirectOutcome

ExpandCampaign
  -> freeze CampaignSnapshot
  -> Source / Policy / Operator
  -> DesignGraph.run(DesignRequest with admitted SemanticDelta)
  -> CandidateGraph.run(CandidateInput with verified parent lineage/source refs)
  -> CandidateOutcome
  -> Policy.tell / should_stop
```

`Observe` is a read model over durable graph/node/Artifact/Finding/release facts.
It is not a graph, router, retry mechanism or release authority. Consumption is
a separate downstream subsystem over exact Registry package refs.

### 2.1 DesignGraph

`DesignGraph` owns the conversion from a bounded design request into one
complete, compiled `EnvironmentDesign`. It is reused by Direct and Expand.

```text
DesignRequest
  -> research_plan
  -> research_acquire
  -> research_synthesis
  -> world_architecture
  -> shared_tool_semantics[group] (zero or more)
  -> tool_semantics[tool]          (one per frozen tool)
  -> world_rules
  -> curriculum_plan
  -> task_requirement[task]        (one per frozen task family)
  -> modeling_gate
  -> EnvironmentDesign
```

The variable node families are materialized by explicit bounded Python loops
after the preceding framework-owned plan is committed. V1 does not require a
dynamic scheduler: stable coordinates, a fixed maximum tool/task count and a
single deterministic execution order are sufficient. Parallel dispatch can be
added later without changing node contracts.

Direct supplies a request and empty parent/delta fields. Expand supplies exact
released parent semantic refs, admitted clue/evidence refs and a proposed typed
delta. Designer still reconstructs a complete child design; it never accepts a
source patch as environment evolution.

### 2.2 CandidateGraph

`CandidateGraph` accepts only a valid compiled Design and produces a complete
candidate outcome:

```text
                                  -> build_plan -> candidate_build -> integration --+
EnvironmentDesign ---------------+                                                   |
                                  -> verifier_intent ---------------------------------+-> judge
                                                                                          |
                                                               passed -> package -> registry
                                                               failed -> Finding / repair
```

The dependency details are binding:

- `build_plan` and `verifier_intent` are siblings after Design.
- `candidate_build` consumes Design + BuildPlan only. It never receives
  VerifierIntent, Verifier IR, sealed cases, Judge traces or release policy.
- `integration` starts as soon as CandidateBuild commits and does not wait for
  VerifierIntent.
- `judge` requires the exact passed IntegrationReport and compiled
  VerifierBundle for the same Design and Candidate revision.
- Package and Registry are unreachable after any required failed or
  inconclusive Judge claim.

`CandidateGraph` is origin-neutral. Direct passes empty parent source refs.
Expand may pass framework-verified read-only source closures from exact released
parent package digests, but only to CandidateBuild after child Design commit.

## 3. One Node abstraction, four execution kinds

A Node is one durable work/decision boundary, not a class hierarchy for every
role. Every Node executes the same transaction:

```text
resolve exact input ArtifactRefs
  -> prepare the minimum executor-facing projection
  -> run one proposal/execution operation
  -> framework validation / optional real assurance
  -> commit authoritative output Artifacts or emit one FeedbackEvaluation
```

Only the proposal/execution operation varies:

| Kind | Meaning |
| --- | --- |
| `FRAMEWORK` | deterministic framework code |
| `DIRECT_LLM` | prompt-only structured model call; no Skill, tools or workspace |
| `AGENT` | Codex Agent with exactly one mounted runtime Skill and explicit tools/workspace |
| `CANDIDATE_PROCESS` | untrusted generated Runtime process; the component owner still validates and commits |

Framework validation is always authoritative. A model/Agent response is a
proposal, even when validation and commit occur inside the same logical Node.
Raw proposal output is not exposed on graph edges. Split another graph node only
when an intermediate result has an independent consumer, repair owner or durable
readiness meaning; this prevents proposal/compile pairs from doubling every
node without product value.

The minimal static Python declaration is conceptually:

```text
NodeSpec:
  id
  purpose
  owner                         # Controller/Designer/Builder/Judge/Registry
  execution_kind                # FRAMEWORK/DIRECT_LLM/AGENT/CANDIDATE_PROCESS
  input_ports[]                 # typed ArtifactRef ports
  output_ports[]                # committed typed ArtifactRef ports
  model_contract?               # only DIRECT_LLM/AGENT
  validation_policy
  assurance_policy?
  local_feedback_policy

EdgeSpec:
  from_node.output_port
  -> to_node.input_port
  condition                     # success/finding/terminal predicate
```

The implementation uses one `NodeSpec`, one `EdgeSpec`, one small runner and
closed Python tuples per graph. There are no Node subclasses, handler plugins,
YAML graph definitions, callbacks or `SubgraphNode`. `FoundryController` and
`ExpandCampaign` call the two graphs as ordinary typed Python components.

## 4. Node-first design gate

No node executor may be implemented until its Node Contract Card is complete.
The card is part of design review, not post-failure remediation. It must state:

1. purpose and single framework owner;
2. exact graph input/output ports and Artifact revisions;
3. minimum LLM/Agent-visible input projection, distinct from graph input;
4. execution kind and resolved route;
5. Prompt objective, forbidden authority and closed output model;
6. Agent Skill, tools and workspace access, or explicit `none`;
7. framework validation, assurance and commit rule;
8. local correction feedback and cross-node repair input;
9. immediate and later consumers;
10. smallest deterministic check and smallest real-boundary proof.

The exact closed projections/output roots are binding in `node-contracts.md`.
An implementation note saying that a schema will be chosen later does not
satisfy this gate.

Changes to a model node's effective Prompt, input projection, output model,
runtime Skill bundle or profile-materialization code change its semantic
implementation revision. Transport-only fixes do not silently invalidate
semantic Artifacts.

## 5. Model, Prompt, Skill and feedback contracts

### 5.1 Prompt composition

Every model-facing node is designed from its purpose outward:

```text
authority and role
  + exact objective for this node
  + frozen minimum input projection
  + completeness/quality obligations
  + closed output shape
  + forbidden fields and downstream claims
  + optional authorized correction packet
```

Direct LLM prompts contain the complete semantic method and output protocol,
because Direct LLM nodes mount no Skill. Agent prompts contain only the current
Artifact coordinates, bounded task and authorized feedback; reusable method and
tool discipline live in the one mounted runtime Skill. Skill text is never
duplicated into the prompt.

Prompt bodies are ordinary versioned Python builders or small text assets. No
prompt templating framework is added. Prompt bodies, credentials and private
transcripts are not written to run Artifacts or Observe; only safe digests and
resolved route/model provenance are retained.

### 5.2 Runtime Skills

Development skills under `.agents/skills/` are not product runtime input. The
runtime owns exactly four explicit bundles, materialized read-only by the Codex
backend adapter:

| Agent work | Runtime Skill | Tools/workspace |
| --- | --- | --- |
| research | `research-world-evidence` | staged evidence + explicit Search/Fetch/Extract |
| build_plan | `engineer-build-planning` | read-only Design/Implementation projection |
| verifier_intent | `challenge-agent-world` | read-only Design/Task/public contract projection |
| candidate_build | `engineer-environment-codegen` | fresh writable candidate workspace; optional verified parent source roots read-only |

The bundles live outside `.agents/skills/` in a product-owned runtime resource
directory so development agents cannot be confused with generated-environment
agents. CandidateBuild receives no challenge/verifier file.

The Agent backend remains the cleanroom's thin official-Python-SDK adapter:
`AgentRoute(model, base_url, api_key_env)` -> ephemeral `AsyncCodex` thread ->
existing `InvocationResult/InvocationError`. It pins `openai-codex==0.144.4`,
uses `wire_api=responses`, disables SDK retries, selects the constant
`Sandbox.full_access`, materializes one temporary `CODEX_HOME` with one Skill
bundle and deletes it after session close. Primary/fallback route selection is
the only adapter recovery. There is no project permission manager, capability
matrix, configurable sandbox, profile inheritance, hook/MCP loader, worker
protocol or plugin DSL.

One real preflight turn proves the model-visible initial `Available skills`
surface is the exact singleton and can read a unique public marker contained
only in that bundle. Framework also verifies the physical bundle closure digest
before/after the turn, non-ambient `CODEX_HOME`, SDK close and cleanup. This is
an acceptance proof for the adapter, not a runtime node or access-control
subsystem.

### 5.3 Feedback classes

Two feedback paths are sufficient:

1. **Node-local correction**: proposal has not committed; exact inputs and scope
   are unchanged; framework returns `code + exact path + violated condition +
   expected category`. Default is one correction. A Direct node that explicitly
   declares two may use the second after a format-first rejection: either for
   another complete format replacement or for a newly parsed exact semantic
   issue. Semantic-first then format is a regression and remains terminal;
   proposal three is the hard ceiling. Other second corrections still require
   code-proven strict semantic progress and the global repair budget.
2. **Cross-node repair (bounded-repair child)**: a committed Artifact is
   contradicted downstream; current R9 persists the Finding and stops. The child
   will create a new target revision, invalidate only affected descendants and
   rerun the causal suffix.

Provider/transport retry is infrastructure handling, not semantic feedback.
Nodes do not maintain independent hidden retry counters. Current R9 has only
the per-node local correction limit; the child introduces one run/campaign
repair budget for cross-node corrections.

## 6. Binding node contracts

### 6.1 DesignGraph nodes

| Node | Graph input -> committed output | Model-visible input/output | Prompt, Skill and feedback |
| --- | --- | --- | --- |
| `research_plan` | `DesignRequestRef` -> `ResearchPlanRef` | need, allowed source policy, bounded parent/clue projection and unresolved dimensions -> bounded queries/source hints/questions | AGENT; `research-world-evidence`; cannot claim evidence, coverage, Design/code/Gate. |
| `research_acquire` | ResearchPlan/source policy/budget -> `SourceRecordRef[] + CitationCatalogRef` | none | FRAMEWORK Search/Fetch/Extract; real provider facts only; snippets alone are not evidence. |
| `research_synthesis` | request/plan/source/citation refs -> `EvidenceGraphRef + CoverageMapRef` | frozen one-based citation catalog -> citation-backed claims/conflicts/gaps | AGENT; `research-world-evidence`; framework maps indexes, validates provenance and computes coverage. |
| `world_architecture` | evidence/coverage/request refs -> `WorldArchitectureRef` | need, evidence claims, unresolved coverage -> boundary/entities/relations/tool-surface source draft | DIRECT_LLM; no Skill/tools/workspace. Prompt demands business meaning only; framework compiles IDs/schema/refs. |
| `shared_tool_semantics[group]` | architecture + coupling group + evidence -> `SharedToolSemanticsRef` | exact ordered tool IDs and shared-state summary -> atomicity/concurrency/idempotency/error-policy draft | DIRECT_LLM; one bounded group; exact group-coverage correction only. |
| `tool_semantics[tool]` | architecture + optional shared contract + evidence -> `ToolSemanticsRef` | one tool contract projection -> minimal complete pre/post/error/transition RuleDraft | DIRECT_LLM; one tool per call; no trajectories, schema mechanics, reward or Gate fields. |
| `world_rules` | architecture + all tool semantics -> `WorldRulesRef` | compact world/tool closure -> only additional cross-tool/entity invariant drafts | DIRECT_LLM; empty is valid when no additional rule exists; framework rejects tautologies/schema restatement. |
| `curriculum_plan` | compiled world closure + coverage -> `CurriculumPlanRef` | public capability dimensions -> ordered bounded task families/objectives plus 1..6 ordered difficulty dimensions, each with 2..5 ordered semantic levels | DIRECT_LLM; no fixed task IDs/seeds/reward/verifier cases. Framework validates names, finite domains and canonical order and commits one per-family `DifficultySchema`. |
| `task_requirement[task]` | world closure + one curriculum item including its frozen `DifficultySchema` -> `TaskRequirementRef` | one task family, allowed actor/tool scope and read-only difficulty meanings -> initial/success/failure/terminal RuleDraft | DIRECT_LLM; one task per call; cannot redefine difficulty. Feedback remains local to that task coordinate. |
| `modeling_gate` | all committed design refs -> `EnvironmentDesignRef` | none | FRAMEWORK; compiles WorldSpec, ToolContractSet, Task/Materializer protocol, Reward, VerificationRequirements and ImplementationContract; failure binds its Finding subject to the minimum contradicted design Artifact. |

### 6.2 CandidateGraph nodes

| Node | Graph input -> committed output | Model/process-visible input/output | Prompt, Skill and feedback |
| --- | --- | --- | --- |
| `build_plan` | `EnvironmentDesignRef` -> `BuildPlanRef` | minimum WorldSpec/Task/Implementation projection -> bounded implementation steps | AGENT read-only; `engineer-build-planning`; no candidate writes or validity claims. |
| `verifier_intent` | Design/Task/public evidence refs -> `VerifierBundleRef` | compact Rule/task/tool projection -> attack semantics, trace skeleton and property/metamorphic intent | AGENT read-only; `challenge-agent-world`; framework generates IDs, seeds, public/sealed partition and closed Verifier IR. It never sees candidate source. |
| `candidate_build` | Design + BuildPlan + origin/lineage + optional verified parent source refs -> `EnvironmentCandidateRef` | frozen implementation contract and plan; Direct R9 has no repair packet or parent roots -> candidate workspace + bounded completion statement | AGENT writable; `engineer-environment-codegen`; writes Task Materializer, Runtime and source only. Framework scans hashes/sizes/dependencies and commits Candidate. No VerifierIntent input. |
| `integration` | Design + Candidate -> `IntegrationReportRef` | untrusted Materializer/Runtime process protocol -> real clean-install/materialize/reset/invoke/idempotency/snapshot/restart/teardown evidence | FRAMEWORK + untrusted process. Failure stops before Judge/Registry and may create implementation or infrastructure Finding. |
| `judge` | Design + Candidate + passed Integration + VerifierBundle -> `JudgeReportRef + FindingRef[]` | fresh untrusted episodes and sealed/public verifier execution -> claim results and evidence | FRAMEWORK + untrusted process. Judge never receives graph topology and never emits target node, retry, invalidation or release action. |
| `package` | valid Design/Candidate/Integration/Judge/operation closure -> `ReleaseDossierRef + TelemetryReleaseSummaryRef + PackageRef` | none | FRAMEWORK; produces portable source closure with no secret/sealed/evaluator/workspace leakage and preserves unknown usage. |
| `registry` | Package + dossier + exact passed evidence -> `RegistryReceiptRef` | none | FRAMEWORK; atomically re-reads and publishes or returns an honest terminal non-release. |

`package` and `registry` use the exact portable closure and cold-read checks in
`node-contracts.md`; a baseline `manifest.json + runtime.py` zip cannot satisfy
either node.

Framework ownership is closed and singular: Designer owns every DesignGraph
node plus `verifier_intent`; Builder owns `build_plan`, `candidate_build` and
`integration`; Judge owns `judge`; Controller's ReleaseKernel owns `package`;
Registry owns only physical re-verification and atomic `registry` publication.
Registry may reject but cannot reinterpret Judge or become a second
ReleaseKernel. The exact machine-readable owner matrix and closed schema
subtypes are binding in `node-contracts.md`.

## 7. Edges, Findings and future routing

### 7.1 Forward edges

An Edge only selects committed output refs, maps them to named input ports and
applies a framework condition. It cannot call a model, compile business data,
read ambient state or mutate an Artifact.

Graph construction validates unique node IDs, known ports, type-compatible
Artifact kinds and acyclic forward dependencies. Runtime records the exact refs
used by each node revision.

### 7.2 Current R9: Judge and Finding only

Judge evaluates the candidate against exact contracts. Its framework-owned,
immutable Finding states what failed and binds `failed_claim_ref`,
`subject_ref`, evidence, expected condition, framework-derived owner domain and
blocking effect. It does not know or select graph nodes. The exact Finding
schema in `node-contracts.md` contains no target coordinate, retry, budget,
invalidation, jump or release action; Repair must reverify its owner evidence.

The current Direct task persists the Finding, marks downstream work `not_run`
and terminates honestly. It implements no `RepairRouter`, `RepairDecision`,
cross-graph rerun or `upstream_repair_required` state. This avoids dormant
control code that has not been proved.

### 7.3 Bounded-repair child contract

The dependent repair child introduces framework routing from the immutable
R9 provenance records. It will read and reverify only Finding owner/condition,
subject/evidence producer coordinates, dependency refs, closed graph-local
rules and one repair budget;
it will not read Prompt bodies, Skills, transcripts or every business schema.

Its target behavior is:

| Proven failure owner | Future decision |
| --- | --- |
| evidence/claim provenance | new minimum research revision |
| world/tool/task semantics | new minimum owning DesignGraph revision |
| verifier intent/IR | new `verifier_intent` revision |
| candidate source/protocol/behavior | new `candidate_build` revision |
| package/framework infrastructure | bounded same-boundary handling; never weaken Judge |
| permission/risk/unattributable ambiguity | `needs_human` |

CandidateGraph will return an upstream Finding to Controller rather than jump
directly into DesignGraph. Same-owner repair is at most two, one-hop semantic
parent repair at most one, and longer automatic backjumps are rejected. This is
a reviewed child contract, not a current implementation claim. No LLM Router
is planned.

## 8. Artifact and runtime boundaries

All graph edges carry typed `ArtifactRef`s or a framework-owned ephemeral
workspace handle that cannot be persisted or exposed. Durable outputs remain
content-addressed and immutable. `ArtifactEnvelope` and terminal `WorkRecord`
from `node-contracts.md` bind producer graph/node/shard/revision, semantic
revision digest, exact ordered dependency/input/output refs, validation,
assurance, Findings and terminal status. `DirectRun` contains ordered
WorkRecord refs; coarse stage strings are not provenance authority.

The generated environment contract is:

```text
DifficultySchema (framework compiled per task family):
  ordered dimensions -> ordered finite levels
  every dimension required exactly once

Task Materializer:
  materialize(seed, task_type, actor, difficulty)
    -> exact echoes + public_goal + initial_config

Runtime:
  handshake
  reset(seed, actor, initial_config)
  invoke(tool_id, arguments, idempotency_key)
  snapshot                 # framework/Judge/Consumer private
  close
```

Candidate code never computes reward, termination, hashes, manifests, Judge
results or release status. Framework executes candidate code out of process and
never imports it into Foundry/Judge. The complete trusted
`TaskRequirement -> MaterializerResult -> PublicTask + EvaluatorGoalBinding ->
Runtime/Judge` flow and closed schemas are defined in `node-contracts.md`.
The difficulty selection is a closed ordered `mapping[str, str]`: key order is
the frozen dimension declaration order and each value is one declared level.
Framework rejects missing, extra, duplicate, reordered or unknown values before
candidate execution or release. Candidate code exact-echoes it and owns no
difficulty semantics.

## 9. Expand, Observe and training boundaries

### 9.1 ExpandCampaign

Expand remains an outer bounded state machine, not a third generic DAG:

```text
CampaignRequest
  -> immutable parent/source/direction/operator/budget snapshot
  -> real ExpansionSource research
  -> Policy.ask
  -> framework admission + typed operator
  -> DesignGraph
  -> CandidateGraph x N
  -> CandidateOutcome batch
  -> Policy.tell / should_stop
```

The stable policy interface is only `ask`, `tell` and `should_stop`. Multiple
parents mean exact released parent package/source refs, not multiple policy
rules. Builder may reuse parent code only after complete child Design commit and
always writes one fresh self-contained child. Every child earns a new Judge and
Registry result.

An Expand semantic delta may change task or difficulty meaning only by causing
Designer to produce a complete new Curriculum/TaskRequirement revision through
DesignGraph. The child package then carries its own compiled
`DifficultySchema`; no parent selection domain is silently unioned or inherited.

### 9.2 Observe

Observe projects safe L0 run/campaign, L1 graph, L2 node/revision and L3
Artifact/Finding evidence facts. It stores no prompt, credential, sealed case,
raw candidate source, private workspace path or evaluator goal, and it cannot
retry, route, judge or publish.

### 9.3 Consumption

Training depends one-way on exact Registry packages through a framework-owned
Episode service. SFT and RL see only PublicTask, observation, tool schema/action,
public result/error, reward and termination. Optional aggregate capability
feedback may prioritize Expand but is never Design evidence or a release Gate.
Consumer validates difficulty against the exact task-family schema carried by
the selected package. It does not define a Consumer-only difficulty schema.

## 10. Minimal implementation shape and anti-overdesign budget

The cleanroom keeps its existing `artifacts.py`, `invocation.py`, `runtime.py`,
`config.py`, `observe.py` and CLI boundaries. R9 adds or extracts only:

```text
agent_world/graph.py       # NodeSpec, EdgeSpec, two static graphs, small runner
agent_world/design.py      # DesignGraph node handlers and prompt builders
agent_world/candidate.py   # CandidateGraph node handlers
agent_world/runtime_skills/<four bundles>
agent_world/foundry.py     # thin Controller composition
```

These may be combined when shorter. The graph kernel is a domain helper, not a
framework product. Review must block any implementation that introduces node
subclasses, dynamic plugins/imports, YAML graph DSL, callback/event bus, generic
distributed scheduling, automatic source merge, compatibility adapters or a
second Artifact/repair/release authority. New graph/control code should replace
equivalent monolithic orchestration rather than accumulate beside it.

## 11. Parent-owned delivery sequence

The complete sequence and final acceptance are owned by
`08-11-foundry-complete-v1`; this task is only its first implementation child.

1. **R9 Direct foundation (this child)**: static Node/Edge contracts, Design
   and Candidate graph composition, corrected Builder/Verifier separation,
   canonical Materializer/Runtime, Integration fail-stop, package evidence,
   safe Observe and one fresh real Direct release.
2. **Bounded repair sibling**: `08-11-foundry-bounded-repair`.
3. **Expand sibling**: `08-11-foundry-expand-multiparent`, including both a
   single-parent proof and useful real multi-parent composition.
4. **Consumption sibling**: `08-11-foundry-consumer-sft-rl`.

Each slice has an honest E2E and explicit non-claims. A green graph test, model
JSON response or package-shaped file is never substituted for the required real
boundary proof.
