# Agent World Debugging and Execution Proof

Use the project-local agent-world-debugging Skill for every real Agent World
failure. Use agent-world-llm-remediation only after a real scene makes the
runtime Agent/LLM boundary a live hypothesis. Use
agent-world-real-execution-proof to select the actual proof after a change.

The goal is to advance a trustworthy stage from natural-language need to a real
programmatic environment, independent validation, and eventual Registry
release—not to make a mocked test or one model sample pass.

## Keep the two Agent contexts distinct

The **project-execution Agent view** is for the Code Agent changing this
repository: active task, compact scene, stable index, and absolute or
repository-relative paths for on-demand reads. It is a project-navigation aid,
not a runtime role-Agent input or permission system.

A **runtime role Agent** receives the product's effective runtime
instruction/input (rendered Prompt plus runtime input projection), Runtime
Skill, model profile, and authorized correction feedback. Do not repair one
kind of context by changing the other.

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
3. Runtime Skill;
4. code / execution boundary;
5. feedback / observability.

They are lenses, not exclusive buckets. Give evidence for one first repair
target and only directly causal coupled changes. Route feedback by recipient:
the project Agent gets a safe narrative and local paths; the control plane gets
authority facts; a runtime role Agent gets a bounded correction story only when
authorized.

Code is not the default owner merely because it is editable. Before changing
it, state what weakens or keeps live the project-view, runtime
instruction/input, Runtime Skill, and feedback explanations. If several repair
mechanisms remain credible, name the alternatives, choose the smallest coherent
one, and record the observation that would make you switch.

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

## Select a repair from evidence

Possible choices include better project view/feedback, runtime
instruction/input or Runtime Skill changes followed by fresh generation, an
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
- Run one isolated real node for runtime instruction/input, Runtime Skill, or
  model/profile claims.
- Run the normal Scheduler for repair-loop claims.
- Chain immediate integration and then E2E only after the changed single point
  passes.

pytest, lint, and typing are regression guards, not replacement evidence for a
real boundary. Stop at the first new failure, read its scene, and begin a new
attribution.
