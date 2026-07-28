---
name: agent-world-debugging
description: "Investigate any real Agent World failure or confusing result before changing code, runtime instruction/input, Runtime Skills, profiles, feedback, or retrying. Use after a failed node, weak observe scene, unexpected CLI/runtime/verifier behavior, unclear test result, or when the current project-execution Agent lacks enough orientation to form a hypothesis. Use text-first evidence exploration and real single-boundary proof; do not turn uncertain Agent reasoning into unnecessary deterministic contracts."
---

# Agent World Debugging

Use this as the master investigation Skill for runtime Agent nodes and ordinary
project failures alike. A patch, retry, or E2E run is not a diagnosis.

The project goal is not a green sample or a convenient test. Advance one
trustworthy stage of the path from a natural-language need to a real
programmatic environment, independent validation, and eventual Registry
release. Never manufacture that progress with mock outputs, hand-injected
Artifacts, fixture/replay success paths, or a host fallback.

Keep two different Agents separate:

- The **project-execution Agent** is the Code Agent changing and debugging this
  repository. Its project view is an index, active-task context, observe
  summary, and local path map.
- A **runtime role Agent** is the product's invoked model. Its inputs are its
  effective runtime instruction/input, Runtime Skill, runtime context
  projection, profile, and
  correction feedback.

The first is not a smaller version of the second. A project path map does not
alter a runtime model's context; a runtime Prompt change does not repair a
project Agent's inability to find the relevant source file.

## Start from a real event

Before modifying or retrying:

1. Read the safe observe scene.
2. Read the smallest related event, artifact, source, or state record needed
   to understand the chronology.
3. State what ran, what definitely happened, what is unknown, and what the
   current runner can and cannot prove.

Do not promote a label such as timeout, invalid JSON, missing field, or failed
pytest assertion into a root cause. If the scene and available evidence cannot
support two plausible explanations or one precise next read, feedback and
observability are themselves the first defect. Improve that boundary and run a
real local proof of the improved feedback before changing semantics or
retrying.

For deterministic code, feedback, validator, scheduler, projection, verifier,
CLI, replay, or resume claims, first extract or construct one failing execution
of the true boundary before editing. If the durable real event is already the
only credible failing proof, record why a constructed reproduction would add no
evidence and name the exact post-change observation that could falsify the
attribution.

If the evidence exists but the project-execution Agent cannot locate or
interpret it without broad repository searching, invoke
agent-world-agent-view-stewardship. That is a project navigation problem, not a
runtime Agent-context change.

## Establish timeout liveness in layers

Treat `hard_timeout` as a parent-side observation, not a diagnosis of the
model or Provider. Before changing a timed-out runtime node, establish the
first failing layer in this order. Do not skip a lower layer merely because the
node has a large Prompt or expensive output contract.

Treat first-progress and first-write as observations, not independent short
death clocks for a real Agent/LLM invocation. Do not install a diagnostic
60-second-style deadline merely to force a quick result; retain the declared
logical envelope and distinguish an absent Provider event from a true Provider
terminal, owner-process loss, or configured parent terminal.

1. **Raw Provider control:** issue one tiny real request through the target
   model and configured Provider route. Keep the prompt harmless and the
   expected semantic result trivial, but inherit the configured logical
   envelope: do not add a diagnostic input, output-token, or short-timeout
   ceiling. Retain only a safe terminal class, elapsed time, completion state,
   and output length or exact predicate. Never print or persist a credential,
   base URL, raw request, or raw response.
2. **InvocationBackend control:** issue one tiny real request through the
   same adapter family as the node (for example, Codex SDK/app-server), with a
   minimal resolved profile and the same model/route. This proves or falsifies
   worker spawn, profile materialization, SDK/app-server startup, transport,
   and strict-output handling independently of the business node.
3. **Frozen node proof:** only after controls pass, execute the exact frozen
   node once. This is the first execution that can support an attribution to
   its runtime instruction/input, Runtime Skill, node profile, feedback, or
   semantic output boundary.

Run each control where its intended route is actually reachable. A command run
in a no-network sandbox cannot prove a remote Provider timeout; record that
execution-environment mismatch and repeat the same configured-envelope control
in the authorized network context. Likewise, a shell invocation with no captured
terminal result is not evidence that a model call occurred.

Interpret only the first failed layer:

- Raw Provider control fails: investigate credential/routing/network/provider
  availability before adapter, Prompt, Runtime Skill, or node code.
- Raw Provider passes but InvocationBackend control fails: investigate the
  SDK, app-server, worker lifecycle, adapter, profile materialization, or
  transport boundary; do not retry the business node.
- Both controls pass but the frozen node fails: inspect the exact node's
  effective runtime instruction/input, Runtime Skill, node profile, parser,
  feedback, and semantic output before choosing a repair.

This ladder is a control experiment, not a substitute for the node proof. It
narrows the owner; it does not certify the full pipeline.

## Make attribution explicit

Before choosing a repair, give each primary surface a status of **supported**,
**weakened**, or **unknown**, with the evidence that earned that status:

1. **Project-execution Agent view:** Does the project index, active-task
   summary, scene, and local path map let the Code Agent choose the next read?
2. **Effective runtime instruction/input:** Does the rendered Prompt **and**
   the runtime input projection express the actual requirement and disclose the
   needed frozen facts at the required scope?
3. **Runtime Skill:** Does the role Skill provide a usable method, self-check,
   or repair habit?
4. **Code / execution boundary:** Are parser, schema, compiler, validator,
   scheduler, adapter, model route, response mode, timeout, upstream input,
   or harness behavior responsible?
5. **Feedback / observability:** Does the scene or correction narrative make
   the failure intelligible enough for the intended recipient to act?

These are lenses, not exclusive owner buckets. A Prompt omission can cause a
feedback gap; a profile change may be coupled to an adapter change. State one
first repair target and only the directly causal coupled surfaces. Do not
change all five merely because the event is frustrating.

Do not start with code merely because code is easiest to edit. Before a code
change, say what keeps the project-view, runtime-instruction/input, Runtime
Skill, and feedback explanations live or weakens them. Conversely, do not
infer a Prompt or Skill defect when no semantic candidate reached the relevant
boundary. If several repair mechanisms remain credible, list the alternatives,
choose the smallest coherent one, and name the observation that would make you
switch strategy.

Do not write “Prompt audited” or “Skill audited” without a locator. For every
live surface, record the exact coordinate and rendered projection/path/profile
read, the evidence for its status, and either the falsifying observation or
the next precise read that would change the status.

When code / execution is live, name its specific sub-lane instead of saying
only “code”:

- **CLI / execution safety:** Does the actual command use uv and the intended
  execution path, avoid generic shell-runner success paths, and keep secrets
  out of arguments and artifacts?
- **Verifier / gate weakness:** Does the gate prove real runtime behavior
  rather than a schema, mock, fixture, or superficial replay?
- **Replay / resume / state:** Does recovery use live state correctly without a
  fixed replay case, stale ABI, or fixture registry becoming a success path?
- **Runtime / Judge isolation:** Did the intended isolated process or boundary
  run, rather than silently falling back to host behavior?
- **Legacy-path regression:** Did a command or compatibility route accidentally
  preserve the retired awm CLI or runtime ABI v1 path?
- **Provider / transport:** Are route, response mode, timeout, lease, retry,
  and upstream availability the actual liveness boundary?

A useful attribution is prose, for example:

> Feedback is supported as the first defect: the scene says validation failed
> but names neither the coordinate nor the rejected condition. Prompt and
> Runtime Skill remain unknown because that omission prevents a focused read.
> The first change is a safe validation narrative; no model retry is justified
> yet.

## Route feedback to the recipient who can use it

Feedback is not just an error string. Give each recipient the smallest useful
story:

- **Project-execution Agent:** safe scene, knowns/unknowns, and local paths to
  evidence, effective runtime-instruction/input and Runtime Skill surfaces,
  profile, and implementation.
- **Control plane:** authorization, budget, attempt, and settlement facts. It
  authorizes a correction; it does not invent a semantic correction.
- **Runtime role Agent:** only an authorized, bounded correction narrative:
  what failed, what remains frozen, what may change, and what a complete
  replacement must achieve.
- **Human:** only a decision that needs human authority, ambiguity resolution,
  credentials, or release policy.

Before routing, express the safe story in five parts: coordinate and phase;
what happened; what is known; what remains unknown; and the next permitted
read or action. This is a recipient-facing narrative, not a demand to turn
every failure into a new global Schema.

Do not send opaque diagnostics straight to the runtime model. Do not ask a
runtime model to repair an adapter, timeout, route, or authorization defect as
though it were a semantic revision.

## Make test evidence actionable too

A constructed boundary exercise or regression is also feedback for the next
project-execution Agent. Its failure output must identify the node/boundary and
current owner lens; frozen-input or committed-closure provenance; the one
poisoned condition; expected versus actual stable code/path/condition/category
and terminal state; and elapsed time plus the last completed phase. A bare
assertion, opaque exception, or unexplained stall is a test/harness feedback
defect. Repair that diagnostic boundary and prove it locally before using the
result to steer a semantic runtime-instruction/input, Runtime Skill, or
contract change.

## Choose a repair strategy from evidence

Pick the smallest coherent strategy; do not use a fixed error-label table.

- Improve the project Agent view or feedback when the current investigation
  cannot distinguish meaningful causes.
- Change the effective runtime instruction/input, Runtime Skill, or model
  profile, then make a fresh generation only after that causal change.
- Use an authorized bounded correction turn when a localized candidate is
  coherent, feedback is precise, and preserving valid work is useful.
- Change route, response mode, budget, timeout, adapter, parser, validator,
  scheduler, or upstream input when the execution boundary is the cause.
- Use deterministic code for deterministic ownership: framework IDs, ordering,
  wrappers, serialization, authority, or a known control-plane/validator bug.
  Do not fill in business semantics merely because one sample was incomplete.
- Retry only for an explicitly evidenced transient condition, with the retry
  policy recorded. A repeat of an unexplained failure is not an experiment.

Malformed JSON, a wrong envelope, or missing fields can justify any of several
strategies: clearer runtime-instruction/input or Runtime Skill guidance and
regeneration, a bounded format correction, a profile/response-mode change,
adapter repair, or better feedback. Let the observed boundary decide; do not
hard-code the symptom into one remedy.

Before adding a permanent contract, Schema rule, Hook gate, or fixed repair
branch, ask:

1. What concrete harm requires deterministic enforcement?
2. Could better textual context, runtime instruction/input, Runtime Skill,
   feedback, or Agent reasoning solve it?
3. Which valid strategies would the rule forbid?
4. Is this a recurring invariant, or only a sample/model quirk?
5. What real execution would show that the rule improves the system?

## Audit the whole live mechanism, then prove one point

Once the cause is credible, inspect all effective homologous surfaces before
the next live call: rendered runtime-instruction/input projections, Runtime
Skill versions, profiles, parser/validator/compiler paths, feedback renderers,
and sibling nodes using the same mechanism. A single omission often has
siblings.

Then hand off to agent-world-real-execution-proof:

- construct realistic frozen input and execute the real local boundary for
  deterministic code, feedback, validator, projection, verifier, CLI, replay,
  resume, or isolation claims;
- run one real isolated runtime node for runtime instruction/input, Runtime
  Skill, profile, route, or model-behavior claims;
- use the normal Scheduler with repair authority for repair-loop claims;
- run immediate integration and then E2E only after the changed single
  boundary passes.

pytest, typing, lint, and projection checks are useful regression guards. They
do not replace the affected real boundary. Stop at the first new failure, read
its new scene, and begin a new attribution rather than continuing the chain.

## Finish honestly

Leave a short record:

> I observed … . The live explanations were … . The project view was
> sufficient/insufficient because … . I changed … rather than … because … .
> This focused execution proves … and does not yet prove … .

Do not claim repair-loop, integration, release, or E2E success from a single
node result.
