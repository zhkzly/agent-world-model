# Research: prompt-feedback-deep-research

- Query: Deep research on initial-generation and iterative-revision prompting for Foundry Direct and Agent nodes: instruction hierarchy, roles, structured output, validator feedback, Self-Refine, Reflexion, evaluator-optimizer, replacement versus patch, prior output, multiple issues, stochastic repair, bounded retries, no-progress, tool/transport failures, permissions, ambiguity, and evaluation.
- Scope: mixed
- Date: 2026-08-12

## Findings

### Executive conclusion

The useful prompt pattern is deliberately small: an initial request supplies the
frozen task and output contract; an authorized correction is a new user-level
wish that preserves that contract, gives only safe validator facts, asks for a
complete replacement, and requires a whole-object recheck. It is not a retry
permission, a repair route, a hidden evaluator, or a release decision.

Research supports specific, actionable feedback and retaining relevant history,
but it does not authorize an Agent to choose another turn. In Foundry, the
framework must make that decision from attribution, replay safety, immutable
inputs, issue disclosure safety, budget, and no-progress policy. The canonical
source assigns JSON/schema mechanics, retry, permission, route, invalidation,
and release to code, not the LLM
(docs/agent-world-environment-generation.zh.md:369-445).

The active R9 slice has a narrower, presently implemented local loop: one
CorrectionPacket may cause a second physical call only when the first node
failure is rejected, non-retryable, and carries that packet
(agent_world/graph.py:462-680). It does not yet render that packet as a complete
revision wish, preserve an assistant transcript, or aggregate a full
same-object issue frontier. This report describes the evidence and a minimal
contract; it does not authorize a code, prompt, policy, or retry change.

### Authority and conversation roles

Instruction hierarchy is a safety property, not a stylistic preference. Wallace
et al. propose higher-priority system instructions over user instructions and
user instructions over third-party/tool content; their paper specifically frames
lower-trust content as a prompt-injection risk. OpenAI's current Model Spec
likewise makes higher-authority instructions override lower-authority ones and
states that quoted data, attachments, and tool output have no authority unless
an authorized instruction delegates it.

For Foundry, apply that principle as follows:

| Conversation material | Proper role and authority | What it may contain |
| --- | --- | --- |
| Stable system/developer instruction | Highest application-controlled runtime instruction | Node role, Direct-versus-Agent boundary, immutable task/output contract, forbidden authority, and the required output mode. |
| Initial user request | The first task wish | Frozen model-visible projection, objective, completeness criteria, and the closed output shape. |
| Previous assistant result | Contextual data, never authority | At most a volatile rejected proposal; it must never amend the output contract or determine retry/release. |
| Tool result/error | An observation, not an instruction | Typed result or safe error facts; it can enable the Agent to choose a different permitted action. |
| Framework revision message | A second, framework-authored user wish | Continuity, safe validation facts, full-replacement request, and self-check. It cannot override system/developer constraints. |

The roles do not make model output trustworthy. The Model Spec notes that an
application can supply arbitrary assistant messages, and says untrusted
structured/quoted text should normally be treated as data rather than
instructions. Therefore a rejected proposal must never be injected as a
developer instruction or allowed to carry control-plane claims.

This matches the product split: Direct receives only rendered Prompt/input and
authorized feedback, while a runtime Agent additionally receives its single
mounted Skill, granted tools, and workspace
(.trellis/spec/guides/agent-llm-node-debugging.md:19-26). Direct must not gain
an Agent Skill or tools merely because a correction is needed.

### Initial-generation prompt engineering

The active design already defines the right composition order:

1. authority and node role;
2. exact objective;
3. frozen minimum input projection;
4. completeness and quality obligations;
5. closed output shape;
6. forbidden fields/downstream claims;
7. optional authorized correction.

That is the binding task design
(.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:223-248). Keep the
initial instruction self-contained for Direct nodes because Direct mounts no
Skill. Keep Agent prompts bounded to the current task, coordinates/projection,
and desired outcome; reusable procedure and tool discipline belong in the one
mounted Runtime Skill, not in duplicated prompt prose.

Practical implications:

- State the task, success condition, and complete output shape positively and
  once. Repeated prose is not a substitute for a closed contract.
- Put the output contract at the provider boundary when supported. JSON mode is
  only a validity aid; strict structured output can enforce a supplied schema,
  but neither proves business semantics nor prevents refusal/truncation.
- Exclude framework authority from the model's output surface. The model must
  never write retry count, owner, budget, invalidation, Gate, Finding, or
  release fields.
- Use stable, versioned prompt/input builders. Any effective Prompt, input
  projection, output model, or mounted Skill change is a semantic revision, not
  a quiet retry change
  (.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:218-248).

Structured output is an input/output guard, not a semantic validator. OpenAI's
Structured Outputs release distinguishes JSON mode from schema adherence and
explicitly says that a schema-conforming object can still contain incorrect
values. That supports a two-stage design: provider/schema constraints prevent
representational failures where possible; framework compilation validates
references, business rules, cross-field conditions, and provenance.

### What the iterative-refinement literature actually supports

| Primary source | Direct finding | Foundry implication and limit |
| --- | --- | --- |
| Wallace et al., The Instruction Hierarchy, arXiv:2404.13208 | Conflicting lower-trust instructions must not override higher-priority instructions; evaluation includes prompt injection and over-refusal. | Keep correction at user-level beneath the stable system/developer contract. Treat prior proposal/tool text as untrusted data. Test both injection resistance and non-conflicting helpfulness. |
| OpenAI Model Spec, version 2025-10-27 | Defines authority levels and describes tool responses as appended observations followed by another assistant invocation. | A correction can be conversational, but it cannot confer policy authority. Tool outputs are facts with constrained trust. |
| OpenAI Structured Outputs, 2024-08-06 | JSON mode does not guarantee a schema; strict structured output can enforce a supplied schema, while semantic mistakes, refusal, and truncation remain possible. | Do not use a successful parse/schema check as proof of semantic validity. Do not turn provider refusal or truncation into a blind semantic correction. |
| Madaan et al., Self-Refine, arXiv:2303.17651 | Generates an initial output, feedback, and refinement; the refiner sees earlier output/feedback. Feedback is useful when specific/actionable; the paper uses stopping conditions and a maximum of four iterations. | A feedback message should name concrete fixes and preserve task context. Do not inherit its self-evaluator as a control authority: Foundry uses deterministic validators and a much tighter budget. |
| Shinn et al., Reflexion, arXiv:2303.11366 | Uses verbal reflection over external or internal feedback and stores it in episodic memory for later trials. | Reflexion is a trial-level learning/memory pattern, not justification for modifying an immutable node revision or retrying an effectful operation. Persistent reflection would need its own Artifact/privacy/authority contract. |
| Yao et al., ReAct, arXiv:2210.03629 | Interleaves reasoning with actions; environment observations let a model update plans and handle exceptions. | A safe public tool result/error can enable another Agent action inside an authorized tool loop. It is distinct from a new node-local semantic correction. |
| Anthropic, Building Effective AI Agents, 2024-12-19 | Evaluator-optimizer loops fit when evaluation criteria are clear and iteration has measurable value; Agents need ground truth and stopping conditions. | Deterministic validator feedback is preferable where possible. Add a second evaluator model only when it improves a measured outcome; it must not replace framework validation or routing. |
| Liang et al., HELM, arXiv:2211.09110, and Liu et al., AgentBench, arXiv:2308.03688 | Evaluation needs standardized conditions, multiple metrics, and interactive-environment coverage. | Test correction policy across failure classes, routes, and interaction states; report quality, safety, cost, latency, and no-progress rather than a single pass rate. |

Self-Refine is especially relevant to two questions. First, it demonstrates a
reasonable refine input of original task plus prior output plus feedback.
Second, it also reports weak self-evaluation in nuanced reasoning settings:
external feedback can be materially better than model self-feedback. The
correct inference is not to reproduce its unbounded self-loop. It is to give a
framework validator's exact, safe observation to one bounded revision turn.

Reflexion has a different time scale. Its reflection memory can improve later
trials, but a Foundry correction operates on one uncommitted proposal with
immutable inputs. It must not be stored as a mutable opinion that changes
Artifact truth, parent selection, retry authority, or release state.

### Validator-generated feedback: the required boundary

A validator-generated message is valid only when it is a safe projection of
facts the framework already established. It must be:

- attributable to the just-completed model/Agent proposal;
- tied to the same uncommitted node, shard, immutable input, and output
  contract;
- concrete enough to repair: closed code, exact path or safely clustered path
  pattern, violated condition, and expected category;
- complete for every safely discoverable issue at that validation frontier;
- free of secrets, sealed cases, raw provider content, coordinates, owner,
  repair policy, budget, invalidation, Gate state, and release facts; and
- issued only after framework authorization and budget admission.

The canonical source is explicit: a shape-correct proposal rejected by compiler
or semantic validation retains each safe
code + path + violated condition + expected category; the resulting
AgentCorrectionBrief contains only those blockers and requests a complete typed
artifact, while code retains routing and authorization
(docs/agent-world-environment-generation.zh.md:421-445).

Multiple issues must be handled as one same-object frontier, not as a
field-by-field conversation:

- The complete ValidationReport retains every field-level issue for audit and
  no-progress comparison.
- The model-visible brief groups only safely equivalent issues by code,
  violated condition, and expected category; it reports count, affected path
  pattern, and a few representative paths.
- The brief says that each condition applies to every matching location in the
  complete replacement.
- If the issue clusters cannot be safely disclosed or cannot fit a coherent
  local rewrite, terminal-block or redesign the proposal boundary. Do not spend
  arbitrarily many turns discovering issues one at a time.

This is stronger than the current implementation. GraphRunner currently carries
one CorrectionPacket and immediately invokes the second call after its first
eligible exception (agent_world/graph.py:486-557); current Direct/Candidate
compilers commonly fail at the first error. That leaves an A-to-B failure mode:
the model can fix the disclosed issue yet spend its only turn on a different
hidden issue. The source-of-truth requirement is aggregation of known safe
issues, not a second validator model and not a larger retry counter.

### Complete replacement versus patch

For a structured semantic proposal, require a complete replacement. The
proposal is atomic: the framework validates the whole object and commits either
the entire typed Artifact or nothing. A patch/diff/explanation leaves ambiguous
which unchanged fields survive, makes omissions easier, and shifts merge logic
into an untrusted response. This conclusion is an engineering inference from
the immutable Artifact contract, not a claim that the cited papers prove a
universal replacement rule.

The rule is narrow:

- Direct source drafts and Agent advisory JSON: return one complete declared
  object, never a patch, diff, prose rationale, or partial subtree.
- A writable CandidateBuild Agent may edit its private workspace incrementally,
  but its final CandidateCompletionDraft is still a complete declared object;
  framework scanning and a fresh candidate revision establish source truth.
- Cross-node repair creates a new owner Artifact revision and reruns only the
  causal suffix. It is not a conversational patch applied to a committed
  Artifact.

This agrees with the source requirement that Evolve reconstruct a complete
WorldSpec/task/verifier/implementation candidate rather than accept a source
patch as evolution (docs/agent-world-environment-generation.zh.md:97-102), and
with the correction brief rule that the model re-produces the complete same
typed semantic Artifact (docs/agent-world-environment-generation.zh.md:433-438).

### Prior assistant output: include conditionally, not by default

Self-Refine retains prior output and feedback, and common Agent SDK conversation
mechanisms can carry earlier assistant messages forward. That is evidence that
history can improve refinement; it is not evidence that raw rejected output
must be persisted or echoed in every corrective request.

For the minimal Foundry contract, do not include the rejected assistant output.
Re-send the immutable task projection/output contract plus the validator brief.
That is sufficient for a full replacement and has these benefits:

- A malformed response has no safe canonical structured representation to echo.
- The project forbids raw prompts/provider payloads/private transcripts in
  Artifacts and Observe; retaining the proposal for a correction must not
  silently create another persistence channel
  (.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:245-248).
- The prior proposal can contain prompt-injection-like text or forbidden
  control claims. It must be data, never instruction.
- Repeating a large faulty object consumes context and can anchor the model on
  the failed structure. The exact error frontier is the causal information the
  model needs to regenerate.
- The present Direct adapter creates only system and user messages for each
  call, and the Agent adapter starts a fresh ephemeral AsyncCodex thread; neither
  preserves an assistant transcript
  (agent_world/invocation.py:97-163 and agent_world/invocation.py:283-310).

An optional future experiment may include a parsed rejected proposal only if
all of these are true:

1. it is a bounded, canonical, parseable object from the same attempt;
2. policy permits it to remain in volatile per-invocation memory and it contains
   no secret, sealed value, external/tool instruction, or control field;
3. it is sent explicitly as untrusted data, not as developer instructions or a
   source of authority;
4. the same conversation-state strategy is used exactly once, without duplicate
   history or a hidden server-side continuation;
5. the test suite proves no Artifact, trace, manifest, package, or Observe
   projection retains the raw object; and
6. an A/B evaluation shows a net benefit across held-out cases without worse
   injection, cost, or no-progress rates.

Even then, the correction user message must remain authoritative only as a
user-level request and require a complete replacement. A new persistent
conversation/session or response-ID path would alter the effective input
surface, replay safety, and semantic revision; it is not a wording-only
change.

### Minimal Feedback-as-next-user-wish contract

Use this exact semantic shape for the second message. The rendering can be
plain text or a closed JSON envelope, but no field below may gain control-plane
meaning.

    Same task. Keep the original objective, frozen input, and declared output
    contract unchanged.

    The previous proposal was rejected. Return one complete replacement of the
    declared object. Do not return a patch, diff, explanation, retry decision,
    Gate result, or release claim.

    Fix every listed issue wherever it occurs:
    - code: <closed safe code>
      path: <exact path, or safe pattern plus representative paths>
      violated_condition: <short safe condition>
      expected_category: <closed expected category>
      count: <only for an aggregated safe cluster>

    Before answering, recheck the complete replacement against the original
    task, all declared fields, and every listed condition. Return only the
    declared complete object.

The four required semantic components are:

1. continuity: same task, immutable projection, same output contract;
2. facts: one bounded list of safe validator issues;
3. action: full typed replacement, never a patch or explanation;
4. self-check: apply every issue to the whole object before returning.

The contract intentionally omits prior raw output, route, model, node/shard
coordinate, Artifact IDs, retries remaining, budget, owner, repair target,
invalidations, hidden validator data, Judge output, and release state. These
facts are either unnecessary for repair or would transfer authority.

The current code sends a serialized correction data field to Direct
(agent_world/design.py:561-587) and appends an Authorized correction packet to
Agent instructions (agent_world/design.py:540-559 and
agent_world/candidate.py:708-750). That is not yet the full wish above: it does
not explicitly preserve the original task, require replacement rather than
patch, prohibit explanations/control claims, or require a whole-object
self-check.

### Exact turn-decision matrix

The question must distinguish four different outcomes:

1. a node-local revision: a new model/Agent turn with Feedback-as-next-user-wish;
2. an in-session tool-loop continuation: an Agent receives a tool observation
   and selects another permitted action;
3. an infrastructure replay: framework schedules a new physical attempt with no
   semantic feedback; and
4. no external turn: terminal block, rejection, or needs_human.

| Event at the active boundary | Another model/Agent turn? | Required facts before that outcome | Correct disposition |
| --- | --- | --- | --- |
| Model/Agent returned non-JSON or malformed JSON | No under the active R9 contract. | It is a generic root output/parse failure with no field-level semantic frontier. R9 explicitly says provider/transport/JSON parsing never enters local correction. | Record rejected output-contract evidence; no blind retry. A future reclassification requires a real diagnosis, a safe root diagnostic policy, a reviewed plan, and a fresh critic allow. |
| Valid JSON, but wrong top-level/root shape with no useful exact issue | No. | Generic root shape error or missing safe path/condition/category. | Framework/output-contract terminal; improve provider schema/adapter or model-facing contract through the normal change gate, not a model turn. |
| Valid JSON, field-level closed-schema mismatch | Yes, exactly one local revision only if every local-revision predicate below is true. | Framework can emit safe, exact field path, condition, and expected category; response is uncommitted and input/output definition remains immutable. | Send the bounded full-replacement wish. Provider-enforced schema rejection/refusal itself is not this case. |
| Valid, shape-correct JSON rejected by deterministic compiler/semantic validator | Yes, exactly one local revision only if every predicate holds. | All safely discoverable issues are reported/clustered; no disclosure leaks hidden/sealed data; failure is attributable to the proposal rather than framework code. | Send one full-replacement wish; framework independently validates the replacement. |
| Semantic validator cannot disclose condition or expected category safely | No. | The model would have to guess a hidden constraint. | Terminal framework/output-contract failure or redesign the boundary; never authorize a blind semantic retry. |
| Second response has the same normalized issue set/frontier | No. | Same path + code + condition + expected-category set after correction. | No-progress terminal. Do not raise temperature, switch routes, or increase count silently. |
| Second response turns issue A into a distinct issue B | Not a local third turn in current R9. | A-to-B is strict validation progress, not success. Any further attempt needs an existing higher-level RepairAction, budget, and policy. | Current R9 records the terminal; future bounded repair may create a new revision only through its separate contract. |
| Agent proposes an unknown/invalid tool before the tool executes | Possibly an in-session Agent tool-loop continuation, not a node-local revision. | Tool runner has an explicit safe model-visible error contract; no side effect occurred; error names an available safe alternative; turn/tool budgets permit it. | Return a typed tool error observation and let the Agent choose an allowed tool. The OpenAI Agents SDK offers this only as an explicit opt-in for unresolved function tools. |
| A tool executes and returns a declared public business/precondition error | Possibly an in-session Agent tool-loop continuation. | The ToolContract declares the error/result shape; Agent has enough public information to choose a different permitted action; error is not a permission escalation. | Feed the result/error as an observation. Count it as a real tool operation; do not turn it into a node repair by default. |
| Tool timeout/transport failure before a reliable result | No semantic feedback turn. | Framework knows whether replay is deterministic, queryable, or idempotent-with-key; no unknown side effect; typed retryability, RepairPolicy, and budget all permit replay. | At most one framework-authorized infrastructure retry; otherwise terminal with conservative/unknown usage. |
| Tool may have executed a side effect, or replay safety is unknown | No automatic turn/replay. | External state is ambiguous or non-replayable. | Reconcile if possible; otherwise terminal/needs_human. Never ask the Agent to repeat the action blindly. |
| Direct/Agent transport, timeout, or provider HTTP failure before terminal envelope | No Feedback-as-next-user-wish. | Typed error, known response-start/replay-safety facts, appropriate replay mode, RepairPolicy, hard budget, and idempotency condition. | Framework-only infrastructure retry/fallback if admitted; otherwise terminal. It is not semantic correction. |
| Provider refusal, credential/configuration failure, missing executable, permission denial, or approval rejection | No automatic corrective turn for the denied action. | The missing authority is real and cannot be inferred. | needs_human or terminal configuration/permission result. An Agent may describe a safe alternative only when doing so cannot broaden permission or rerun the denied action. |
| High-risk or permission-relevant product ambiguity | No. | Request/evidence policy says a human decision is required. | needs_human. The model cannot close an explicit human-required unknown. |
| Low-risk information gap with an authorized research operation | Not a local correction of the failed proposal. | Separate research node/operation, allowed sources, and budget. | Use the normal Researcher/framework path; do not have the failed node invent facts. |

The local-revision predicate is therefore:

    completed, attributable model/Agent proposal
    AND output has not committed
    AND same immutable input + output contract remain valid
    AND failure is proposal-owned, not transport/permission/framework-owned
    AND all model-visible issues are safe and causally actionable
    AND no non-replayable tool side effect is implicated
    AND authorized local correction + hard budget remain
    AND normalized issue frontier is not no-progress

The model never evaluates that predicate. GraphRunner currently approximates only
part of it: first ordinal, one local correction, Direct/Agent kind, rejected
status, non-retryable status, and a present CorrectionPacket
(agent_world/graph.py:671-680). The stronger conditions are product-policy
requirements, not permission to infer a retry from an exception type.

### Bounded retries, stochastic repair, and no-progress

Treat stochasticity as a reason to measure a bounded second proposal, never as
proof that another proposal is allowed. Self-Refine demonstrates potential
improvement from refinement, but it also uses explicit stopping logic and a
fixed maximum. Evaluator-optimizer guidance similarly makes stopping conditions
part of control. This supports a small budgeted experiment, not retry-until-pass.

No-progress must compare normalized issue states, not exception class or raw
count:

- fingerprint: stable set of path + code + violated_condition +
  expected_category for the same validation frontier;
- same fingerprint after a revision: no-progress;
- A to B: progress in diagnosis, but not a valid output;
- A to B to A: oscillation and stop;
- an issue-count reduction alone is not sufficient evidence of progress;
- an output passing the deterministic compiler/validator is the only local
  success; model self-certification is not evidence.

The canonical source requires this exact distinction
(docs/agent-world-environment-generation.zh.md:300-307 and 421-445). Its
broader repair policy permits only bounded, framework-authorized progression;
the active Direct slice does not yet implement a general RepairLedger or
cross-node rerun. Do not stack node-local correction, provider fallback, and
controller repair ceilings into multiplicative retries.

For infrastructure failures, OpenAI's Agents SDK documentation is consistent
with the intended separation: retries are opt-in; policy receives typed
network/HTTP/replay facts; aborts, response-started streams, side-effect vetoes,
and unknown-safe stateful follow-ups fail closed. That is useful reference
behavior, but Foundry's framework remains the authoritative policy owner.

### Evaluation methodology

Do not evaluate this change by one attractive correction sample. Run a
pre-registered comparison with exact prompt/rendering/configuration provenance
and a held-out corpus. The corpus should contain at least:

1. valid first-pass outputs;
2. non-JSON/invalid-root output;
3. one field-level schema violation;
4. multiple independent safe field/semantic violations;
5. a condition that cannot safely be disclosed;
6. same-fingerprint repetition;
7. A-to-B progress and A-to-B-to-A oscillation;
8. unknown-tool call before execution;
9. declared business/precondition tool error;
10. queryable/idempotent tool outage versus unknown-side-effect outage;
11. provider transport failure before and after response start;
12. credential/approval denial; and
13. high-risk ambiguity requiring a human.

Compare at least these arms under the same model, route, temperature, schema,
and frozen task projection:

- initial generation only;
- current packet-only correction rendering;
- the minimal next-user-wish rendering with the same one-correction budget;
- only if separately approved, volatile prior-proposal inclusion versus omission.

Measure:

- first-pass valid rate; conditional repair-success rate; and complete
  validation success after at most the authorized calls;
- schema/semantic/tool classification precision and false-correction rate;
- same-fingerprint no-progress, A-to-B, and oscillation rate;
- complete-replacement compliance, including omission/extra-field and
  patch/explanation rejection rate;
- tool safety: invalid-tool recovery, duplicate side-effect attempts,
  permission-escalation attempts, and replay-safety violations;
- cost: model turns, tool calls, tokens, wall time, and unknown usage;
- security: raw-output/secret/sealed/control-field leakage and prompt-injection
  resistance; and
- product progression: isolated node success separately from downstream
  Integration, Judge, Registry, and E2E outcomes.

Use deterministic validators as the primary scoring oracle. For subjective
quality, add blinded human preference or an independent evaluator, then report
its agreement/calibration separately; never let that evaluator decide retry,
route, budget, or release. Report confidence intervals or a paired statistical
comparison when sample counts permit. HELM's multi-metric standardized
evaluation and AgentBench's multi-turn environmental coverage support this
broader measurement rather than a single benchmark score.

The minimal proof sequence after any separately approved implementation would
be:

1. deterministic renderer/contract tests prove exact message role/content,
   preservation of frozen inputs, full replacement wording, safe multi-issue
   grouping, absence of raw output/control fields, and no third local call;
2. deterministic fault-injection tests prove every row in the decision matrix;
3. one isolated real Direct or Agent node proves the actual provider/SDK
   boundary and its safe Observe projection;
4. read Observe at that terminal and stop at the first new failure; and only
   then
5. run immediate causal consumer proof and, later, a fresh E2E.

Passing a rendering test or isolated correction is not proof of an executable,
independently verified, Registry-released EnvironmentPackage.

## Files found

- docs/agent-world-environment-generation.zh.md — canonical product and
  control-plane authority contract; source of truth for feedback, repair,
  budget, no-progress, permission, and release.
- docs/direct-rewrite-execution-map.zh.md — derived map of framework, Direct
  LLM, Agent, and candidate-process responsibilities.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md — active Direct
  foundation scope and acceptance constraints.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md — R9 Prompt,
  Runtime Skill, local correction, and bounded-repair separation.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md — current
  common model boundary and explicit R9 parser/transport classification.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md — current
  planned Direct closure and explicit non-goals.
- agent_world/contracts.py — CorrectionPacket definition and safe terminal
  contracts.
- agent_world/graph.py — NodeSpec local-correction limit and the current
  two-physical-call transaction runner.
- agent_world/design.py — Direct and Agent prompt assembly for design nodes.
- agent_world/candidate.py — Agent correction packet assembly for build and
  candidate nodes.
- agent_world/invocation.py — current Direct Chat adapter, Agent SDK boundary,
  parse/error classes, fresh-thread lifecycle, and adapter fallback behavior.
- .trellis/spec/agent_world/backend/index.md — backend policy for validation
  visibility, no-progress, replay safety, and typed infrastructure retries.
- .trellis/spec/guides/agent-llm-node-debugging.md — role/context separation
  and evidence-first diagnosis rules.
- .trellis/spec/guides/foundry-product-alignment.md — north-star and
  non-completion guardrails.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/research/prompt-feedback-observe-retry-principles.md
  — prior internal prompt/feedback distinction.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/research/correction-feedback-audit.md
  — prior internal audit of fail-fast correction frontier and A-to-B risk.

## Code patterns

- CorrectionPacket is intentionally limited to code, path,
  violated_condition, and expected_category
  (agent_world/contracts.py:95-110).
- NodeSpec allows zero or one local correction; GraphRunner makes at most two
  physical calls and permits its second only for a first rejected,
  non-retryable, packet-bearing Direct/Agent failure
  (agent_world/graph.py:35-80, 462-557, and 671-680).
- The Direct wrapper reuses frozen projection and output shape but only sends a
  nullable correction data field; it does not carry a prior assistant message
  (agent_world/design.py:561-642).
- Design and Candidate Agent wrappers append an Authorized correction packet
  without an explicit full-replacement revision wish
  (agent_world/design.py:540-559 and agent_world/candidate.py:708-750).
- Direct invokes only a system and a user message, requests JSON-object mode,
  parses the response strictly, and currently maps parse failures to rejected
  InvocationError; transport/selected HTTP failures are separately typed
  (agent_world/invocation.py:49-163).
- Each Agent invocation creates a fresh ephemeral AsyncCodex thread, so the
  second invocation does not implicitly inherit prior assistant output
  (agent_world/invocation.py:178-310).
- The active node contract permits one packet but states that
  provider/transport/JSON parsing and process/integration/judge/package failures
  do not enter local correction
  (.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:125-148).
- The canonical source instead requires a full safe validation report and
  model-visible correction brief for safe semantic issues, with clustering for
  multiple issues and terminalization when disclosure is unsafe
  (docs/agent-world-environment-generation.zh.md:421-445).

## External references

- Wallace, Xiao, Leike, Weng, Heidecke, and Beutel. 2024. The Instruction
  Hierarchy: Training LLMs to Prioritize Privileged Instructions.
  https://arxiv.org/abs/2404.13208
- OpenAI. Model Spec, version 2025-10-27, accessed 2026-08-12.
  https://model-spec.openai.com/2025-10-27.html
- OpenAI. Introducing Structured Outputs in the API. 2024-08-06.
  https://openai.com/index/introducing-structured-outputs-in-the-api/
- Madaan et al. 2023. Self-Refine: Iterative Refinement with Self-Feedback.
  https://arxiv.org/abs/2303.17651
- Shinn et al. 2023. Reflexion: Language Agents with Verbal Reinforcement
  Learning. https://arxiv.org/abs/2303.11366
- Yao et al. 2023. ReAct: Synergizing Reasoning and Acting in Language Models.
  https://arxiv.org/abs/2210.03629
- Anthropic. Building Effective AI Agents. 2024-12-19.
  https://www.anthropic.com/engineering/building-effective-agents
- OpenAI Agents SDK documentation: running agents, tool errors, conversation
  state, and retries; accessed 2026-08-12.
  https://openai.github.io/openai-agents-python/running_agents/
  https://openai.github.io/openai-agents-python/models/
- Liang et al. 2022. Holistic Evaluation of Language Models.
  https://arxiv.org/abs/2211.09110
- Liu et al. 2023. AgentBench: Evaluating LLMs as Agents.
  https://arxiv.org/abs/2308.03688

## Related specs

- docs/agent-world-environment-generation.zh.md: source-of-truth authority;
  especially sections 3.6-3.7 and 10.2-10.3.
- .trellis/spec/agent_world/backend/index.md: provider schema exposure,
  deterministic validator diagnostics, no-progress, replay modes, and
  infrastructure retryability.
- .trellis/spec/guides/agent-llm-node-debugging.md: recipient-specific feedback,
  Direct no-Skill invariant, evidence-first diagnosis, and real-boundary proof.
- .trellis/spec/guides/foundry-product-alignment.md: a correction proof is not
  product completion.
- .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md and
  node-contracts.md: current R9 Local Correction versus later bounded-repair
  child boundary.

## Caveats / Not Found

- The canonical source and active R9 node contract do not fully agree on the
  breadth of correction feedback. The source-of-truth requires a complete safe
  issue frontier and clustered AgentCorrectionBrief
  (docs/agent-world-environment-generation.zh.md:428-445); R9 currently has
  one first-error CorrectionPacket and says JSON parsing never enters local
  correction (node-contracts.md:127-148). The source-of-truth wins. Resolving
  the implementation/design mismatch requires a real-failure diagnosis, a
  revised plan, and independent critic allow; this research record does not
  resolve it.
- The exact matrix is a policy recommendation constrained by Foundry's product
  contract. Papers and SDK documentation describe effective patterns and
  possible runtime behavior; they do not grant Foundry authority to retry,
  disclose data, grant permission, or publish.
- No model provider, Agent, tool, real execution proof, test suite, git
  operation, source edit, task plan edit, JSONL read/write, or PAC edit was
  performed. Historical task-local diagnosis records were read only as context,
  not treated as a new live failure.
- No empirical A/B result exists yet for the proposed message or optional prior
  output. The proposed evaluation must establish benefit and safety before a
  product claim.
