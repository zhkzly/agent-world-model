# Research: Context engineering for the Direct Foundry graph

- Query: Research context composition, selection, ordering, isolation, progressive disclosure, compaction, caching, dynamic observations, context rot/noise, and context lifecycle across graph nodes; apply the evidence to the project’s Direct LLM, Codex Agent, framework, candidate-process, and `EnvironmentRequest -> verified EnvironmentPackage` boundaries.
- Scope: mixed (project source/specification plus external primary papers and official engineering documentation)
- Date: 2026-08-12

## Executive result

The smallest sound design is **not** a general memory, RAG, workflow, or context-runtime product. The two fixed graphs should treat every model/Agent call as a fresh, purpose-built context transaction:

```text
immutable ArtifactRefs + node contract
  -> minimum node-specific rendered projection / staged workspace
  -> one Direct LLM or one isolated Codex Agent turn
  -> framework validation and real assurance where required
  -> committed safe Artifact(s) + WorkRecord
  -> discard raw proposal, transient tool output, and session state
```

This is already the dominant shape of the cleanroom. It is the right response to long-context noise, positional sensitivity, and authority leakage. The one material Direct-foundation gap exposed by the code is that Research Synthesis currently stages the first 10,000 characters of up to six fetched sources without an explicit per-node token budget, relevance/coverage selection rule, source-order rule, or an explicit “retrieved text is data, never instructions” boundary. That needs a small, typed context-selection contract before a live proof relies on arbitrarily long or adversarial technical material.

Do **not** add cross-node chat history, a vector database, a generic summarizer, a memory hierarchy, a context broker, or a provider-session continuation policy in this child. Those address longer-horizon repair/Evolve work only after a real need is observed. The durable Artifact DAG is the canonical long-term memory; any future compact note is a non-authoritative retrieval aid that must point back to immutable Artifacts and never replace their evidence or release meaning.

## Evidence grading

- **Project fact** means a current source/specification or code observation, cited as `path:line`.
- **External evidence** means a primary paper, a technical report from its authors, or official engineering documentation.
- **Inference** is a design conclusion drawn from those facts; it is explicitly labelled and is not a claim that the current code already has the proposed behavior.

## Files found

| File | Description |
| --- | --- |
| `docs/agent-world-environment-generation.zh.md` | Source-of-truth product contract: immutable Artifact DAG, framework authority, Agent roles, candidate isolation, Judge, Registry, and consumer boundaries. |
| `docs/direct-rewrite-execution-map.zh.md` | Derived implementation map separating components, logical Work, Direct LLM, tool-enabled Codex Agent, framework, and candidate process. |
| `.trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md` | This child’s product requirements, static two-graph scope, node contracts, and explicit non-goals. |
| `.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md` | R9 node-first design, graph ports, Prompt/Skill split, runtime Skills, and anti-overdesign budget. |
| `.trellis/spec/agent_world/backend/index.md` | Backend constraints for artifact reads, Direct-vs-Agent context, causal dependencies vs disclosure, and bounded correction. |
| `.trellis/spec/guides/agent-llm-node-debugging.md` | Separates project-execution Agent context from Direct/Agent runtime context and requires evidence-led diagnosis. |
| `agent_world/graph.py` | Fixed `NodeSpec`/`EdgeSpec`, per-node transactions, committed envelopes, bounded local correction, and semantic revision identity. |
| `agent_world/design.py` | Direct LLM prompt composition, Researcher staging, evidence synthesis, and node-specific projections. |
| `agent_world/candidate.py` | Build-plan/CandidateBuild/Integration/Verifier/Judge handoffs and CandidateBuild’s deliberately restricted inputs. |
| `agent_world/invocation.py` | Direct chat boundary plus the disposable Codex SDK session, one mounted Runtime Skill, and cleanup behavior. |
| `agent_world/artifacts.py` | Content-addressed safe persistence, cold reads, and prompt/transcript/sealed-value exclusion. |
| `agent_world/contracts.py` | Safe `CorrectionPacket`, operation evidence, provenance envelopes, WorkRecord, and verifier commitment contracts. |
| `agent_world/observe.py` | Read-only projection of persisted WorkRecords and Findings. |
| `agent_world/runtime_skills/*/SKILL.md` | The four product-owned, role-specific Agent methods and their allowed inputs/authority exclusions. |

## Project facts: the existing context model is mostly the intended one

### 1. Context is separate from graph causality and from authority

**Project fact.** A graph edge validates a committed producer/port and resolves exact ArtifactRefs; it does not itself make the artifact payload model-visible. `GraphRunner._resolve_inputs` verifies only the declared graph ports and provenance (`agent_world/graph.py:597-666`). Direct model calls use manually constructed projections rather than blindly serializing all graph inputs (`agent_world/design.py:599-642`); CandidateBuild receives only `design.json`, `implementation-contract.json`, and `build-plan.json` (`agent_world/candidate.py:848-904`).

**Project fact.** The source-of-truth requires “dependency = causal invalidation; input slot = minimum disclosure” and treats release evidence as a typed closure, not a stage name. The execution map says raw model output never crosses an Edge and that a Node commits only after framework validation.

**Inference.** This is the key context-engineering primitive for Foundry: **causal dependency, model visibility, physical capability, and release authority must remain four separately declared relations.** An upstream Artifact can be necessary to invalidate a downstream result but still be inappropriate to disclose to the model. This prevents both noise and privilege escalation.

### 2. Direct LLM and Codex Agent have intentionally different context composition

**Project fact.** Direct calls use a small static system message that explicitly denies tools, Skills, workspace, and release authority; the user payload carries `node`, a node projection, an output shape, and only an authorized correction packet (`agent_world/design.py:561-587`). The graph forbids a Skill on a `direct_llm` node and fixes Direct nodes to the Direct route (`agent_world/graph.py:35-80`).

**Project fact.** A Codex Agent call gets a fresh `CODEX_HOME`, exactly one copied product Runtime Skill, one workspace, a bounded instruction, and a disposable SDK session. The adapter checks the skill bundle before/after the turn and deletes the temporary home after session close (`agent_world/invocation.py:166-310`). Runtime Skills state the reusable method; the short prompt names the current files/task. For example, the Researcher Skill permits only staged evidence and citation data (`agent_world/runtime_skills/research-world-evidence/SKILL.md:6-28`), while CandidateBuild is constrained to its source closure and exact runtime/materializer contract (`agent_world/runtime_skills/engineer-environment-codegen/SKILL.md:6-30`).

**External evidence.** OpenAI’s current model guidance recommends lean prompts, stating each instruction once, exposing only relevant tools, and monitoring context as a run grows; it also distinguishes stable prompt caching from task-specific context and advises validation on representative tasks. [OpenAI Model guidance](https://developers.openai.com/api/docs/guides/latest-model). Anthropic’s engineering guidance independently recommends the smallest information set sufficient for the desired behavior, a minimal viable tool set, and purpose-specific tool contracts. [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

**Inference.** Keep the current split:

- **Direct LLM:** static authority/objective + complete node-specific semantic projection + closed output shape + bounded correction. No Skill, tool catalog, workspace, or prior chat transcript.
- **Codex Agent:** static adapter guardrail + exactly one role Skill + current task coordinates/files + explicit tool/workspace surface + bounded correction. Do not duplicate the Skill’s method in the prompt.
- **Framework:** no natural-language “context” can give it away its gate, route, budget, manifest, or release authority; it computes those from typed facts.
- **Candidate process:** receives only a protocol call and a framework-selected task instance; it never receives evaluator/Judge/release context.

The important test is not a character-count assertion. It is that the actual model-visible surface matches this table and that excluded authority remains inaccessible through payload, workspace, tool, Skill, or later Artifact.

### 3. Fresh contexts already serve as safe per-node compaction

**Project fact.** `GraphRunner.execute` creates a transaction around one proposal/process operation, optional local correction, compiler/validator, immutable output envelope, and terminal WorkRecord (`agent_world/graph.py:462-595`). It retains a semantic-revision hash of the effective projection/prompt identity/route/Skill digest, not a raw prompt or transcript (`agent_world/graph.py:442-459`). The Artifact store rejects prompt-, transcript-, sealed-, evaluator-, credential-, and raw-provider-like fields (`agent_world/artifacts.py:15-42`, `277-309`, `405-425`).

**External evidence.** Anthropic defines compaction as distilling an old context before beginning a fresh window; it recommends preserving decisions and unresolved work while discarding redundant raw tool output. It also describes isolated specialized subagents returning compact distilled results rather than exposing their full exploration state. [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). [MemGPT](https://arxiv.org/abs/2310.08560) supplies an original-paper example of hierarchy/paging for situations that genuinely need a larger virtual context.

**Inference.** The Artifact boundary is Foundry’s first and safest form of compaction:

1. raw proposal and raw tool observations are working memory only;
2. deterministic validation converts only accepted, safe, typed meaning into a durable Artifact;
3. the next node reconstructs a much smaller, purpose-specific view from Artifacts; and
4. the old session is discarded.

Do not summarize a `WorldSpec`, passed Integration, JudgeReport, or release evidence into prose and then treat the prose as authority. A future summary may carry `ArtifactRef`s, digests, unresolved issue IDs, policy/contract revisions, and selected safe facts, but canonical semantics remain in the original immutable Artifacts.

### 4. Current branch separation is a useful noise and leakage control

**Project fact.** CandidateBuild’s ports are only `design` and `build_plan`; `verifier_intent` is a sibling and joins only at Judge (`agent_world/graph.py:216-300`). The Candidate executor runs BuildPlan -> CandidateBuild -> Integration before it makes the verifier bundle, and an integration failure records downstream `not_run` work rather than running Judge/Registry (`agent_world/candidate.py:554-625`, `955-1020`). The verifier Agent gets a public catalog only, and framework-generated private cases are not persisted to ArtifactStore (`agent_world/candidate.py:1022-1228`; `agent_world/contracts.py:1104-1115`).

**External evidence.** Indirect prompt injection research demonstrates that retrieved data can blur data/instruction boundaries and alter tool/API behavior in real systems. [Greshake et al., *Not what you’ve signed up for*](https://arxiv.org/abs/2302.12173). This is a direct reason not to pass verifier, sealed, or release material through a broadly capable code-generation context merely because it is causally related.

**Inference.** CandidateBuild’s absence of verifier context is not just a security rule; it is a context-quality rule. It removes a tempting target, prevents accidental verifier overfitting, reduces unrelated tokens, and maintains an independent Judge. Likewise, a malformed verifier must not erase already committed Build/Integration evidence, but it must block the release join.

### 5. Context isolation here is logical/provenance isolation, not an OS security claim

**Project fact.** The Codex adapter deliberately uses `Sandbox.full_access`; the `writable` flag is discarded and workspace access remains a product convention at the adapter boundary (`agent_world/invocation.py:211-253`, `283-304`). The canonical documentation likewise calls for a small adapter rather than a new permission/capability system. Candidate Runtime is separately executed and framework does not import candidate code; that is a real process boundary, not an LLM/Agent boundary.

**Inference.** Never claim that “read-only Agent” or “CandidateBuild cannot see X” is enforced by the Codex OS sandbox in this child. It is currently enforced by:

- what files/projections are deliberately staged;
- what gets passed as the Agent’s cwd/prompt/Skill;
- framework revalidation and source scanning;
- private data never being written to normal Artifact paths; and
- process isolation for the untrusted runtime.

That is enough for the stated minimal route only if product claims are worded as **context and authority isolation**, not hostile-host containment. A stronger filesystem/namespace isolation design would be a separate, evidence-led security scope and is explicitly outside this child’s minimal adapter budget.

## External evidence by topic

### Composition, selection, and ordering

- [Liu et al., *Lost in the Middle*](https://arxiv.org/abs/2307.03172) finds a U-shaped position effect: relevant content at the beginning or end of long contexts is used more reliably than relevant content in the middle. It also finds that adding retrieved documents can saturate benefit long before recall saturates. This supports selection before injection and deterministic placement of the task/authority contract and output protocol. It does **not** justify mechanically duplicating every fact at both ends; the paper’s query repetition improvement on synthetic retrieval did not remove the broader multi-document QA pattern.
- [Hong, Troynikov, and Huber, *Context Rot*](https://www.trychroma.com/research/context-rot) reports across 18 models that performance becomes less reliable as input length grows, that distractors become more harmful as length grows, and that haystack structure matters. Treat this as a useful technical report and stress-test source, not as a model-independent law or a quantitative prediction for the configured providers.
- [Xu, Shi, and Choi, *RECOMP*](https://arxiv.org/abs/2310.04408) shows task-conditioned compression and **selective augmentation**: an irrelevant retrieval can yield an empty augmentation rather than adding noise. This supports an explicit “omit if irrelevant / coverage already satisfied” option for a model-facing projection.
- [Jiang et al., *LLMLingua*](https://arxiv.org/abs/2310.05736) finds that compression requires a budget and preservation of semantic dependencies; token deletion is not a safe generic substitute for selection. It is evidence for preserving typed/citation structure, not a reason to adopt a token-compression model in this child.

### Progressive disclosure and dynamic observations

- Anthropic’s official guidance describes a just-in-time model: provide lightweight identifiers up front, then use targeted retrieval to load data incrementally; this avoids loading full corpora and lets the Agent build understanding layer by layer. [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- [LongMemEval](https://arxiv.org/abs/2410.10813) distinguishes indexing, retrieval, and reading. It finds that long histories can degrade even with strong long-context models, and that value granularity, keying, retrieval, and reading order are distinct design choices. This supports the project’s explicit Artifact index/refs and node-specific projections rather than “the whole run so far.” Its multi-session chat setting is not the same as Foundry’s short node transactions.
- The same official guidance cautions that just-in-time exploration requires thoughtful tools and can waste context if the agent chases dead ends. Therefore, Foundry should have framework-set source caps, explicit stop conditions, and only the Researcher gets raw technical material.

### Lifecycle and long-horizon memory

- [MemGPT](https://arxiv.org/abs/2310.08560) demonstrates a viable virtual-memory approach for document analysis and multi-session chat. It is useful evidence that memory tiers can work when a single agent must retain a very long evolving narrative.
- **Inference:** Foundry does not presently have that problem inside an individual Direct node. Its durable unit is a typed Artifact rather than a chat turn. Therefore MemGPT-style paging/memory management is a later option for long-lived Evolve/repair orchestration, not a Direct graph requirement.

### Context isolation and untrusted content

- [Greshake et al.](https://arxiv.org/abs/2302.12173) shows indirect instructions embedded in retrieved data can manipulate LLM-integrated systems. It supports a hard rule: fetched text, candidate output, and runtime observations are **data**, never authority or instructions.
- This project’s type/provenance boundary gives a better-than-prompt-only defense: raw external content is not eligible to become a Gate, Finding, manifest, route, or release fact; framework compilers and real execution must produce those facts. That is project evidence, not a claim that injection is solved.

### Caching

- OpenAI’s model guidance distinguishes explicit/implicit prompt caching from semantic workflow reuse and advises tracking cached tokens and cache-write costs. [OpenAI Model guidance](https://developers.openai.com/api/docs/guides/latest-model).
- The backend spec requires Artifact verification memoization only within one public read/call graph, with a new cold read/re-hash for later reads; global verified-content caching would mask post-read tampering (`.trellis/spec/agent_world/backend/index.md:45-84`).
- **Inference:** cache only a stable, non-secret prefix at a provider when it is objectively useful; it is a transport/cost optimization, not evidence or semantic reuse. Cache a passed Artifact only when its acceptance identity—including exact inputs, projection/prompt/Skill identity, output contract, validator, and assurance—is unchanged. Never cache raw Agent conversation state or verified Artifact content globally across later integrity reads.

## Context lifecycle required by the two fixed graphs

The following is a design interpretation of the current graph; it is not a request to add another graph node.

| Lifecycle phase | Direct LLM | Codex Agent | Framework | Candidate process |
| --- | --- | --- | --- | --- |
| **Admit** | Receives a node-specific safe projection only. | Receives current workspace files, one Runtime Skill, and task instruction only. | Resolves ports, ArtifactRefs, route, budgets, and output contract. | Receives a framework-selected protocol request only. |
| **Observe / explore** | None; no tools or workspace. | May inspect only staged/authorized data through the mounted Skill and available tools. | Acquires sources, scans source tree, runs validator/assurance, and records safe facts. | Produces protocol results; it does not interpret Judge/release state. |
| **Propose / execute** | Returns closed structured semantic draft. | Returns bounded advisory/completion draft and may write only the candidate closure in CandidateBuild. | Performs deterministic compilation, policy, Gate, lineage, package, and release work. | Executes materialization/runtime state transitions out of process. |
| **Commit** | Proposal becomes durable only after framework validation. | Same. Skill/prompt/output identity is committed as a digest, not as raw text. | Writes ArtifactEnvelope/WorkRecord/Finding/registry facts. | Never writes Foundry control facts. |
| **Handoff** | Next node sees a new minimum projection of committed Artifacts. | Same; another Agent does not inherit a hidden chat transcript. | Maps Artifacts to exact ports and release evidence. | Judge sees only its allowed public/private protocol inputs. |
| **Discard / retain** | Discard provider conversation and raw response after compilation; retain safe operation evidence. | Close SDK session, delete temporary `CODEX_HOME`, delete temporary read-only workspace where appropriate. | Retain safe immutable Artifacts and read-only Observe projection. | Tear down process/episode; retain framework-produced evidence only. |

### Branch-specific lifecycle observations

1. **Research.** `research_acquire` records URL/content commitment and keeps a truncated text only in its returned in-memory tuple; the persisted artifact projection deliberately contains source/citation commitments rather than raw documents (`agent_world/design.py:727-806`). `research_synthesis` stages raw source text in a temporary workspace and returns citation-backed claims/conflicts/gaps (`agent_world/design.py:808-944`; Runtime Skill lines 18-28). This is mostly right, but selection needs an explicit contract (below).
2. **Semantic Direct design.** The Direct nodes work from compact typed values and frozen one-based citation/catalog indexes. Their projections are materially narrower than their graph dependencies: e.g. architecture gets need + claims/conflicts/gaps + citation catalog (`agent_world/design.py:1226-1243`), and each task shard gets one family’s tools/schema/rules/catalog (`agent_world/design.py:1938-1964`). This is progressive disclosure already.
3. **Build.** BuildPlan sees an advisory projection and contract; CandidateBuild sees Design + BuildPlan and not verifier data. CandidateBuild deletes its `inputs/` staging directory before scanning the candidate closure (`agent_world/candidate.py:881-907`), preventing input artifacts from leaking into a release source tree.
4. **Integration/Judge.** Integration turns an untrusted execution into a passed/failed normalized report and fail-stops Judge/Registry on failure (`agent_world/candidate.py:955-1020`). Verifier commitments are persisted but private cases stay transient (`agent_world/candidate.py:1156-1228`). Judge joins exact passed Integration with verifier evidence; Package/Registry cold-read their closure.
5. **Observe.** Observe projects persisted WorkRecords/Findings and expressly does not create/change state (`agent_world/observe.py:381-445`, `498-536`). It must never be reintroduced as a model-facing “history” channel.

## Concrete minimal design implications

### Must be explicit now (small, node-local, and testable)

| Need | Minimum implementation/design implication | Why it is required now | Do not turn it into |
| --- | --- | --- | --- |
| **Model-visible context contract** | Each model-facing Node Contract Card must declare: allowed Artifact kinds/fields, the rendered projection revision/digest, source classes, output root, Skill/tool/workspace surface, forbidden authority, and correction packet shape. Existing `NodeSpec` plus the current semantic revision already cover part of this; keep it node-local. | The task’s acceptance criteria require exact model-visible inputs and no conflation of Direct/Agent/framework/candidate boundaries. | A generic prompt registry, profile platform, or context service. |
| **Per-node budget and deterministic selection** | Add a byte/token budget, maximum item count, deterministic ordering, and selection/omission rule to each model-facing projection. Start with Research Synthesis, whose current “first six URLs, first 10,000 characters” behavior is an implicit policy (`agent_world/design.py:746-777`). Preserve source identity, URL/content digest, citation index, and coverage reason for every admitted excerpt. | Long context and distractor evidence makes an implicit first-N policy fragile, non-explanatory, and vulnerable to irrelevant early sources. | Embedding/vector retrieval, semantic summarizer, or a new research scheduler. |
| **Treat fetched material as untrusted data** | In the Researcher Runtime Skill/prompt contract, say that source text and tool output are evidence data, not instructions; never follow directives inside them. Keep source text structurally delimited and exclude instructions/credentials/control fields from compiled output. | Indirect prompt injection is directly relevant once web text enters an Agent workspace. Schema validation limits output authority but does not stop relevance/behavior steering. | A claim that prompt wording alone solves injection, or an elaborate security platform. |
| **Safe context receipt, not raw logging** | Make existing provenance sufficient to audit the effective context without persisting it: exact input refs, projection/prompt identity digest, runtime-Skill digest (Agent only), route/model, counts/bytes or token estimate by source class, output-schema revision, and correction ordinal. `WorkRecord`/`OperationEvidence` already carry much of this (`agent_world/contracts.py:114-150`, `194-224`). Add only missing counts/digests if a proof cannot reconstruct them. | The product requires inspectable boundaries, while persistence rules prohibit prompts/transcripts/sealed data. | Persisting raw prompts, raw Agent responses, full web pages, hidden cases, or source code into Observe. |
| **Prove exclusions as well as inclusions** | Contract tests must show CandidateBuild lacks VerifierIntent/sealed/Judge/release files and fields; Direct nodes lack Skill/tools/workspace; the verifier lacks candidate source/private cases; candidate protocol lacks evaluator/release state. | Context isolation fails most often through an accidental extra file, field, or workspace mount—not through an obvious graph-edge error. | OS-sandbox claims that the current fixed full-access adapter cannot justify. |

### Strong recommendation for Research Synthesis selection

Use a deterministic, framework-owned selector before `evidence.json` is staged. It can be a short helper in the existing Design executor; it need not be a model or graph node.

```text
input: ResearchPlan questions, source commitments, extracted text
for each source:
  normalize/document-bound the text; mark it untrusted data
  retain source ID, safe URL, content digest, byte length, and fetch timestamp
  derive bounded excerpts with stable offsets/labels
  score only by deterministic plan-question/source-policy coverage signals
select: up to N sources/excerpts within B bytes/tokens
order: task objective + citation catalog, then selected evidence in stable
       coverage/relevance order, then explicit unresolved gaps/output contract
omit: excerpts whose coverage contribution is zero; record the omission reason
handoff: Agent sees selected excerpts + a complete citation catalog, returns
         only claims/conflicts/gaps indexed into that catalog
```

The scoring does not need embeddings or an LLM. A first version can use query/source provenance, source-policy priority, text length, stable URL order, and “covers an unresolved question” flags. If that later proves insufficient on real traces, retrieval improvements can be separately evaluated. The explicit selection receipt is more important than an ambitious scorer.

### Ordering rules

**Evidence.** Long-context work supports careful placement and shows that context ordering can affect use. It does not prove a universal prompt template.

**Inference for Foundry.** Keep a stable, node-local order:

1. fixed authority/role and non-authority statement;
2. objective and closed output contract;
3. minimum frozen input projection, grouped by semantic dependency rather than artifact chronology;
4. selected evidence/catalogs with stable IDs;
5. explicit forbidden fields/claims;
6. a bounded correction packet only when present; and
7. final instruction to recheck output against the closed contract.

The current Direct serialization puts the static authority guard in the system message and output shape/correction at the end of the user object (`agent_world/design.py:568-582`). That is a reasonable small-context default. Do not duplicate the full input at both ends merely because older position experiments show primacy/recency; measure representative node failures before changing it.

### Dynamic observation rules

1. A tool/process observation may be rich in its local workspace but must cross a node boundary only as an authorized, typed, safe projection.
2. A failed Integration report is an execution fact and can make downstream nodes `not_run`; it is not a CandidateBuild prompt by default.
3. A local correction is not a transcript. The current `CorrectionPacket` is deliberately bounded to code/path/violated condition/expected category (`agent_world/contracts.py:94-110`) and the runner allows at most one local model correction (`agent_world/graph.py:672-680`). Preserve that shape.
4. Sealed case values, private snapshot state, evaluator goals, and raw Judge traces must remain out of every Agent/Direct context. A future repair needs a framework-built, data-only safe brief, not a hidden-case dump.
5. `Observe` is a consumer of durable facts. Its summary must not feed a retry, a node, or a release decision; otherwise it silently becomes a second control plane.

## Caching, reuse, and compaction: the narrow policy

### Three different things must not be conflated

| Mechanism | Safe meaning | Current/required rule |
| --- | --- | --- |
| **Artifact integrity memoization** | Avoid repeated work only inside one recursive verification call. | Scope it to that call; later public reads cold-read/re-hash. This is already specified. |
| **Provider prompt-prefix cache** | Reduces cost/latency for an identical stable prefix. | May cache static authority/Skill-derived prefix if the provider supports it; never treat a hit as semantic evidence or reuse an old response. Dynamic Artifacts remain outside the prefix. |
| **Accepted Work/Artifact reuse** | Reuse a previously accepted semantic result. | Only after matching acceptance identity: exact dependency refs, rendered projection/prompt identity, output contract, mounted Skill (Agent), validator, assurance, and maturity. No raw conversation/session reuse. |

**Project fact.** `GraphRunner.semantic_revision` already binds the node declaration, effective projection digest, output contract, prompt identity, route, and Agent Skill digest (`agent_world/graph.py:442-459`). This is a useful identity ingredient, not by itself an adoption/reuse policy.

**Inference.** Do not add a cache in this child beyond the scoped Artifact verification behavior. Direct’s goal is a fresh real request; broad reuse would blur evidence freshness. If a later repair/Evolve system reuses artifacts, it must use a reviewed acceptance/adoption policy and retain exact source/freshness provenance.

### Compaction decision rule

| Situation | Action |
| --- | --- |
| One fresh Direct LLM node or one fresh isolated Codex Agent node | No conversational compaction. The node starts with a compact projection and ends at a typed Artifact. |
| Research source corpus exceeds the node budget | Select bounded cited excerpts before invocation; do not make an unbounded conversation then summarize it. |
| A later multi-turn repair/Campaign needs continuity | Create a non-authoritative compact note containing refs/digests, decisions, unresolved issue IDs, safe tool outcomes, and a current budget/status snapshot. Rehydrate authoritative details on demand from Artifacts. |
| A future note is missing an authoritative fact | Fail closed or retrieve the referenced Artifact; never hallucinate the fact from a summary. |

When/if compaction is introduced, evaluate it for **recall first, then precision** on real traces, as Anthropic recommends. A compression model such as LLMLingua is not the first choice here because Foundry needs exact citations, control exclusions, provenance, and schema semantics more than generic token reduction.

## Natural-language need to EnvironmentPackage: context and authority chain

```text
Natural-language need
  -> framework canonical request / allowed source and release policy
  -> Researcher: bounded untrusted-source evidence context
  -> Direct Designer: validated claim/catalog projection, no tools
  -> framework compiler: exact Design Artifact
  -> BuildPlan Agent: read-only Design/contract projection
  -> CandidateBuild Agent: Design + BuildPlan only, isolated source workspace
  -> framework + candidate process: Integration normalized to exact report
  -> Challenger Agent: public verifier projection only
  -> framework + candidate process: independent Judge
  -> framework ReleaseKernel + Registry cold-read: EnvironmentPackage
  -> Observe/Consumer: safe projection of released facts only
```

At every arrow, context must get **narrower in authority** even where it gets richer in domain detail. A model knowing more semantic facts must never gain more release/control capability. Conversely, a downstream framework component can possess more private evidence without making it model-visible.

This is the concrete connection between context engineering and the product target. A good prompt alone cannot turn a need into a publishable environment; it can only yield a bounded proposal. The environment becomes credible through typed compilation, untrusted process execution, independent Judge evidence, exact provenance, and Registry re-verification.

## Smallest proofs and regression probes

These are design/proof implications, not implementation instructions for this research worker.

1. **Context-card test per model-facing node.** Assert route, exact Skill cardinality, allowed workspace files, declared input refs, projection digest, output root, forbidden authority fields, and correction limit. Use an inclusion-and-exclusion matrix, not just snapshot text.
2. **Research selection determinism.** Given a source set larger than the budget, assert a stable selected/excluded set, byte/token cap, retained citation IDs/digests, and an omission reason. Verify that only selected excerpts are staged to `evidence.json`.
3. **Injection-shaped source regression.** Use a controlled fetched-text fixture containing instructions that conflict with the Agent task. Assert framework never turns those strings into a route/Gate/release field and that subsequent Direct nodes receive compiled claims/citations, not raw source text. A real-provider robustness claim still needs an opt-in live boundary proof.
4. **Branch isolation.** Assert CandidateBuild’s staged workspace has no verifier/challenge/Judge/sealed files or fields; assert the verifier workspace has no candidate source/private cases. Preserve the already-required integration-failure terminal behavior.
5. **Fresh-session proof.** Verify Direct has no Skill/tool/workspace; verify each Agent work gets one mounted bundle, a fresh `CODEX_HOME`, closed session, and cleanup. Treat `Sandbox.full_access` as an explicit caveat.
6. **Cache/integrity regression.** Verify repeated references within one read can memoize, but a later read detects a tampered Artifact. Verify any future semantic reuse fails when projection/Skill/output/validator/assurance identity changes.
7. **Future compaction proof only when added.** Start from a long repair/Evolve trace, compact it, and show authoritative decisions/facts can be rehydrated by refs. Test omitted facts require retrieval or yield an honest non-success; do not test only summary fluency.

## What is intentionally deferred

- A generic context-engineering framework, memory service, context broker, or “agent OS.”
- A vector database, embeddings, automatic retrieval, or semantic reranker for the first bounded research source set.
- Long-lived cross-node/Codex chat sessions, resumable hidden reasoning, or a global transcript store.
- Automatic prompt compression, generic summarization, or source-text persistence beyond required safe/cited fragments.
- A new permission/capability/profile/sandbox system. The current adapter is intentionally small; do not imply it provides stronger isolation than it does.
- A cache that adopts accepted Artifacts across requests/campaigns without a future reviewed freshness/acceptance policy.
- Any mechanism that lets Observe, a model self-report, candidate code, an LLM judge, or a summary become a Gate, retry route, budget authority, or release decision.

## Related specs and project contracts

- `docs/agent-world-environment-generation.zh.md` — canonical goal and authority contract. Especially relevant: immutable Artifact DAG, Code Router versus LLM advisory, Agent role separation, Task Materialization, candidate out-of-process execution, independent Judge, Registry cold verification, and safe telemetry.
- `docs/direct-rewrite-execution-map.zh.md` — Direct child’s binding distinction among component, Work, Direct LLM, Codex Agent, framework, and candidate process; it explicitly says graph inputs are not model disclosures.
- `.trellis/spec/agent_world/backend/index.md` — artifact verification cache scope, Direct LLM prompt-only / Codex Skill boundary, bounded correction, and causal dependencies versus input disclosure.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — project Agent context is not runtime Agent context; diagnose actual node context before changing prompts/Skills.
- `.trellis/spec/guides/foundry-product-alignment.md` — a green node or graph test does not prove `need -> real runtime -> independent Judge -> Registry EnvironmentPackage`.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md` and `design.md` — current child scope, static DesignGraph/CandidateGraph, exact node cards, and explicit anti-overdesign constraints.

## External references

1. [OpenAI, *Model guidance*](https://developers.openai.com/api/docs/guides/latest-model) — official living documentation, retrieved 2026-08-12. Relevant to lean prompts, tool relevance, prompt caching, persisted reasoning, and measuring context growth.
2. [Anthropic, *Effective context engineering for AI agents*](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (2025) — official engineering guidance on finite context, progressive disclosure, compaction, structured notes, and isolated subagents.
3. [Liu et al., *Lost in the Middle: How Language Models Use Long Contexts*](https://arxiv.org/abs/2307.03172) (TACL 2024) — primary evidence on positional sensitivity, long-context trade-offs, and distractor/retrieval saturation.
4. [Hong, Troynikov, and Huber, *Context Rot: How Increasing Input Tokens Impacts LLM Performance*](https://www.trychroma.com/research/context-rot) (Chroma technical report, 2025) — evidence on length, distractors, similarity, and haystack structure; non-peer-reviewed caveat applies.
5. [Xu, Shi, and Choi, *RECOMP: Improving Retrieval-Augmented LMs with Compression and Selective Augmentation*](https://arxiv.org/abs/2310.04408) (2023) — primary evidence for task-conditioned compression and omitting irrelevant retrieval.
6. [Jiang et al., *LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models*](https://arxiv.org/abs/2310.05736) (EMNLP 2023) — primary evidence for budgeted, dependency-aware compression and its limitations.
7. [Packer et al., *MemGPT: Towards LLMs as Operating Systems*](https://arxiv.org/abs/2310.08560) (2023) — a reference architecture for genuine long-horizon virtual context, included here chiefly to distinguish it from this child’s needs.
8. [Wu et al., *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory*](https://arxiv.org/abs/2410.10813) (ICLR 2025) — primary evidence on index/retrieve/read choices and degradation across sustained interaction histories.
9. [Greshake et al., *Not what you’ve signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection*](https://arxiv.org/abs/2302.12173) (AISec 2023) — primary evidence that retrieved data may be interpreted as instructions and influence external actions.

## Caveats / Not Found

- No provider, Codex SDK, search, fetch, candidate process, or live E2E invocation was run for this research. Code observations are static; the claimed initial Skill surface and actual model-visible request still require the task’s real preflight proof.
- The project has intentionally chosen constant `Sandbox.full_access`. This research therefore does not claim OS/namespace containment for Agent work; it recommends accurate context/authority claims and explicit staging/exclusion tests.
- `Lost in the Middle` studies earlier model families and `Context Rot` is a 2025 technical report rather than peer-reviewed work. Their numerical effects must not be transplanted as thresholds for the configured models. They justify measurement and bounded design, not a fixed token limit.
- OpenAI’s model guide is living documentation and may change; it supports general cache/context principles but is not evidence for the exact behavior of the project’s pinned `openai-codex==0.144.4` adapter.
- No public source establishes a universal best ordering or compression method. The proposed ordering/selection rules are deliberately deterministic, local, and falsifiable through node-level tests and a later real-boundary proof.
- No evidence was found that a vector database, generic compaction model, global transcript retention, or cross-node session continuation is required for this bounded Direct graph. Adding any of them now would exceed the task’s explicit minimal-design scope.
