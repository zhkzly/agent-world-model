# Context / Prompt / Skill / Observe / Feedback / Retry doctrine

- Date: 2026-08-12
- Scope: Direct LLM and tool-enabled Agent proposal nodes.
- Product goal: natural-language need -> executable, independently verified,
  publishable `EnvironmentPackage`.
- Evidence: the three task-local deep-research records, project source of truth,
  official OpenAI/Anthropic engineering documentation, and the primary papers
  listed below.

## The definition that must be restated

**Feedback is the framework making the user's next, more specific wish to the
same LLM or Agent after an observable failure.** It is a new `user` message in
the same node conversation, not an exception dump, a cold retry, a patch, a
Skill edit, an Observe scene, or permission to route/release.

The framework supplies facts and the requested change. The stochastic model or
Agent supplies a complete replacement. The framework then validates the whole
replacement again and alone owns retry admission, routing, budgets, commits,
Judge evidence, and release.

The minimum correction instruction is:

> Same task. Keep the original objective, frozen input, and complete output
> contract unchanged. The previous answer was rejected for the observable
> reasons below. Return one complete replacement, not a patch or explanation.
> Fix every listed occurrence and recheck the whole replacement before
> answering.

## Context engineering is wider than prompt wording

The active model context is the complete token state used for one inference:
stable instructions, the current task, selected evidence, tool definitions and
results when applicable, prior conversation turns, and the new Feedback.
Therefore the engineering question is not "what giant prompt should we write?"
but "what is the smallest high-signal, sufficient context for this node?"

Minimal does not mean shortest. It means complete for the node and free of
irrelevant history, duplicated rules, hidden authority, and downstream data.
Graph causality, model visibility, physical capabilities, and release authority
are four different relations and must not be conflated.

## One context stack, with explicit lifetimes

| Surface | Lifetime | Contains | Must not contain |
| --- | --- | --- | --- |
| Framework/NodeSpec | versioned code | route, execution kind, budgets, validation, commit and release authority | model-generated policy decisions |
| Developer/system instruction | stable for one semantic revision | invariant role and authority boundary | current errors, task data, tool results, retry count |
| Initial user message | one node attempt | objective, frozen minimum projection, success criteria, complete output contract | unrelated Artifacts, hidden tests, downstream release state |
| Previous assistant turn | only this uncommitted correction conversation | the rejected answer as untrusted conversational context | durable authority or persistence |
| Feedback user message | one correction turn | unchanged-task continuity, safe observed issues, requested replacement, whole-result self-check | raw exception text, secrets, policy, budget, owner, route, Gate or release claims |
| Runtime Skill | stable Agent bundle | reusable role procedure, tool discipline, workspace navigation, on-demand references/scripts | current task facts, current failure, transcript, mutable memory |
| Tool contract | stable capability interface | purpose, when to use it, arguments, result/error shape and side effects | current observation or task-specific facts |
| Tool observation | current Agent loop | bounded actual result or safe error facts | reusable instructions or release authority |
| Artifact | immutable cross-node truth | validated typed semantics and provenance | prompt/transcript, rejected raw output, secrets, sealed values |
| Observe | read-only safe projection | what ran, terminal state, safe Findings, refs and usage/provenance | control actions, raw prompts/output, Skill bodies, hidden evidence |
| OpenViking/project memory | curated development memory | stable user preference and evidence-backed reusable lessons | runtime truth, one-off output, secrets, exact transient run state |

Direct LLM nodes have no Skill, tools, or workspace. Tool-enabled Agent nodes
receive exactly one role Skill plus the current task and allowed workspace/tools.
Do not copy the Skill body into the task prompt. Put deterministic work such as
sorting, IDs, hashes, sizes, schema normalization, validation, routing, and
release decisions in code.

## Correct conversation shape

The roles below are a **logical message sequence**, not permission to add a
provider-owned `instructions` field, an ambient developer profile, hidden
server-side continuation, or reused Agent workspace/session state. Direct must
render the stable role and task through its already permitted Prompt/input
surface. An Agent may use only one explicitly declared ephemeral conversation
mechanism; its Skill, tools, and workspace contract remain unchanged.

The first generation is logically:

```text
developer: stable node role, invariant boundaries, output mode
user:      objective + frozen input projection + complete output contract
assistant: first complete proposal
```

When the framework authorizes correction, continue that conversation:

```text
developer: unchanged
user:      original task remains in history
assistant: rejected proposal remains only in ephemeral conversation state
user:      Feedback: facts + requested complete replacement + self-check
assistant: complete replacement
```

If the provider API is stateless, reconstruct these same roles manually. If it
supports continuation, use the official SDK's conversation mechanism without
turning provider retention into product storage. Do not paste the rejected
answer again inside the Feedback message; it is already the prior `assistant`
turn. It remains untrusted data and is discarded when the node transaction
ends. It never enters Artifact, Observe, Skill, release package, or long-term
memory.

Retaining that one final rejected proposal is a deliberate, bounded user
requirement, not a universal result established by the research. The safer
general default is omission because malformed/raw output can anchor the next
answer, contain instruction-like text, duplicate context, or accidentally
create hidden persistence. Here, retain only the immediately preceding final
proposal, use exactly one declared continuation method, never duplicate it in
Feedback, and make no quality claim until the approved real-boundary proof.
Tool results remain separately typed observations under the Agent tool loop;
they are not folded into this assistant-turn exception.

This is the user-approved target semantics, not a claim about the current
implementation. The current source text describes attaching a data-only brief
to a fresh bounded prompt, and the current adapters start fresh calls. Changing
that to an actual/reconstructed conversation must be coordinated in the Direct
repair plan and source contract before code changes; it must not appear as an
unreviewed SDK convenience.

For an Agent, normal tool results/errors are observations inside its authorized
tool loop. A framework validator rejection after the proposal is a new user
Feedback turn. These are related but not the same event.

## Feedback compilation

Input is a real validator/tool/runtime observation. Output is a recipient-facing
instruction, not a serialized internal control object.

Each Feedback message contains exactly four semantic parts:

1. **Continuity**: same objective, frozen input, and complete output contract.
2. **Facts**: every safely known, causally actionable issue at the current
   validation frontier, expressed as `code`, path/pattern, violated condition,
   expected category, and count when grouped.
3. **Action**: return one complete replacement; no patch, diff, explanation,
   retry decision, Gate result, or release claim.
4. **Self-check**: apply every issue to every matching location and validate the
   whole object before answering.

Keep the full `ValidationReport` as framework evidence. Group repeated safe
issues in the model-facing Feedback so dozens of equivalent paths do not crowd
the context. Never hide a safely known independent issue and then spend a turn
discovering it later. If a condition cannot be safely or clearly disclosed,
stop or repair the output contract; do not ask the model to guess.

This is prompt engineering because wording, role, ordering, and recipient
specificity determine whether the model can act. It is context engineering
because the prior answer, selected facts, unchanged contract, Skill/tool
surface, and excluded material determine what the model can understand.

## Four loops that must remain separate

| Loop | Meaning | Semantic Feedback? |
| --- | --- | --- |
| Agent tool continuation | Agent receives a typed tool result/error and chooses another permitted action | observation, not a new node proposal |
| Node-local correction | Same uncommitted node, same frozen inputs/contract, new user Feedback, complete replacement | yes |
| Infrastructure replay/fallback | Same semantic request after a typed replay-safe transport/provider failure | no; do not invent a correction |
| Workflow Repair | Terminal Finding creates a new authorized Artifact revision and reruns the causal suffix | new revision, not chat retry |

The default semantic budget is one correction after the first proposal. A
second correction is permitted only when the versioned node policy explicitly
allows it and code proves strict A -> B progress at the same validation
frontier. The same normalized issue set means no progress and stops. A model
never chooses its own extra turn.

## Error routing

Node-local Feedback is appropriate only when all are true:

- an attributable LLM/Agent output exists and is still uncommitted;
- the same objective, frozen inputs, and output contract remain valid;
- the problem is in the proposal, not credentials, permission, ambiguity,
  transport, a framework bug, or an unknown side effect;
- the framework can give safe, concrete, actionable facts; and
- the explicit correction budget remains.

Credential/configuration failures, denied permission, unresolved high-risk
ambiguity, unsafe disclosure, host/framework defects, and non-replayable or
unknown side effects are terminal or `needs_human`. Transport recovery is a
separate typed replay policy and never receives semantic Feedback.

### Current root-format policy conflict

Official OpenAI Structured Outputs should be used when the selected route truly
supports it; JSON mode alone does not enforce a schema and still has documented
edge cases. The project source currently classifies generic root/non-JSON errors
as output-contract/framework defects that do not consume semantic correction.
The current real Luna failure and the user's explicit desired behavior raise a
narrow alternative: a completed, non-refusal, non-truncated model answer could
receive one root-format Feedback turn in the same ephemeral conversation.

That alternative is **not active policy yet**. It must be resolved in the Direct
failure repair plan with an official-SDK boundary, a precise eligible-result
predicate, a deterministic test, and one real-node comparison. Do not silently
change the source contract, add blind retries, or generalize it to transport
failures.

## Observe and memory

Observe answers "what happened?" for humans and debugging. Feedback answers
"given those trusted facts, what should this specific LLM/Agent change next?"
Feedback may be compiled from the same underlying evidence, but public Observe
is not automatically injected into a model and cannot route, retry, judge, or
release.

Long-term memory is a promotion step after evidence exists, not automatic log
retention. Store only a reusable lesson with scope, supporting source/evidence,
countercondition, and invalidation trigger. Do not store raw provider output,
prompts, full transcripts, one-off errors, credentials, sealed data, or exact
run state. OpenViking is development memory for future project Agents; it is
not a new Foundry runtime subsystem and does not enter Direct node prompts.

The Artifact DAG remains the product's authoritative memory. Future Expand or
long-horizon work may retrieve compact notes by Artifact reference, but notes
must never replace the Artifact, Judge evidence, or release dossier.

## Minimal implementation consequence

This research does not justify a context manager, feedback service, validator
Agent, prompt registry, vector database, memory hierarchy, generic RAG layer,
new graph node, or unbounded retry controller.

The later approved Direct repair should need only:

1. the official OpenAI Python SDK with the strongest actually supported
   structured-output mode and framework-owned retry behavior;
2. a small node-local message renderer that preserves the initial conversation
   and emits the Feedback shape above;
3. existing deterministic validation enhanced only enough to retain and group
   all safely known same-frontier issues; and
4. focused role/content tests, one real failing-then-corrected node proof,
   Observe inspection, then the unchanged downstream E2E.

Passing a correction proves only that node boundary. Product completion still
requires Candidate build/install/runtime, independent Judge, Registry, and a
published `EnvironmentPackage`.

## Primary and official evidence

- OpenAI prompt engineering: message roles, code-versioned prompt builders,
  typed dynamic inputs, tests/evals, and structured prompt sections:
  https://developers.openai.com/api/docs/guides/prompt-engineering
- OpenAI conversation state: stateless requests can reconstruct prior messages;
  Responses can continue a prior response:
  https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI Structured Outputs: schema adherence versus JSON mode and Python SDK
  parsing with Pydantic:
  https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Skills: versioned `SKILL.md` bundles and metadata-first loading:
  https://developers.openai.com/api/docs/guides/tools-skills
- OpenAI model guidance: lean prompts, each instruction once, relevant tools,
  and preservation of prior conversation items:
  https://developers.openai.com/api/docs/guides/latest-model
- The Instruction Hierarchy and the OpenAI Model Spec: message roles carry
  different authority; assistant/tool/external text remains data rather than a
  way to override stable application instructions:
  https://arxiv.org/abs/2404.13208
  https://model-spec.openai.com/2025-10-27.html
- Anthropic context engineering: curate the smallest sufficient high-signal
  token set; minimal is not necessarily short; use progressive disclosure:
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic Agent Skills: metadata -> `SKILL.md` -> on-demand references/scripts;
  deterministic operations belong in code:
  https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Anthropic evaluator-optimizer/agents: feedback loops require clear criteria,
  measurable improvement, environment ground truth, and stopping conditions:
  https://www.anthropic.com/engineering/building-effective-agents
- Self-Refine: initial output -> feedback -> refinement with prior context:
  https://arxiv.org/abs/2303.17651
- CRITIC: external tool feedback supports correction:
  https://arxiv.org/abs/2305.11738
- Training Language Models with Language Feedback: refinement conditions on
  both the initial output and natural-language feedback:
  https://arxiv.org/abs/2204.14146
- Large Language Models Cannot Self-Correct Reasoning Yet: intrinsic correction
  without external feedback can degrade performance:
  https://arxiv.org/abs/2310.01798
- VRpilot provides a concrete code-repair example: retain the prior candidate,
  parse compiler/test output down to relevant errors, and use those errors as
  conversational feedback rather than dumping whole logs:
  https://arxiv.org/abs/2405.15690
- ReAct: tool/environment observations update an Agent's next action:
  https://arxiv.org/abs/2210.03629
- Indirect prompt injection: retrieved external text must remain delimited
  evidence data and must not acquire instruction or release authority:
  https://arxiv.org/abs/2302.12173
- Lost in the Middle and Context Length Alone Hurts: more available context is
  not automatically more usable context:
  https://arxiv.org/abs/2307.03172
  https://arxiv.org/abs/2510.05381
- Reflexion and MemGPT are evidence for later trial-level memory/long-horizon
  contexts, not reasons to add runtime memory to this Direct child:
  https://arxiv.org/abs/2303.11366
  https://arxiv.org/abs/2310.08560
