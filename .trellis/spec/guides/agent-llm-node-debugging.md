# Agent World Debugging and Execution Proof

Use the project-local agent-world-debugging Skill for every real Agent World
failure. Use agent-world-llm-remediation only after a real scene makes the
runtime Agent/LLM boundary a live hypothesis. Use
agent-world-real-execution-proof to select the actual proof after a change.

The goal is to advance a trustworthy stage from natural-language need to a real
programmatic environment, independent validation, and eventual Registry
release—not to make a mocked test or one model sample pass.

## Feedback means the next user wish

For every LLM/Agent correction, restate this before changing Prompt, Skill,
validator, or retry behavior:

> Feedback is a framework-authored next `user` message in the same node
> conversation. It keeps the original objective, frozen inputs, and output
> contract unchanged; names the safe observable problems and expected change;
> asks for one complete replacement rather than a patch or explanation; and
> requires a whole-result self-check.

Keep the rejected answer only as the previous ephemeral `assistant` turn. Do
not copy it into the Feedback or persist it in Artifact, Observe, Skill, or
memory. This is a bounded user-required exception to the safer general default
of omitting raw rejected output; retain only the immediately preceding final
proposal, use one declared continuation method, and make no efficacy claim
before a real-boundary proof.

"Same conversation" means the logical sequence `initial user -> rejected
ephemeral assistant -> Feedback user`. It does not authorize a Direct Provider
`instructions`/developer field, hidden server continuation, reused Agent
workspace/session state, or durable transcript. A stateless Direct route
reconstructs only the approved logical turns through its existing Prompt/input
surface. Tool results remain typed Agent-loop observations, not Feedback.
Framework code, not the LLM/Agent, owns whether another turn is authorized and
validates the complete replacement again.

Do not confuse four different loops: an Agent tool result is an in-session
observation; node-local correction is a same-contract user Feedback turn;
transport replay is the same request with no semantic Feedback; workflow Repair
creates a new Artifact revision after terminal failure. The default local
budget is one correction; any second correction requires explicit policy and
code-proven strict progress. The same normalized issue set stops.

An explicitly two-correction Direct node may spend its final bounded Feedback
after a format-first path, but proposal three is terminal and semantic-to-format
regression never unlocks it; this is bounded self-revision, not generic retry.

Feedback is compiled from actual validator/tool/runtime facts for one
recipient. Include continuity, all safely known same-frontier issues, the
complete-replacement action, and a self-check. Exclude raw exceptions, secrets,
hidden tests, policy, budget, owner, route, Gate, Judge, and release fields.
A safe parser subtype must be translated into a recipient-executable replacement or deletion action.
Observe remains a read-only safe account of what happened; it is not itself a
model prompt or control plane.

Full rationale and sources:
`.trellis/tasks/08-10-direct-foundry-minimal-dag/research/prompt-feedback-observe-retry-principles.md`.

## Keep the two Agent contexts distinct

The **project-execution Agent view** is for the Code Agent changing this
repository: active task, compact scene, stable index, and absolute or
repository-relative paths for on-demand reads. It is a project-navigation aid,
not a runtime role-Agent input or permission system.

A runtime model has one of two explicit contexts. A **Direct LLM** receives
only its rendered Prompt/input and authorized correction feedback; Runtime
Skill, hooks, tools, profile-owned instruction fields, and outbound Provider
`instructions` must be absent. A
tool-enabled **runtime role Codex Agent** receives its rendered Prompt/input,
the one actually mounted Runtime Skill, granted tools, model profile, and
authorized correction feedback. Do not repair one kind of context by changing
the other.

Keep durable logs, artifacts, traces, and state in the code-evidence layer.
Keep the project top-level view small and replaceable: current question,
known/unknown facts, and paths that answer the next questions. History belongs
in evidence, not in an ever-growing index or hook payload.

## Investigate before modifying

Read observe scene and the smallest related evidence. State what ran, what is
known, unknown, and what the runner proves. If the evidence cannot support a
useful hypothesis or a precise next read, feedback/observability is the first
defect; improve and prove it locally before changing semantics or retrying.

Explicitly mark these five surfaces as supported, weakened, or unknown:

1. project-execution Agent view;
2. effective runtime instruction/input;
3. Runtime Skill (Agent-only; its expected value for a Direct LLM is absent);
4. code / execution boundary;
5. feedback / observability.

They are lenses, not exclusive buckets. Give evidence for one first repair
target and only directly causal coupled changes. Route feedback by recipient:
the project Agent gets a safe narrative and local paths; the control plane gets
authority facts; a runtime role Agent gets a bounded correction story only when
authorized.

## Role-play the actual time-ordered path

When any Direct LLM or specialized Agent result is bad or confusing, invoke
`agent-world-roleplay-debugging` from the **project-execution Agent** before
changing Prompt, Runtime Skill, feedback, validator, or retry policy. It walks
the actual path against an Expected Behavior Sheet derived from project
authority, using durable event order to find the first deviation. A one-node
Direct Prompt/input → parser/validator loop is enough; extend it only when a
real output actually feeds a downstream node.

The Expected Behavior Sheet is only the reviewing Agent's comparison baseline;
it never becomes a participant-visible context unless an actual pre-step
handoff or source proves it was visible at that time.

This catches missing context, hidden acceptance conditions, stale Artifact
handoffs, feedback that cannot guide repair, and lifecycle/race errors that a
static source review hides. It is not a Runtime Skill, does not enter a model
profile, and does not prove that an invocation will succeed. Determine whether
each stage is Direct, tool-enabled Agent, or deterministic before looking for a
Prompt: a deterministic Integration gate has input/gate/feedback surfaces, not
an imaginary Agent Prompt.

Code is not the default owner merely because it is editable. Before changing
it, state what weakens or keeps live the project-view, runtime
instruction/input, the Agent-only Runtime Skill or the Direct no-Skill
invariant, and feedback explanations. If several repair mechanisms remain
credible, name the alternatives, choose the smallest coherent one, and record
the observation that would make you switch.

Every safe narrative states coordinate/phase, observed fact, known fact,
unknown fact, and the next permitted read or action. This is a useful feedback
shape, not a reason to add a global Schema for every error.

Treat a constructed boundary test as feedback too: state its node/owner,
frozen-input provenance, one poison, expected versus actual stable diagnostic
and terminal state, elapsed time, and last completed phase. A bare assertion,
opaque exception, or unexplained stall is a test/harness observability defect,
not evidence for a semantic retry.

When code / execution is live, name a concrete sub-lane: CLI/execution safety,
verifier/gate weakness, replay/resume/state, Runtime/Judge isolation,
legacy-command or ABI regression, or provider/transport. Do not collapse these
different failures into a generic “code bug.”

`sdk_session_open` with zero Provider events is a startup boundary, not model
behavior: the Prompt and Runtime Skill have not reached the model. Keep those
lenses unknown, inspect provider/profile/adapter and feedback first, and use an
explicitly diagnostic bounded redacted sidecar if the safe phase cannot name a
concrete next read. Runtime profiles deliberately expose no base/developer
instruction text; the Codex worker must omit those SDK fields rather than pass
an empty string or generic replacement. Prove that mechanical change on a real
Agent boundary before reattempting the frozen node.

The equivalent Direct case needs an equally safe transport fingerprint. A
body-less SDK exception must retain only a closed `connection` or `timeout`
class when its exception type proves one; do not retain exception prose, host,
proxy, request, or credential. `shape=missing` is not enough to choose a route.
If the control itself ran in a network-restricted test process, that proves only
the local process boundary. Repeat the identical minimal call on the actual
invocation host before diagnosing the API, Prompt, or Direct input.

## Select a repair from evidence

Possible choices include better project view/feedback, Direct Prompt/input
changes followed by fresh generation, an Agent-only Runtime Skill change,
authorized bounded model correction, model/profile/route/response-mode changes,
deterministic mechanics repair, or an explicitly evidenced transient retry.
Malformed JSON and missing fields do not prescribe one of these by themselves.

Before adding a contract, Hook gate, or fixed repair branch, ask what
deterministic harm it prevents, whether textual Agent reasoning would suffice,
what valid strategies it would forbid, whether the issue recurs, and which real
execution would prove improvement.

## Prove one point before the chain

- For deterministic code, feedback, validator, scheduler, projection, verifier,
  CLI, replay, resume, or isolation claims, first reproduce or extract one
  failing true-boundary execution before editing. If only a durable real event
  is available, record why it is sufficient and what post-change observation
  would falsify the repair.
- Run a constructed realistic input through the actual local boundary for
  feedback, validator, scheduler, code, verifier, CLI, replay, resume, or
  isolation claims.
- Test a project-view change with a fresh project-Agent navigation exercise;
  do not turn it into a runtime node test unless a runtime surface also changed.
- Run one isolated real node for Direct Prompt/input, Agent Runtime Skill, or
  model/profile claims; inspect its request shape to prove the Direct no-Skill
  invariant or the Agent's mounted bundle.
- Run the normal Scheduler for repair-loop claims.
- Chain immediate integration and then E2E only after the changed single point
  passes.

pytest, lint, and typing are regression guards, not replacement evidence for a
real boundary. Stop at the first new failure, read its scene, and begin a new
attribution.
