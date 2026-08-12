# Independent whole-diff check — Direct R2 ToolSemantics and Observe closure

Date: 2026-08-11  
Worktree: `/home/kelong/pycodes/foundry-direct-graph`  
Scope: read-only review of the current whole diff after ToolSemantics R2 and the
Observe evidence addendum. No model, Agent SDK, network, candidate E2E, or
Registry proof was invoked.

## Decision

**Decision: block.**

The product target remains: an arbitrary natural-language need must become an
evidence-grounded executable candidate, pass isolated Integration and an
independent Judge, become an immutable Registry package, and be projected only
through safe read-only Observe. A static graph, a passing deterministic suite,
or a package-shaped archive is not product completion.

The R2 local ToolSemantics path and the Observe addendum are internally closed
at their intended narrow boundary. The whole diff nevertheless does not
implement the binding DesignGraph semantic contracts: in particular,
`shared_tool_semantics` is a model call that accepts an untyped payload and its
contents have no compiled/package consumer. This is a semantic producer /
consumer gap, not a mechanical repair permitted to this audit. The full mypy
gate also fails when tests are included.

The current check context includes the matching R2 allow
`cross-layer-review-c69de83b-tool-semantics-r2.md` (digest
`c69de83b54e3f849e39653b8227b3772314411fe5dc2141abb3d558eaa1c7a26`) and
the matching Observe allow `cross-layer-review-3efaf683-observe-evidence-r1.md`
(digest `3efaf683de4f09a2fd6934aa30476daf2322f7e5c2780cd81fa2375c07f3a2cf`).
Their exact R2 and one-site Observe scopes are respected by the corresponding
closure code. They do not authorize treating the broader node-contract drift
below as complete.

## Actual node execution and consumer map

| Node family | Actual executor and model/Agent-visible projection | Closed output / persisted artifact | Actual downstream consumer |
| --- | --- | --- | --- |
| `research_plan` | Agent, singleton `research-world-evidence`; `request.json` carries only `need`; prompt requests 1–3 queries. | Framework validates bounded queries; `design.research_plan` envelope and WorkRecord. | `research_acquire`, `research_synthesis`. |
| `research_acquire` | Framework HTTP search/fetch/extract; no model projection. | Source commitments/citation catalog only; source text stays in memory. | `research_synthesis`. |
| `research_synthesis` | Agent, singleton `research-world-evidence`; staged `evidence.json` holds request/source text. | Framework compiles claims and source refs into `design.evidence_graph`. | architecture, ToolSemantics, Modeling Gate. |
| `world_architecture` | Direct LLM; prompt has need and evidence; no Skill, tools, or workspace. | Compiler accepts only `name`, `summary`, and simple tool names/descriptions/argument/result-field strings. | shared-tools, tool semantics, world rules, curriculum, task, Modeling Gate. |
| `shared_tool_semantics` | Direct LLM; projection is only `tools`; no Skill, tools, or workspace. | Only top-level `{"groups": list}` is checked and committed. | Passed verbatim only to each ToolSemantics prompt. It is not compiled into `ToolDraft`, `DesignContract`, Rule IR, CandidateBuild input, Judge, package, Registry cold read, or Observe. |
| `tool_semantics[tool]` | Direct LLM; frozen tool index/surface, framework bindings, the uncompiled shared payload, claims, and citation catalog; no Skill/tools/workspace. | Closed local `RuleDraft` sections compile to `ToolDraft` with framework bindings and digest. | world rules/task/modeling; Builder design/implementation projections; Integration/Judge evaluator; package Rule IR/cold read. |
| `world_rules` | Direct LLM; architecture + local ToolDrafts; no Skill/tools/workspace. | Bounded strings in `invariants`, committed as `design.world_rules`. | curriculum, task, Modeling Gate, package Rule IR. |
| `curriculum_plan` | Direct LLM; architecture + invariant strings; no Skill/tools/workspace. | One task family and one `DifficultySchema`, committed as `design.curriculum_plan`. | task requirement and Modeling Gate. |
| `task_requirement[task]` | Direct LLM; architecture/tools/rules/curriculum; no Skill/tools/workspace. | One actor/goal/simple public scenario, committed as `design.task_requirement`. | Modeling Gate, materializer/runtime configuration. |
| `modeling_gate` | Framework only. | `EnvironmentDesign` plus selected `LocalRuleAssurancePlan`. | CandidateGraph and package provenance. |
| `build_plan` | Agent, singleton `engineer-build-planning`, read-only design/implementation files. | Framework-validates `BuildPlanDraft`, commits `candidate.build_plan`. | CandidateBuild only. |
| `verifier_intent` | Agent, singleton `challenge-agent-world`, read-only public design. | Framework compiles public commitments; private cases stay in memory. | Judge and release closure, never CandidateBuild. |
| `candidate_build` | Agent, singleton `engineer-environment-codegen`, writable candidate root containing only design, implementation contract, and build plan. | Framework scans physical source closure and commits candidate manifest. | Integration, Judge, Package, Registry. |
| `integration` | Framework supervisor plus untrusted candidate process. | Exact passed Integration report and admitted-lock closure, or a Finding/terminal failure. | Judge, Package, Registry. |
| `judge` | Framework plus fresh untrusted candidate process; no Agent/LLM routing. | Gate evidence, Judge report, and route-free Finding on failure. | Package and Registry only on passed gates. |
| `package` | Framework ReleaseKernel. | Release dossier, telemetry, physical package and package envelope. | Registry cold read. |
| `registry` | Registry framework only. | Cold-read verification, atomic package/receipt, released `EnvironmentPackageRef`. | Direct run and Observe. |
| `Observe` | Framework read-only projection; no model/Agent/candidate execution. | No artifacts are written. | User-facing safe work/finding/release scene only. |

Direct nodes are correctly declared `direct_llm` with `skill=None` and
`route="direct"` in `agent_world/graph.py`; the adapter sends only system/user
messages. Agent nodes declare exactly one named runtime Skill and the Codex
adapter constructs a disposable `CODEX_HOME` containing only that Skill before
starting an ephemeral `AsyncCodex` session. Candidate runtime runs through the
process supervisor. Judge does not route or release, and Observe only cold
reads durable facts.

## R2 and Observe closure evidence

- ToolSemantics receives evidence, frozen one-based bindings and citation
  indexes (`agent_world/design.py:1355-1379`), compiles local RuleDrafts, and
  Modeling Gate derives a deterministic local-rule assurance plan.
- CandidateBuild receives the compiled Design/implementation contract; it has
  neither verifier material nor a sealed/Judge input. Integration and Judge
  call distinct candidate-process traces. The package Rule IR carries the
  compiled tool rules and local assurance (`agent_world/candidate.py:1939-1960`);
  Registry cold verification rechecks that closure.
- The Observe addendum now reads every Judge gate evidence and performs exact
  conditional equality: only `local_tool_semantics` must contain the exact
  Design-derived `local_rule_assurance` (`agent_world/observe.py:257-270`).
  Its four negative evidence cases pass, so missing, altered, misplaced, and
  extra evidence fail closed.
- Private snapshot values, sealed cases, evaluator values, prompt bodies, and
  credentials are excluded from ArtifactStore payloads and Observe projections
  by the safety boundary. Release authority remains the framework Package node
  plus Registry publication; no second release owner was introduced.
- The legacy firewall passes and a repository search found no implementation of
  old awm CLI, StateGraph/replay/ABI-v1 compatibility, generic scheduler,
  Repair, Expand, Consumer, SFT, or RL paths. The two fixed Python graph
  declarations and one runner remain the only graph mechanism.

## Findings (fixed)

- None. This dispatch is an audit and was explicitly limited to the report
  artifact; no product, test, configuration, plan, JSONL, Skill, spec, or
  workflow file was edited.

## Findings (not fixed)

- File: `agent_world/design.py:1014-1046`, `agent_world/design.py:1355-1379`, `agent_world/candidate.py:1931-1960`
  - Issue: The binding `node-contracts.md` requires
    `shared_tool_semantics[group]` to receive ordered group indexes,
    shared-state summary, and citations; produce closed
    atomicity/concurrency/idempotency/ordering/compensation plus error-policy
    semantics; and have framework-validated group coverage. The implementation
    always materializes one unsharded node, supplies only simple tools, accepts
    arbitrary list contents under `groups`, and gives the model the misleading
    literal shape `{"groups":[]}`. Its produced contents are only forwarded to
    a later prompt and are absent from the compiled ToolDraft/Design, Rule IR,
    package, Registry cold read, and Observe. This also means the purported
    shared semantics have neither an executable consumer nor a durable future
    Expand handoff.
  - Why not fixed: Correcting this changes DesignGraph node cardinality,
    model-visible projection, output/compiler contract, semantic identity, and
    package consumers. It requires a revised plan and fresh cross-layer critic
    review; it is outside both current R2 and Observe `allow` scopes.
  - Minimal actionable feedback: Decide and plan one coherent contract: either
    implement the existing declared per-group shared semantics and carry their
    compiled form through Design/Rule IR/package/cold read, or remove the node
    and every port/edge/contract assertion if shared semantics are intentionally
    deferred. Do not retain a model-produced unvalidated/discarded `groups`
    payload. Add a regression proving the selected policy, including the
    no-multi-tool-group case.

- File: `agent_world/design.py:930-1813`, `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:310-495`
  - Issue: The same whole-diff comparison exposes broader binding-card drift:
    WorldArchitecture is a simple tool surface rather than the declared
    boundary/entity/field contract; WorldRules emits strings rather than
    RuleDraft IR; Curriculum and TaskRequirement each collapse the declared
    bounded multi-family/sharded semantic contracts to one simple scenario.
    These model validators and compiled outputs therefore do not match the
    model-visible contracts that the task calls binding.
  - Why not fixed: This is a behavioral product-contract decision, not a lint
    repair. A change must first reconcile the active task contracts with the
    canonical product document and get a revised plan/critic allow. It should
    not be smuggled into the R2 local-rule repair.

- File: `tests/test_supply_chain.py:281-283`, `tests/test_direct_runtime.py:168,541`, `tests/test_graph_contracts.py:215,352`, `tests/test_direct_release.py:462`
  - Issue: `uv run mypy agent_world tests` fails with eight errors in newly
    modified/added test annotations and monkeypatched subprocess wrappers.
  - Why not fixed: The requested audit prohibits test edits. These are
    mechanical type-check repairs, but they must be made by the authorized
    implementation turn and rechecked. `uv run mypy agent_world` itself passes.

## Verification

- Pytest (offline; `-m 'not live'`): pass — 131 passed.
- Ruff format: pass — 21 files already formatted.
- Ruff check: pass.
- Mypy: fail for `uv run mypy agent_world tests` — 8 test-file errors; source
  package alone passes (13 files).
- CompileAll: pass.
- Diff check: pass (`git diff --check`; no staged diff errors).
- Legacy firewall: pass — 2 passed.

No real model, Agent SDK, network, Candidate E2E, Registry proof, or external
state mutation was performed by this audit.
