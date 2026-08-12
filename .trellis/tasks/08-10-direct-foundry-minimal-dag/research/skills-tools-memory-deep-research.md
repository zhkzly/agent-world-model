# Research: skills-tools-memory-deep-research

- Query: Deep research on the boundary between stable instructions, task prompts, Agent Skills, tool contracts and observations, validator feedback, Artifacts, public Observe, and long-term experience memory; include progressive disclosure and correction without mutating a durable Skill.
- Scope: mixed — project contracts/code plus primary OpenAI, Anthropic, MCP, and ReAct sources.
- Date: 2026-08-12

## Findings

### Product conclusion

R9 should keep the current narrow split: framework code owns authority, routing,
validation, persistence, and release; Direct nodes receive one explicit prompt/input
projection; tool-enabled Agent nodes receive that bounded task handoff plus exactly one
versioned Runtime Skill, explicit tools, and a scoped workspace. A Skill is reusable
procedural knowledge, not a place for live state, error text, policy decisions, hidden
tests, or repair history. This follows the task's Direct/Agent contract and is more
restrictive than general-purpose agent-platform guidance by design.

The important distinction is the lifetime and owner of each datum:

| Surface | Put here | Do not put here | R9 disposition |
| --- | --- | --- | --- |
| Stable system/developer prompt | Only a truly global, invariant behavioral/safety baseline when the transport requires one. | Node objectives, Artifact values, tool results, correction text, budgets, release policy, and role methods that differ by node. | Runtime profiles should remain absent/empty as the project contract requires; framework code, not an ambient prompt, owns authority. |
| Task user prompt / rendered node input | Current node objective, frozen minimum projection, closed output shape, relevant prohibitions, and at most one authorized correction packet. Direct nodes also carry their complete semantic method/output protocol here. | Global retry/repair authority, hidden/sealed data, long history, raw prior outputs, generic role playbooks. | Required. Prompt/input is the complete semantic instruction for a Direct node. |
| Agent Skill | Versioned role-specific procedure, tool discipline, workspace navigation, and on-demand references/scripts for one class of Agent work. | Current task facts, mutable state, ad-hoc validator errors, model transcript, source secrets, release decisions, or a second role's procedure. | Exactly one mounted product-owned bundle for each Agent node. |
| Tool schema and description | Stable capability contract: what it does, when to use it, input/output schema, side effects/limits, safe error categories, and examples only for genuinely difficult shapes. | Request-specific data, observations, policy outcomes, secrets, and changing status. | Framework exposes explicit Search/Fetch/Extract or workspace tools; descriptions should be concise and non-overlapping. |
| Dynamic tool observation | Per-call result or `isError`, safe provenance, bounded result summary/handle, and next-action-relevant facts. | Tool definition, reusable procedure, unfiltered raw exception text, credentials, or a permanent lesson. | Ephemeral Agent context/private staged evidence; persist only the approved provenance/claim projection. |
| Validator Feedback | A safe, actionable delta for the same frozen proposal: code, exact path, violated condition, and expected category. | Raw rejected output, owner, coordinate, budget, mutation authority, hidden test, sealed value, verdict, or new task specification. | `CorrectionPacket`; default one local correction and then stop/route through the framework. |
| Workspace Artifact | Typed immutable input/output/provenance needed by another node, an audit, or a controlled repair; raw material may remain only in the authorized private workspace. | Mutable prompt history, provider transcript, credentials, sealed cases, evaluator goals, or Agent self-asserted control/release facts. | Artifact DAG is authoritative; candidate source is scanned by the framework rather than trusted from completion text. |
| Public Observe | Safe state of run, node/work coordinate, Artifact/Finding identifiers, safe code, budget/gate/release projection. | Prompt text, Skill text, credentials, raw source/candidate data, workspace path, sealed case, evaluator/private expected value, or control actions. | Read-only projection; cannot retry, route, judge, or publish. |
| Long-term experience memory | Future-only, curated evidence-backed reusable lessons with scope/version/expiry and retrieval keys. | Every observation, correction packet, one-off failure, raw transcript/prompt, secret, sealed data, or unverified model claim. | Do not add a runtime memory subsystem in R9. Existing immutable Artifacts and task research are sufficient. |

OpenAI's current guidance distinguishes durable developer rules/business logic from
per-request user inputs, and recommends code-versioned prompt builders with tests. It
also recommends lean prompts, one statement of each instruction, and only task-relevant
tools. The product should use that principle without weakening its stricter Direct
no-profile-instruction invariant.

### Boundary rules for this Foundry

1. **Direct LLM nodes:** use no Skill, workspace, tool surface, ambient developer
   instruction, or hidden memory. Put the exact business task, frozen projection,
   compact output protocol, forbidden authority, and optional `CorrectionPacket` in the
   rendered node prompt. A generic Engineer/Researcher Skill would duplicate the only
   semantic source and make the actual request harder to audit.

2. **Tool-enabled Agent nodes:** mount one role bundle. The node prompt should name
   only the current task, frozen files/Artifact projection, required output, and
   authorized feedback. The bundle owns reusable method and tool discipline; the
   prompt must not paste the bundle body again. The framework/tool layer, not the
   Skill, still enforces paths, schemas, budgets, and permissions.

3. **Stable policy belongs in code/NodeSpec, not in either prompt surface:** role,
   route, one-Skill requirement, tool grants, local-correction ceiling, validation,
   Artifact commit, and release conditions are framework facts. They may be described
   to an Agent only when the current work needs to respect them, but description is not
   authority.

4. **Tool contracts stay stable; observations are per-call:** describe a tool as an
   excellent interface for a junior developer: purpose, trigger, arguments, result
   shape, boundaries, and safe errors. Do not ask a Skill to explain a poorly designed
   tool every time. For MCP-shaped tools, distinguish protocol failures (bad tool or
   arguments) from execution failures carried in a result with `isError: true`; validate
   and sanitize results before adding them to model context.

5. **Validator feedback is not a Skill revision:** semantic validation may offer one
   compact, safe correction attached to the original frozen task. A new Skill revision
   is justified only by a separately reviewed, recurring, cross-run procedural gap
   backed by evidence; it is never an automatic response to a single failed turn.

### Minimal progressive disclosure

Use progressive disclosure *inside the one mounted bundle*, not by mounting a stack of
overlapping Skills.

1. **Discovery:** expose only a stable `name` and precise `description` for the single
   allowed Skill (and a high-level namespace description if a broad tool catalog exists).
2. **Trigger:** load its short `SKILL.md` only for the matching Agent node. It contains
   trigger conditions, core workflow, boundaries, and links to deeper material.
3. **Need-to-know reference:** load one named file under `references/` only when the
   task requires that protocol/domain detail. Run deterministic helpers under
   `scripts/`; inject their output, not their source code, when that is sufficient.
4. **Tool detail:** keep only currently relevant schemas callable. If a future product
   has a large tool surface, defer schemas behind a namespace/MCP discovery step rather
   than preload them; R9's small explicit surfaces do not justify a new tool-search
   subsystem.
5. **Live evidence:** put only the current result, a bounded summary, or a stable
   handle into working context. Raw sources stay in the private staged workspace; a
   selected citation/claim is what may become an Artifact.
6. **Cross-session recall:** retrieve a narrowly matched, evidence-backed experience
   card only when a future policy explicitly enables it. It must be optional and
   cannot silently enter a Direct prompt or change a profile.

Anthropic's Skills documentation provides the useful model: metadata is available for
discovery, the `SKILL.md` body loads on trigger, and references/scripts load on demand.
OpenAI's Skill and deferred-tool documentation supports the same operational principle:
small discovery metadata first, detailed instructions/schema only when selected. The
project's source-of-truth already explicitly adopts this pattern for its one Runtime
Skill bundle.

### When a Skill is harmful or redundant

A Skill is the wrong mechanism when any of these is true:

- The node is `DIRECT_LLM`; the product explicitly forbids it.
- The content is a frozen task input, output protocol, current Artifact coordinate, or
  current correction. Put it in the node prompt/input instead.
- The content is deterministic validation, authorization, budget/retry/release policy,
  path safety, or an error schema. Put it in framework code or the tool contract.
- The content is a live observation, raw result, failure trace, workspace state, or
  temporary workaround. Keep it per-call/private and use bounded Feedback when
  authorized.
- The content is shared only because several headings seem convenient. Use one Skill
  with references, not multiple always-mounted bundles; otherwise selection ambiguity
  and duplicated instructions consume attention and obscure provenance.
- The measured problem is a tool interface failure. Improve the tool schema/name/output
  rather than adding natural-language procedure around it.

### Runtime correction without durable-Skill pollution

The safe loop is:

```text
frozen projection + unchanged mounted Skill
  -> proposal
  -> parser/semantic validator
  -> one safe CorrectionPacket only if eligible
  -> fresh isolated physical invocation with the same task + packet
  -> complete replacement proposal -> validate -> commit or terminal Finding
```

The correction packet must be data-only: `code`, exact JSON path,
`violated_condition`, and `expected_category`. It tells the Agent what to fix in this
proposal, not why the framework will permit a retry or what other nodes/sealed tests
expect. Keep the original skill closure immutable and hash-stable across the two calls;
the temporary mounted copy may be discarded after the session. Do not append feedback to
`SKILL.md`, an Agent's persistent notes, a global prompt, or public Observe.

Only after a run is closed should a separate, reviewable promotion filter consider an
experience-memory record. A future record should require: (a) evidence/Artifact or
real-proof references, (b) a stable node/Skill/tool/schema version scope, (c) a concise
reusable claim plus countercondition, (d) a non-secret/non-sealed safety check, and
(e) expiry or invalidation criteria. It must not automatically edit a Runtime Skill.
This is deliberately not a new R9 runtime feature.

### Code patterns found

- `agent_world/graph.py:39-70` encodes the basic trust boundary: model nodes need a
  prompt identity, Agent nodes require a Skill, and Direct nodes reject one.
- `agent_world/graph.py:442-460` commits a semantic revision using the effective
  projection, prompt identity, route, and Agent Skill digest without persisting the
  prompt or Skill body.
- `agent_world/graph.py:462-557` implements the bounded proposal/validation loop and
  persists a correction only for an eligible first rejected attempt.
- `agent_world/contracts.py:95-141` constrains `CorrectionPacket` to safe fields and
  keeps operation evidence to model/usage/Skill-digest facts.
- `agent_world/design.py:540-586` appends an authorized correction to the per-attempt
  Agent instruction and renders Direct node context separately; `design.py:625-670`
  treats the frozen projection as semantic material for a Direct commit.
- `agent_world/invocation.py:229-276` creates a fresh `CODEX_HOME`, mounts exactly one
  Runtime Skill, verifies it, and deletes it after the turn; `invocation.py:313-365`
  makes the whole bundle closure the committed digest.
- `agent_world/runtime_skills/research-world-evidence/SKILL.md:1-21` demonstrates the
  intended narrow Role Skill: cite-backed output and explicit gaps, with raw source
  text retained only in the supplied workspace.
- `agent_world/artifacts.py:64-110` rejects forbidden/secret-like persisted fields;
  `artifacts.py:270-305` persists canonical immutable JSON Artifacts.
- `agent_world/observe.py:381-497` projects only safe work/Finding fields, and
  `observe.py:498-530` exposes a read-only run scene rather than raw execution state.

### Files found

- `docs/agent-world-environment-generation.zh.md` — source-of-truth product contract:
  component authority, Direct-vs-Agent input separation, progressive one-Skill bundles,
  repair routing, secrets/sealed-data exclusions, and observability rules.
- `docs/direct-rewrite-execution-map.zh.md` — derived execution map separating
  framework, Direct LLM, tool-enabled Agent, candidate process, and safe Observe.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md` — R9 node contract,
  prompt/Skill/feedback split, and public Observe boundary.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — closed
  `CorrectionPacket`, Agent workspace inputs, and same-run Judge-memory exclusions.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — debugging guidance that keeps
  project-Agent view, Direct input, Agent Skill, code boundary, and feedback distinct.
- `.trellis/spec/agent_world/backend/index.md` — package requirements for Direct
  prompt-only routing, singleton Skill materialization, and actionable safe diagnostics.
- `agent_world/graph.py` — node-kind/Skill invariants, semantic revision, corrections,
  WorkRecords, and Findings.
- `agent_world/design.py` — concrete Direct/Agent prompt construction and staged
  research evidence handling.
- `agent_world/invocation.py` — Direct chat and isolated Codex Agent adapter boundaries.
- `agent_world/artifacts.py` and `agent_world/observe.py` — secret-safe immutable
  persistence and safe read-only public projection.
- `agent_world/runtime_skills/*/SKILL.md` — the four current product Runtime Skill
  bundles and their role-specific instructions.

### External references

- [OpenAI Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering) — developer rules/business logic versus user inputs, code-managed prompt builders, and evaluation/versioning guidance (accessed 2026-08-12).
- [OpenAI Skills](https://developers.openai.com/api/docs/guides/tools-skills) — versioned `SKILL.md` bundles and discovery metadata supplied to the model (accessed 2026-08-12).
- [OpenAI Tool search](https://developers.openai.com/api/docs/guides/tools-tool-search) — defer detailed tool schemas; use high-level namespace/MCP descriptions to load only what is needed (accessed 2026-08-12).
- [OpenAI Model guidance](https://developers.openai.com/api/docs/guides/latest-model) — favor lean prompts, expose only relevant tools, and keep tool descriptions concise/precise (accessed 2026-08-12).
- [Anthropic Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) — metadata → triggered `SKILL.md` → on-demand references/scripts progressive disclosure and Skill-supply-chain caution (accessed 2026-08-12).
- [Anthropic Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) — tool descriptions should cover behavior, trigger, and input schema; examples help only for complex/form-sensitive calls (accessed 2026-08-12).
- [Anthropic Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — context is finite; use just-in-time retrieval, compaction, and structured notes rather than unbounded history (accessed 2026-08-12).
- [Model Context Protocol Tools specification, 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) — separates protocol errors from `isError` execution results and calls for input/output validation, sanitization, timeouts, and audit logs.
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) — external observations should inform the next action/reasoning step; it does not justify promoting transient observations into durable instructions.
- [Anthropic Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — start with the simplest workflow, reserve agents for flexible model-directed work, and treat tool interfaces as first-class agent-computer interfaces.

### Related specs

- `.trellis/spec/guides/foundry-product-alignment.md`
- `.trellis/spec/guides/agent-llm-node-debugging.md`
- `.trellis/spec/agent_world/backend/index.md`
- `docs/agent-world-environment-generation.zh.md`
- `docs/direct-rewrite-execution-map.zh.md`
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md`
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md`

## Caveats / Not Found

- This is read-only research, not a repair plan, cross-layer review, implementation
  decision, or real execution proof. No provider invocation or production change was
  performed.
- The external sources describe broadly useful agent patterns. The project source of
  truth is stricter: it wins whenever general platform advice would introduce ambient
  instructions, more than one Skill, hidden tools, or a durable memory channel.
- ReAct supports an observation-to-next-action feedback loop; it is not evidence for
  exposing chain-of-thought, provider transcripts, or hidden Judge data in Artifacts or
  Observe.
- No dedicated long-term experience-memory component is specified in the current R9
  contracts. The recommendation is intentionally to defer it rather than smuggle
  mutable experience into Skills or runtime prompts.
- This research does not prove that every prompt-body change is mechanically reflected
  in the current semantic-revision identity; that is a separate implementation/proof
  question.
