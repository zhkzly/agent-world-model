# Task Curriculum E2E Diagnostic Fidelity — Design

## Decision

Advance exactly one causal boundary: the TaskCurriculum node. First establish
whether the isolated-test mechanism can create a real downstream dispatch from
the committed diagnostic WorldRules result. Only after that plumbing is proven
do we interpret a TaskCurriculum proposal result as runtime instruction/input,
Runtime Skill, code, or
feedback evidence.

## Node boundary

```text
committed diagnostic WorldRules
    + Architecture + EvidenceGraph
    -> TaskCurriculumLeaf
    -> TrainingSemanticSourceDraft
    -> compile_training_semantics
    -> ValidationReport / FeedbackEvaluation / WorkCommit
    -> design.task_curriculum_source (diagnostic-only)
```

The model owns task-family meaning, objectives, actor/tool scope, difficulty,
and task-specific success/failure/terminal semantics. The framework owns
frozen-world binding, schemas, mechanical identities, compiler closure,
validation, repair authority, and release authority.

## Five-way audit order

| Owner | Evidence required | Correct repair |
|---|---|---|
| Project-execution Agent view | The Code Agent cannot choose a needed current-task/evidence read without broad repository search. | Correct only the smallest project path map or task orientation; paths do not alter runtime access. |
| Feedback / observability | No stable safe diagnostic or no bounded terminal progress information | Repair safe diagnostics, scene/frontier or harness reporting first |
| Code / execution | Complete valid constructed source fails on framework-owned mechanics, diagnostic successor dispatch is impossible, or resolved profile/capability behavior is wrong | Refactor deterministic compiler/scheduler/profile boundary with regression |
| Effective runtime instruction/input | Frozen task/world context or structural instruction is missing from the rendered Prompt or runtime input projection | Fix this node's effective runtime instruction/input only |
| Runtime Skill | Runtime instruction/input and code/execution are sufficient but Engineer guidance lacks reusable task-authoring constraints | Amend only the Engineer Skill |

A project-execution Agent view is distinct from the runtime role Agent's
instruction/input. The former is a compact project task/path map for the Code
Agent. The latter is what the invoked model actually receives. Resolved runtime
capabilities remain deny-by-default and belong to code/execution, not to the
project view. No row is selected because a live call merely failed.

## Diagnostic-successor feasibility

The previous diagnostic run has a committed `world_rules` head, while the
captured source has no `task_curriculum` head. The legacy `test-node` contract
archives a persisted target head before a real rerun, which is appropriate for
rerunning a historically attempted coordinate but may exclude the next frozen
definition.

The first test is therefore deterministic: feed the marked WorldRules
diagnostic state into the real test-node resolver for the already-frozen
TaskCurriculum coordinate. If it cannot resolve a head, the defect is a
diagnostic scheduling/feedback contract: the framework cannot perform the
user-required sequential isolated proof. The minimal fix must create one fresh
diagnostic successor attempt from the existing graph manifest and committed
parents; it must not synthesize a success, mutate the source state, or grant
release authority.

If the mechanism already supports the coordinate, retain it and move directly
to the leaf/compiler constructed-input proof. Do not change infrastructure on
speculation.

## Test design

1. Start from the frozen WorldRules diagnostic closure or equivalent complete
   typed construction, not a partial mock.
2. Exercise `TaskCurriculumLeaf` and `compile_training_semantics` together
   with a valid `TrainingSemanticSourceDraft`.
3. Poison exactly one condition at a time (for example an unknown frozen rule
   reference, invalid actor/tool binding, or a framework-owned identity), and
   assert safe code/path/condition/category and owner actionability.
4. If a scheduler extension is needed, test source immutability, one target
   dispatch, committed-parent closure, diagnostic marker retention, and
   `releasable=false` explicitly.
5. Inventory every homologous source/compiler/runtime-instruction-input/Skill
   location if one
   owner gap is confirmed.
6. Run one real grok-4.5 invocation only after the deterministic proof.

## Live-result decision table

| Real result | Next action |
|---|---|
| `committed` / passed | Record only this node as proven; advance to ModelingBoundary later |
| typed proposal failure | Use exact code/path to select runtime instruction/input, Runtime Skill, or semantic contract owner |
| generic feedback | Stop semantic work and repair feedback first |
| infrastructure / timeout / interruption | Inspect liveness/transport boundary; do not modify task semantics |
| no progress / oscillation | Stop and record causal blocker rather than retrying |

## Safety boundaries

- All diagnostic work remains marked `diagnostic_only=true` and
  `releasable=false`.
- The live invocation uses `InvocationBackend`, never a direct HTTP shortcut.
- No task source, WorkCommit, provider payload, or output is hand-injected.
- Broad pytest is supplemental; an opaque or stalled test must be repaired as
  a test-feedback problem before it guides an LLM repair.

## 2026-07-26 audit record

The first deterministic probe against the marked WorldRules diagnostic state
returned `test_node_coordinate_not_found`: normal `test-node` correctly
requires an existing terminal target head, while the frozen TaskCurriculum
definition has never run. A constructed three-node WorkGraph regression then
proved the missing diagnostic capability and now dispatches exactly one
unheaded frozen descendant from committed parents in a fresh marked child
copy. It preserves the immutable parent, uses the ordinary Scheduler, and
keeps every new artifact diagnostic-only and non-releasable.

The TaskCurriculum semantic audit selected three real owners before any new
provider call:

| Owner | Evidence | Required correction |
|---|---|---|
| Runtime instruction/input | The active `_curriculum_prompt` names only “task Rules”; it omits source section families, `task_goal` restrictions, sampling restrictions, and Rule-ID ownership. | State the exact semantic sections and forbidden/required sources in every active projection. |
| Engineer Skill | The skill defines WorldRules ID ownership but has no TaskCurriculum equivalent. | Add reusable task/sampling Rule ownership and closed-world guidance. |
| Code / feedback | `compile_training_semantics` accepts Agent `rule_id` values for sampling and task Rules; multiple reachable bare `ValueError` paths collapse to `framework_diagnostic_incomplete`. | Canonicalize source IDs, derive deterministic IDs, persist only canonical source, and make the affected compiler feedback stable and field-addressable. |
| Runtime input/capability profile | The exact TaskCurriculum profile is tool-free; its runtime input has only `world` and `claims`, while the Engineer Skill is injected as developer instruction. This is not the project-execution Agent view. | No access expansion: prove the two required input projections and TaskCurriculum Skill are present, while broader network/tool permissions remain discarded. |

The scheduler diagnostic itself was complete (`test_node_coordinate_not_found`)
and therefore classified as a code/contract limitation rather than a runtime
instruction/input or
feedback defect. The TaskCurriculum semantic changes remain blocked on the
complete same-boundary inventory above; no Grok invocation has been retried.

### 2026-07-26 addition: runtime-input/capability classification

Future runtime audits begin by reading the exact runtime input projection and
effective capability profile mounted for the node. A change is permitted only
when a concrete required frozen fact is missing/stale/contradictory in the
input, or when the deterministic capability profile is wrong. The corresponding
test must prove the necessary input or capability behavior and continued
exclusion of unrelated runtime access. It is never valid to widen a runtime
profile merely to make a model sample more likely to pass.

The constructed compiler proof also found and corrected one feedback-boundary
bug: `StructuredValidationError` is a `ValueError`, so a raw-ValueError fallback
must explicitly preserve pre-existing structured errors. The regression poisons
one TaskCurriculum family and asserts its original stable code/path survives
the final compiler boundary rather than being relabeled as a framework error.

### 2026-07-26 addition: first real TaskCurriculum result

The first isolated `grok-4.5` TaskCurriculum execution reached the real
`TaskCurriculumLeaf -> InvocationBackend` boundary, but its direct structured
operation terminalized as `agent_backend_direct_timeout` after 120,408 ms. No
proposal artifact was generated. The safe scene named the backend terminal
failure but did not expose elapsed time, proposal/validation phase, or the last
completed operation; those facts required a manual durable-telemetry lookup.

This is not evidence for a project-execution Agent-view, runtime
instruction/input, or Engineer-Skill repair:
the model did not return semantic output for the compiler to assess. It selected
two same-boundary framework corrections before another invocation:

1. Scene projection now renders only durable attempt/operation timing,
   terminal failure phase, and last completed phase. Its constructed regression
   uses the real `WorkAttempt -> OperationRun -> FeedbackEvaluation` boundary
   and deliberately has no proposal artifact.
2. `IsolatedAgentProfileProvider` no longer uses the Engineer *role* as a
   timeout class. Structured Designer calls use their explicit structured
   budget, while Builder codegen retains its independently supplied per-turn
   budget. A regression proves 900 s structured TaskCurriculum and 120 s
   Builder codegen remain distinct under the same Engineer role.

The next and only permitted rerun uses a new ignored diagnostic configuration:
global ceiling 2,700 s, structured ceiling 900 s, codegen ceiling 120 s. The
900 s value is bounded and is causal (the observed timeout was 120 s); it is
not a retry-policy or semantic prompt change. Its terminal safe scene must be
read before any further action.

### 2026-07-26 addition: bounded Grok result and transport-feedback repair

The 900 s Grok rerun was one causal diagnostic execution, not a blind repeat.
It ran for 229,614 ms—therefore it proved the prior 120 s role-based truncation
was removed—but then terminalized as
`agent_backend_direct_structured_output_invalid_json`. It produced no proposal
artifact. The new scene correctly reported attempt elapsed time, first progress,
proposal failure duration, and validation as the last completed phase.

The resulting failure still lacked enough safe transport detail to choose a
semantic owner: `invalid_json` alone did not distinguish a Markdown wrapper,
truncation, non-JSON gateway text, or an invalid nested envelope. The current
owner decision is therefore:

| Owner | Evidence | Decision |
|---|---|---|
| Runtime input/capability profile | The proven tool-free, deny-by-default TaskCurriculum profile is unchanged and all required frozen facts remain in the runtime instruction/input. | No runtime input or capability expansion. |
| Runtime instruction/input / Engineer Skill | No parseable proposal reached Pydantic or the semantic compiler. | Do not edit semantic guidance from this result. |
| Code / transport | A completed strict Responses call returned non-JSON despite its outer JSON-schema contract. | Treat the Grok route as incompatible with this required structured boundary until a different route proves otherwise. |
| Feedback | The terminal code had no safe parse-shape/cause/offset information. | Repair first; no provider transcript may be retained. |

The repair adds a common direct-structured diagnostic contract used by both
Designer one-shot and Judge verifier-batch leaf paths. It persists only a closed
response shape, parse class, offset and character count; tests prove a provider
canary never reaches result, Artifact or scene. Completed malformed JSON and
malformed envelope terminals are explicitly non-retryable, while real timeouts
remain explicitly retryable only through Scheduler authority.

No third Grok invocation is permitted: the current evidence establishes that
Grok can execute but did not honor the strict structured-output requirement for
this actual node. After deterministic gates, the next distinct real execution
is the same frozen TaskCurriculum coordinate through the user-prioritized
`gpt-5.3-codex-spark` profile with the same bounded 900 s structured budget.
Its scene will decide the next owner; `gpt-5.4-mini` remains the next fallback
only if that route cannot satisfy the boundary.

### 2026-07-26 addition: TaskCurriculum fan-out decision

The first Spark execution reached the real provider and terminalized with
`direct_output_limit` at the frozen 65,536 token policy. A safe static audit
then established that this is not task-instance generation, but it is still an
over-broad single Agent transaction: the prompt currently includes a 70,963
byte frozen context and asks one response to author the entire curriculum plan
plus every task family's Rule IR. The wire model permits up to eight task
families, 64 Rules in each of three evaluator sections per family, and 128
sampling Rules. The frozen world itself is modest (four tools, three
invariants, two state entities, 33 existing World Rules), so the broad
transaction—not an unbounded world—is the confirmed structural concern.

Replace that opaque whole-curriculum call with this explicit, durable fan-out:

```text
WorldRules
  -> CurriculumPlan (one small Agent proposal)
  -> TaskRequirement[task_type] (one Agent proposal per plan entry)
  -> TaskCurriculum join (deterministic compile and closure validation)
  -> ModelingBoundary
```

Framework code derives the physical `TaskRequirement` coordinates only after
the committed CurriculumPlan fixes the ordered task types. It may schedule the
children sequentially under the declared budget initially; each remains an
independent WorkDefinition, WorkAttempt, telemetry span, feedback report, and
repair decision. No hidden loop inside one Scheduler leaf may spend multiple
unobservable Agent turns. The join retains the existing
`design.task_curriculum_source` boundary so Builder and downstream contracts do
not receive a partially assembled curriculum.

This changes the topology, not merely the prompt: a new non-releasable
intermediate graph epoch must retain WorldRules and CurriculumPlan before the
derived task-family graph can be frozen. A higher output-token diagnostic may
remain available as a separate, explicitly recorded policy experiment, but it
is not the default remediation for the confirmed over-broad node boundary.

### 2026-07-26 addition: final Build timeout and staged concurrency

The first real `build.candidate_build` invocation against the committed
Modeling and VerifierPlan closure reached the Engineer through the real
`InvocationBackend`, recorded first provider progress at 129,149 ms, and then
terminalized at 131,443 ms as `hard_timeout`. It produced no candidate
proposal. The safe scene and provider telemetry identify the parent-side
deadline as the observed terminal boundary; the selected diagnostic profile set
`environment_codegen_invocation_timeout_seconds = 120` despite the final Build
definition owning a 1,200-second wall/build budget. That is not yet proof that
the Provider itself timed out: the same symptom can arise from a slow model,
SDK-worker bootstrap/transport stall, response handling after model output, or
another Builder lifecycle defect.

The owner decision is explicit: project-execution Agent view and feedback are
sufficient (they point directly to the durable scene, timing, and adapter
message); runtime instruction/input and Runtime Skill remain unknown because
no semantic output reached either; execution/transport is a live hypothesis,
with the 120-second configuration proven only as the immediate deadline. Under
the user's explicit authorization to allow a longer real build, the next
single-boundary proof uses a separate ignored profile with a 900-second Builder
ceiling and the same model, token budget, frozen closure, transport, and
single-provider capacity. It is a discriminating execution, not a semantic
retry or a Prompt/Skill edit. Its terminal evidence must first distinguish a
real Provider timeout from a worker/adapter/Builder lifecycle defect; if it
does not, the permitted next experiment is one tiny same-backend/profile
InvocationBackend probe rather than another Build.

The final graph makes `Build`, verifier batch 1, and verifier batch 2
independent only after the Design and VerifierPlan closure. This proof keeps
capacity at one until Build has a truthful terminal result. After individual
Build and batch proofs, a separate controlled wave may raise provider capacity
and prove concurrent sibling leases/commits; `Integration` still depends on a
committed Build, and release gates wait for both Build/Integration and the
deterministic verifier-batch aggregate.

### 2026-07-27 addition: Agent workspace proof and feedback gap

The authorized isolated `gpt-5.4-mini` Build rerun used the same frozen final
closure after both a raw Provider control and the same `InvocationBackend`
control completed successfully. It terminalized after 207,595 ms with no
candidate proposal. This is not evidence that the Engineer lacks a working
directory: a separate real Agentic probe using the same Engineer profile,
workspace-write capability, Codex route and structured terminal contract
created and framework-verified `candidate/agent_workspace_probe.txt`.

The full Build's durable evidence instead establishes the following five-way
attribution before any third Build retry:

| Surface | Status | Evidence / next meaning |
|---|---|---|
| Project-execution Agent view | weakened | The existing scene omits the child Runtime-Agent liveness and the Builder workspace heartbeat, so a Code Agent cannot distinguish “no workspace action” from a dead or silent invocation without direct SQLite/artifact inspection. |
| Effective runtime instruction/input | live but unproven | The full Builder instruction asks one turn to read all frozen inputs, implement the complete candidate, test it, and serialize a completion. The small write proof does not prove this monolithic transaction is usable. |
| Engineer Runtime Skill | live but unproven | The Engineer Skill is large and its Build-specific method arrives late; no semantic candidate exists from which to select a Skill correction. |
| Code / execution | supported sub-lane | The Build has no explicit durable substage between “entire candidate” and terminal completion. The Agent stream had first and continued progress, but candidate workspace heartbeats remained at zero files/bytes. |
| Feedback / observability | confirmed first defect | The child invocation span recorded start, first progress and last progress, and the Builder wrote eight content-free workspace heartbeats; the scene rendered none of them. The terminal envelope also omitted a closed Codex error kind, but the worker classified opaque provider text as Provider unavailability. |

The first correction is therefore narrow and non-semantic: project only safe
Runtime-Agent liveness and candidate-workspace heartbeat facts into the scene,
and preserve an absent/unclassified closed terminal discriminator as unknown
rather than asserting Provider unavailability. This does not broaden any
runtime permission, retain a transcript, change the frozen Build input, or
authorize a retry. It must be proved using the actual
`WorkAttempt -> ProposalExecution -> Telemetry -> SceneProjector` boundary and
by reprojecting the existing durable Build trace. Only then may the full Build
instruction/Skill be redesigned into explicit durable stages.

### 2026-07-27 addition: wrong-workspace hypothesis and activity feedback

Before changing the Builder prompt, the "Agent wrote to a different directory"
hypothesis was checked against the exact failed isolated profile.  The worker,
Codex thread, and turn all set their cwd to the same resolved workspace; its
write capability is scoped to that workspace; and the full attempt's complete
`.agent-runtime` tree contains only framework inputs/control files and no
Agent-created candidate either under `workspace/candidate/` or elsewhere in
the materialization root.  A prior real same-profile workspace-write probe
created its file exactly at `workspace/candidate/agent_workspace_probe.txt`.
The path contract is therefore supported, not a reason to redirect the
Builder's output path.

The remaining feedback gap is finer-grained: the historic failed turn retained
only a total notification count, so it cannot tell a project-execution Agent
whether the live role Agent was emitting reasoning, command, file-change,
tool, message, or unclassified protocol events.  The next deterministic
change records only fixed, content-free protocol activity-category counters
and projects them as optional scene facts.  It deliberately retains no raw
command, filename, item id, prompt, tool argument, or transcript.  Its proof
is one constructed `WorkAttempt -> ProposalExecution -> Telemetry ->
SceneProjector` boundary plus one real isolated workspace-write probe; the
historic trace must remain explicitly `activity unavailable`, rather than
being retroactively guessed from its old method-name metric.

### 2026-07-27 proof: resolved-workspace path and safe activity projection

The actual same-boundary proof is now complete; it is deliberately narrower
than Build and is not an E2E success claim.  The opt-in live regression
`test_real_engineer_write_stays_in_resolved_workspace_and_emits_safe_activity`
uses the real `gpt-5.3-codex-spark` `InvocationBackend` route, an
`environment-engineer` workspace-write profile, the real Codex SDK worker,
and a fresh isolated logical workspace.  It asks for one small file beneath
`candidate/` and a closed `{status: ok}` completion envelope.

The real turn passed in 25.79 seconds.  The test verified both that
`workspace/candidate/agent_workspace_probe.txt` existed with its per-turn
random content and that the persisted telemetry retained no copy of that
content.  Its safe activity aggregates were 30 notifications: 8 reasoning,
4 agent-message, 6 command, and 12 unclassified.  A command notification is
not treated as proof of a successful write; the file assertion is the write
proof.  Conversely, the successful write is not treated as proof that a full
Build transaction is healthy.

Rebuilding the original failed Build scene from the durable marked diagnostic
state now yields these safe facts for the exact Build coordinate:

- Runtime Agent liveness: started at 854 ms, first progress at 1,366 ms, last
  progress and terminal at 208,450 ms, with 127 observed notifications.
- Activity classification: unavailable, because that historical worker did
  not persist typed SDK item categories.  The projector does not infer them
  from a method-name substring.
- Builder workspace terminal heartbeat: `turn_terminal`, 0 files, 0 bytes at
  208,450 ms.

This closes the path-contract question: the real agent can write at the
expected location and the failed Build did not leave an Agent-created file in
any allowed materialization location.  The next open question is not path
selection; it is why the monolithic Build made no durable progress before its
terminal result.  Therefore the next work is a complete effective
Builder-Prompt/Engineer-Skill/Builder-stage audit before any full Build retry.

### 2026-07-27 design: narrow the Build input and make planning a durable node

The completed audit rules out two tempting but unsupported diagnoses.  A
`gpt-5.3-codex-spark` Engineer control read the exact four frozen Build input
files, computed their hashes, and wrote an exact candidate-local summary in
55.29 seconds.  It terminalized normally with safe reasoning/command/message
activity.  Therefore neither the workspace path nor ordinary access to the
158,266-byte frozen input closure explains the failed 208-second Build.

The current Build transaction nevertheless has three independently evidenced
structural problems:

1. Its effective Prompt asks one turn to inspect all inputs, decide a project
   layout, implement runtime and materializer, lock dependencies, write tests,
   run checks, clean output, and serialize a complete final declaration.
2. The input projection redundantly sends `WorldSpec` inside the 83,406-byte
   `environment-design.json` and again as the 63,261-byte `world-spec.json`.
   The latter is byte-for-byte the nested WorldSpec projection.
3. The workspace-write Build profile loads the 14,113-byte general Engineer
   Skill, whose earlier design/WorldRules/Task authoring material is irrelevant
   to code generation.  The historic event contains no proof of which Skill
   sections were read, so this is a causal burden to reduce, not an assertion
   that the model misunderstood one particular line.

The selected remediation is deliberately **not** an in-place correction (no
candidate exists) or a hidden multiple-turn loop.  It is one new durable,
non-authoritative physical node before candidate code generation:

```text
ModelingBoundary
  -> BuildImplementationPlan (real read-only Engineer Agent)
  -> CandidateBuild (real workspace-write Engineer Agent)
  -> Integration
```

`BuildImplementationPlan` compiles the deterministic
`ImplementationContract`, stages the minimal Builder-visible input projection,
and returns a small text-first `ImplementationPlanDraft`.  Framework wraps it
with the exact Design and ImplementationContract refs in a
`build.implementation_plan` Artifact.  The text is advisory only: it cannot
change WorldSpec, task semantics, budget, permissions, release, candidate
validation, or scheduler routing.  CandidateBuild receives the committed plan
as an explicitly labeled advisory input and must still satisfy the frozen
inputs and deterministic workspace validation.

The minimal codegen input projection is:

```text
inputs/world-spec.json
inputs/curriculum.json
inputs/implementation-contract.json
inputs/task-materializer-output.schema.json
inputs/implementation-plan.md       # only after a committed plan
```

It removes the full `EnvironmentDesign` container, reward, verification,
evidence/ref metadata, and the duplicate WorldSpec while retaining the exact
world behavior, task requirements, code contract, and output schema that the
candidate needs.  It is a runtime-input reduction, not a new semantic source
of truth; every file is still deterministically projected from the frozen
EnvironmentDesign and exact ImplementationContract.

The Runtime Skill is split by node rather than role: the plan node gets a
short read-only planning Skill, CandidateBuild gets a short codegen-only
Skill, and existing structured Designer nodes retain the general Engineer
Skill.  Capability ceilings and all profile permissions remain unchanged.

Proof order is mandatory:

1. Constructed WorkGraph/Scheduler/leaf tests establish the new plan node,
   exact parent closure, plan-to-build dependency, input projection, and no
   candidate writes in the read-only planning node.
2. A real isolated `BuildImplementationPlan` execution against the frozen
   closure must terminalize with a readable safe scene before CandidateBuild
   is attempted.
3. Only then can the new CandidateBuild boundary run once.  Its scene and
   workspace heartbeat decide whether another layer needs remediation.

### 2026-07-27 design: logical 5M Build budget versus physical Provider turns

The first real CandidateBuild under the authorized 5,000,000-token / eight-hour
envelope did not hit the configured task budget.  It emitted 126,104 measured
tokens and then the Codex route returned the closed terminal signature
`Incomplete response … max_output_tokens`.  The Agent had created a real
23-file candidate workspace, so this is neither a no-workspace hypothesis nor
a semantic completion.  It is a Provider-owned physical-turn boundary.

The correction must not disguise this as a short task budget, a transient
transport retry, or a hidden Builder loop.  The chosen model is:

```text
one logical CandidateBuild session: 5M tokens / parent wall envelope
  -> explicit physical turn 1 (own WorkAttempt, Proposal, Validation, Feedback)
  -> if and only if the closed output-ceiling signal plus a resumable session exist:
       explicit session-continuation authority and private checkpoint
  -> explicit physical turn 2 against the same thread/workspace
  -> ...
```

Every physical turn is independently durable and observable.  A continuation
is not a semantic correction and does not expose raw Provider prose to the
runtime Agent.  Its maximum number of turns is derived from the declared
logical session budget and the configured Provider physical-turn envelope;
the global token, Agent-turn, and wall-time ledgers remain the final admission
authority.  No arbitrary short polling timeout is used to cancel a live turn.

The operational split is now explicit: `environment_codegen_turn_token_limit`
is the logical session ceiling, while
`environment_codegen_physical_turn_token_limit` is the observed/configured
Provider ceiling for one SDK response.  The graph computes an integer number
of physical turns and divides both token and wall reservations by that same
count.  Thus the authorized 5,000,000-token / 28,800-second session with a
128,000-token Provider ceiling becomes forty visible turns of 125,000 tokens
and 720 seconds each, rather than pretending that one `thread.turn` can emit
5M tokens or imposing an unrelated short timeout.  Each resumed profile keeps
the logical rollout budget but uses its computed physical lifecycle timeout;
the private continuation record binds the same thread, workspace, profile,
schema, immutable inputs and Scheduler authority before any resume call.

Before a new live attempt, a constructed normal-Scheduler boundary must prove
that an exact output-ceiling result with a private session produces a separate
continuation WorkAttempt, preserves only a public commitment, restores the
same workspace/session, and can complete on the next physical turn.  A
diagnostic one-attempt node remains useful for identifying the first failure,
but cannot prove the continuation path by itself.
