# S2 Task Foundry — semantic design

## 1. Design purpose

This document makes S2 concrete enough to validate S1. It freezes Task
semantics, trust boundaries, constructive solvability and admission, but it is
not an S2 implementation plan.

```text
exact EnvironmentRelease
-> Graph-based and Programmatic candidate generation
-> package-owned start materialization
-> public-only reference execution
-> actual public/native truth
-> independent task-local verifier
-> challenges and provisional trials
-> immutable TaskPack
-> S3 episode handoff
```

## 2. Roles and information boundaries

| Role | May see | May mutate |
| --- | --- | --- |
| candidate generator | public Brief/docs/limitations, start/reset-observation schemas, ToolSpecs and public exploration observations | candidate instruction and requested start only |
| trusted materializer | exact EnvironmentRelease and qualification summary, `start_schema`, `reset_observation_schema` and caller-owned instance directory | loads release, calls reset, validates the initial observation and performs optional setup through invoke only |
| reference solver | draft instruction, actor-visible start context, public docs, ToolSpecs and invoke results | its fresh instance through public calls only |
| TruthExtractor author | instruction, StartRecord, Brief, terminal tool observations, trusted instance access and decode-only source access after expected relations freeze; minimal trace only for declared process constraints | protected TruthExtractor workspace only |
| OutcomeVerifier author | instruction/answer contract, extracted task facts and minimal declared-process trace; no candidate/reference source | protected OutcomeVerifier workspace only |
| admission runner | exact identities, trusted episode instance directories, public traces, verifier and challenges | loads/resets/closes instances and stages TaskPack |
| pilot harness | provisional public Task projection, ToolSpecs and immutable sealing-policy configuration; no protected truth | its bounded fresh trial instances; emits protected trial evidence only, never EpisodeRecord/Reward |
| later acting policy | public Task projection, ToolSpecs, public observations and final-answer contract | its S3 episode through the selected caller adapter and final response only |

Research evidence and the S1 Brief identify supported capabilities; they never
serve as Task truth. Candidate package source may be inspected only by the
TruthExtractor author for native representation decoding after expected
relations are frozen; it is never an oracle or acting-policy input.

## 3. Start materialization

### 3.1 Objects

`StartRecipe` is private S2 input used to recreate a start:

```text
release and qualification-summary identities
+ canonical package-specific reset/start JSON
+ selected ordinary package-asset references
+ ordered public setup-call program
```

The recipe identity excludes observations and native state because they do not
exist until the recipe runs.

`StartRecord` is a protected attestation of one actual materialization:

```text
recipe identity
+ actual setup call/observation trace digest
+ protected baseline-instance evidence digests
+ close/reload persistence and fresh-reset semantic-replay outcome
+ ToolSpec surface and runtime identities
```

`TaskPackID` later binds existing component digests, including recipe and record,
without any component containing the TaskPackID itself.

### 3.2 Execution

```text
validate exact EnvironmentRelease identity and qualification summary
-> create a unique empty caller-owned instance directory
-> load release and call reset with canonical start input
-> call tools() to discover the public surface
-> resolve setup parameters from instruction/public observations/prior results
-> execute optional setup through invoke()
-> close or otherwise quiesce
-> inspect raw native baseline
-> reload for promised persistence and reset/replay on another fresh instance
-> validate reset/setup observations and public behavior
```

S1's qualification summary attests release-level reset, persistence and
isolation; it is not a State IR or replay oracle. S2 does not consume a generic
invariant manifest. Candidate-specific replay is established later by replaying
the public constructive witness and rerunning the task-local TruthExtractor on a
second fresh materialization.

A documented reset, semantic replay or reload failure first returns
InfrastructureFailure and retries identical release/runner/input identities. It
becomes PackageDefect only when the failure reproduces from published bytes on
the qualified platform/runner. An invalid candidate input is RejectedCandidate.
S2 never repairs either by writing native bytes.

Ordinary generated-project package data is allowed because large datasets and
real Git history may be irreducible to small JSON. StartRecipe uses documented
package-defined asset identifiers; only the package reset implementation
interprets/materializes them. There is no generic snapshot or state-import API.

## 4. Two mandatory constructive solvability lanes

Graph-based and Programmatic are both mandatory candidate sources. They are not
Task types and not an exclusive router. They may cover the same capability, and
both pass the same admission.

The implementation task may prioritize a lane to improve coverage/cost, but it
cannot delete either mechanism or treat its candidate as solved before fresh
public execution.

## 5. Graph-based generation

### 5.1 Candidate graph

The graph is ephemeral evidence for a candidate batch, not an S1 graph, runtime
engine or universal state model.

`tools()`, public docs and an LLM propose tool pairs, weights and possible
parameter bindings. These links guide sampling; they are not automatically
causal or required.

Graph exploration maintains a generic `PublicValuePool`, not a domain table:

```text
actor-visible Task/start values
+ documented public constants/enums
+ structured values extracted from `data` in successful `invoke()` observations
+ provenance for each value: step id, JSON Pointer, output type/schema
```

At each step the runner computes an action mask: a tool is callable only when
all required inputs can be bound from that pool or from explicitly generated
public values such as a date stated in the future Task. The framework never
contains names such as `room_id`, `issue_id` or `sku`; it works with ToolSpec
input/output schemas, JSON Pointers and provenance. If no public root action
or visible value can start a core capability, the package surface is not
Task-reachable and S1 must not release it as core-complete.

### 5.2 Evidence labels

- `output_binding`: the executed host trace shows an earlier public result being
  used as a later argument. This proves value provenance for that witness, not
  that the earlier tool is the only source.
- `state_precondition_candidate`: an earlier public call may enable a later one.
  It remains a sampling hypothesis unless the Task or verifier claims necessity.
- `weak`: the value/order has another public route and cannot become a mandatory
  solution step.
- `independent`: no required relation; useful only for diversity.
- `distractor`: available to the Agent but removed from `tau*`, truth and required
  coverage.

When Task wording, a process constraint or the verifier asserts that A must
precede B, run a scoped omission/reversal replay on fresh equivalent starts and
inspect the relevant native predicate. If necessity is not demonstrated, remove
the order claim and treat the link only as sampling scaffolding. A successful
sequence alone never proves required order.

### 5.3 Sampling and solvability

Random walk is execution-conditioned: it samples only from the currently
callable action mask, biased by proposed/witnessed edge weights and coverage
goals. It does not pick from all tools blindly and does not establish truth.
Independent/distractor calls may diversify the proposal but are never required
solution steps.

After each real call, successful observation `data` is validated against the
tool output schema and added to the PublicValuePool. On `ok=false` business
refusal, the runner
records the structured failure and either selects another action or creates a
fresh root and replays the last valid prefix. It never repairs exploration by
reading or writing native state.

Reserved `contract.*` errors are invalid-action feedback, not business
refusals. They add no values, witness no edge/state relation and cannot become
Task truth.

The concrete witness records each argument either as a Task/public constant or
as a `PublicResultRef(step, json_pointer)`. Replay therefore re-resolves dynamic
IDs from new observations rather than hardcoding incidental database values.

For each sampled chain:

1. bind parameters from the PublicValuePool with complete provenance;
2. run the complete chain on a fresh materialization;
3. record host trace and native before/after truth;
4. synthesize an instruction from the achieved business relation, removing tool
   names, private values and solution order;
5. reject leakage or hidden-information dependence;
6. replay the final pruned `tau*` through `invoke()` on another fresh reset.

Fresh public execution/replay of `tau*` is the existence witness. Later repeated
acting-Agent trials test whether the natural-language Task lets an ordinary
policy recover a solution. Graph reachability and random walk are proposal
evidence only.

## 6. Programmatic generation

The generator proposes a grounded instruction and a Python reference program.
The program is a trusted admission-time policy, not the later acting Agent.

It may:

- discover tools with `tools()` and call them through `invoke()`;
- branch on public observations;
- loop over variable-length results;
- aggregate, sort and perform local deterministic computation;
- return a proposed final answer.

It may not:

- read native roots or use the inspector;
- import candidate package functions;
- alter initialization or controls;
- embed protected expected values;
- write private state.

Every dynamic operand must be stated in actor-visible context, independently
rediscovered through public tools, or bound from an earlier public observation.
A protected sampler may identify an interesting entity but cannot pass a hidden
value directly into the reference program.

Reserved `contract.*` observations indicate an invalid reference action. They
cannot supply values, prove business refusal or become ground truth; the
candidate program must correct the public action or be rejected.

The public-Environment-API restriction intentionally strengthens Agent-World's
implementation-loading reference: it may reduce convenience, but it proves the
same interface available to the later acting Agent is sufficient.

The runner creates a fresh start and executes the program. Bounded repairs use
only public observations and protocol/runtime failures. A program that cannot
achieve the instruction is rejected.

Actual execution produces truth:

- state-changing truth comes from native before/after relations;
- query/final-answer truth comes from actual tool observations cross-checked
  against native facts where relevant;
- process truth comes from the host-owned public trace.

The program's literals or intended outcome are never truth merely because the
program produced them.

## 7. Task types and final answer

| Task type | Primary truth | Final answer | Verifier evidence |
| --- | --- | --- | --- |
| state-changing | protected native goal and collateral relations | optional unless requested | final/reloaded state; trace only for declared process rules |
| read/query | actual public result cross-checked against native truth | required | structured answer correctness and normally no unintended mutation |
| process-constrained | declared trace milestones/minefields plus native result | optional unless requested | minimal semantic trace predicate and final state |
| composite | conjunction of relevant component truths | required for query/report subgoals | native relations, answers, trace constraints and collateral checks |

S2 defines a Task-local satisfied/failed/abstain verifier contract. S3 later maps
verified facts into Reward; S2 does not prescribe one scalar rule.

Deterministic native-state, structured-answer and host-trace predicates are the
default for both lanes. A criterion-bounded LLM Judge is allowed only for a
remaining open-text quality that cannot be expressed through those channels. It
must be challenged with wrong/stale answers, may abstain, and never overrides a
deterministic failure. Verifier choice follows truth type, not synthesis lane.

## 8. Task-local truth, verifier construction and challenges

Before candidate-source access, the truth author freezes instruction/Brief-
derived expected relations and acceptance predicates. It may then inspect source
read-only solely to locate/decode native representation. Source-use purpose and
ordering are recorded; candidate code may not be imported/executed and its
business predicates or expected literals cannot become Task truth.

The author receives a sanitized projection only: instruction, StartRecord,
published Brief, terminal tool observations, trusted baseline/terminal instance
access and, for a declared process constraint, the minimal predicate-specific
trace. It never receives the reference program source, the reference program's
returned final answer or the full ordinary-outcome path. From that projection it
authors a digest-bound ordinary Python `TruthExtractor`; the host executes it to
produce task-local facts. This is the named raw-native-to-task-truth owner; no
universal state adapter exists.

`project_terminal_tool_observations(reference, answer_contract)` is a named host
projection. It contains only the final tool-result fields required by the Task's
outcome/answer contract. It excludes tool calls, arguments, ordered intermediate
observations, reference-program return/final answer and any information that
would reconstruct the ordinary reference path. Process Tasks receive their
separate minimal predicate-specific trace projection.

A separate source-free context authors `OutcomeVerifier` from extracted facts,
the answer contract and only the minimal declared-process trace. It does not
receive candidate source, the reference program or the complete reference path.

Both protected programs are challenged. The extractor must distinguish the
intended entity/field/relation under native near misses and claim-scoped
mutations. The verifier must not match the exact reference path or invoke
candidate business functions as its oracle.

Each frozen verifier runs on fresh starts against:

- the positive reference execution;
- no-op;
- wrong parameters/entity;
- near miss;
- achieved goal plus collateral damage;
- wrong/stale final answer when applicable;
- a process violation reaching the same final state when applicable;
- at least one independently executed alternative valid path when available.

Verifier mutations (remove a required predicate, ignore final answer, remove a
minefield), Task mutations and applicable disposable environment mutants or
physical negatives are claim-scoped. A mutation counts only if its targeted path
still executes; syntax/import/crash is not semantic evidence.

A false acceptance or rejection is a VerifierDefect or ambiguous Task. It is
revised/rejected without changing EnvironmentRelease truth.

## 9. Common admission

```python
def admit(release, mechanism) -> AdmissionOutcome:
    exact = resolve_and_validate_exact_release(release)
    draft = mechanism.propose(exact.public_surface)

    start = materialize_with_attribution(draft.start_recipe)
    replay = materialize_with_attribution(draft.start_recipe)
    if start.infrastructure_failed or replay.infrastructure_failed:
        return InfrastructureFailure(start, replay)
    if reproducible_package_contract_failure(start, replay):
        return PackageDefect("start_replay")
    if not reset_and_setup_observations_are_schema_valid(start, replay):
        return RejectedCandidate("invalid_start_recipe")

    reference = run_constructive_witness(draft, start)
    replayed_reference = run_constructive_witness(draft, replay)
    if reference.infrastructure_failed or replayed_reference.infrastructure_failed:
        return InfrastructureFailure(reference, replayed_reference)
    if not reference.completed or not replayed_reference.completed:
        return RejectedCandidate("no_public_solution")

    expected = freeze_task_expected_relations_before_source(
        draft.instruction, exact.published_brief, start.record
    )
    truth_extractor = author_task_truth_extractor(
        expected=expected,
        instruction=draft.instruction,
        start_record=start.record,
        brief=exact.published_brief,
        terminal_tool_observations=project_terminal_tool_observations(
            reference, draft.answer_contract
        ),
        baseline_and_terminal_instances=(start.baseline, reference.terminal),
        minimal_declared_process_trace=project_trace_if_required(reference),
        source_access="decode-only",
    )
    truth = host_extract_actual_truth(
        truth_extractor, start.baseline, reference.terminal
    )
    replayed_truth = host_extract_actual_truth(
        truth_extractor, replay.baseline, replayed_reference.terminal
    )
    if not task_local_facts_agree(truth, replayed_truth):
        return RejectedCandidate("unstable_task_truth")
    if not instruction_matches_truth(draft.instruction, truth):
        return RejectedCandidate("instruction_truth_mismatch")

    verifier = author_outcome_verifier_in_source_free_context(
        instruction=draft.instruction,
        answer_contract=draft.answer_contract,
        extracted_truth=truth,
        minimal_declared_process_trace=project_trace_if_required(reference),
    )
    truth_extractor, verifier = challenge_and_revise(
        truth_extractor, verifier, draft, start, truth
    )
    if verifier.unresolved:
        return VerifierDefect(verifier.findings)

    provisional = bind_provisional_task(
        exact, start, draft, truth_extractor, truth, verifier
    )
    sealing_policy = resolve_immutable_sealing_policy()
    trials = run_independent_actor_pilots(provisional, sealing_policy)
    if trials.expose_task_or_verifier_defect:
        return RejectedCandidate(trials.findings)
    if not trials.meets(sealing_policy):
        return QuarantinedCandidate(provisional, trials)

    return Admitted(seal_taskpack(provisional, trials, sealing_policy))
```

`task_local_facts_agree` is exact but task-local: both extracted fact sets must
satisfy the same frozen business predicates. Dynamic entities are aligned by
their public binding roles and JSON-pointer provenance inside their respective
executions, not by comparing incidental IDs/bytes across resets. A permissive
subset/contains comparison is invalid. This rule belongs to the Task's
TruthExtractor/admission evidence and does not create a universal State IR.

Repeated trials happen after reference/verifier proof and before final sealing.
They reveal public recoverability, wording stability, verifier false negatives,
feasibility and empirical difficulty. They do not prove or disprove existence.
The S2 implementation later calibrates policy mix, run count and the repeated
success threshold. A zero-success candidate remains unsealed and quarantined;
future corpus policy may reconsider it but cannot silently call it Admitted.

The bounded pilot harness is owned by S2 admission and emits protected trial
evidence only; it does not run the S3 EpisodeRecord/Reward pipeline. The
immutable sealing policy requires at least one pilot policy/model lineage
independent of the candidate generator and binds all pilot/runner identities.

## 10. TaskPack identity and projections

The provisional candidate identity is distinct from the sealed TaskPack
identity. The TaskPack identity hashes canonical public bytes and all protected
component digests, including exact release/qualification summary,
StartRecipe/StartRecord, instruction, answer contract, reference evidence,
TruthExtractor, OutcomeVerifier, dependencies, challenge evidence, immutable
sealing-policy artifact, exact trial evidence and final admission status. The
sealing policy binds thresholds, trial protocol, runner/policy identity
requirements and decision rule. No identity-bearing record embeds the
TaskPackID inside its own preimage.

Public acting projection:

- TaskPack and exact EnvironmentRelease identities;
- natural-language instruction;
- actor-visible initial context;
- permitted public tool interaction and process constraints;
- final-answer requirement/format;
- applicable public limitations.

Protected trusted projection:

- canonical start recipe;
- native baseline/replay evidence;
- setup/reference programs and traces;
- task-local TruthExtractor and actual truth derivation;
- OutcomeVerifier bytes and both protected dependency identities;
- challenges, mutations, trials and admission evidence.

Changing release, start, instruction, answer contract, truth, verifier or
load-bearing evidence creates a new TaskPack identity and reruns admission.

Package defect handling:

```text
S2 quarantines new admission for the exact release
-> submits reproducible defect evidence
-> S1 requalifies the exact published bytes
-> confirmed defect marks that immutable artifact unavailable for new use
-> all descendants become inadmissible
-> correction requires a new S1 release and new S2 admission
```

Historical bytes are never rewritten. There is no compatibility migration or
latest alias.

## 11. S3 boundary

S3 receives both TaskPack projections. Its trusted runtime materializes the
protected start, gives only public Task/ToolSpec/observation material to the acting policy,
records actions/observations/final answer, quiesces native state, executes the
frozen TruthExtractor and OutcomeVerifier, and emits EpisodeRecord plus verified
facts for Reward or abstain.

S2 does not own policy rollout scheduling, trajectory storage, scalar reward,
SFT/RL adapters or training.

## 12. Derived S1 obligations

| S1 capability that must be frozen and proved | Exact S2 consumer |
| --- | --- |
| immutable EnvironmentRelease identity, runtime project/entry point and qualification summary | release resolution, TaskPack binding and package-defect attribution |
| named `start_schema`, `reset_observation_schema`, meaningful default, validated initial public observation and package data | materialization of diverse valid StartRecipes without native writes |
| ToolSpecs and uniform `ToolObservation {ok,data,error}` with schema-valid success data | both candidate lanes, public value binding and later acting policy |
| caller-owned isolated instance directories and trusted read-only access | baseline, witness truth, scoped order checks and task-local verifier |
| semantic replay, persistence, isolation and relocation | reference/challenge/episode recreation |
| public Brief/environment docs/limitations and S1 qualification summary | candidate grounding and trust decision |
| consumer-shaped pre-release proof | evidence that the seam works without generator-private adapters |

S1 does not need Task/TaskPack schemas, graph engine, verifier DSL/runtime,
answer extractor, reward function, policy trials, difficulty/curriculum fields,
universal state IR/snapshot importer, lifecycle ABI, transport adapter,
compatibility adapters or mutable latest.

## 13. Two concrete handoffs

### Booking

Materialize users, resources, capacity, prices, clock and existing reservations.
Graph exploration records public output bindings and proposes state/order links,
then executes and freshly replays a reserve/cancel chain. Order intervention is
used only if the Task claims that order is mandatory. Programmatic generation may
loop over search results and choose a qualifying option under constraints. The
Task instruction states the business goal, not the path. Native reservation,
capacity and unrelated-record relations plus any requested final identifier form
truth. Challenges include wrong resource/date, duplicate reservation,
collateral cancellation and alternative qualifying reservations.

First fake-green: accepting `reserved` output without a committed capacity and
reservation relation after close/reload.

### Filesystem/Git

Materialize a real project and Git history from package assets and reset inputs.
Graph witnesses distinguish read-output binding from a proposed `git add`/commit
order; a targeted omission replay licenses that order only for a process Task.
Programmatic generation may discover files, loop over
results, edit, check and commit. Verifier truth uses file bytes/modes, tests,
index/refs/objects and the host trace only for declared process constraints.
Challenges include no-op, protected-file modification, uncommitted change,
wrong branch and a different valid implementation.

First fake-green: accepting a commit-shaped observation while no corresponding
Git object/reachable ref exists or collateral files changed.

## 14. Deferred implementation decisions

- Lane sampling/ranking proportions and graph storage.
- Model/provider, prompts, Skills and repair budgets.
- Trial count, policy mix, difficulty thresholds and curriculum.
- Concrete serialization, Registry/storage and verifier dependency execution.
- Parallelism, caches, dashboards and service topology.
- S3 EpisodeRecord and Reward schemas and all training integration.

These cannot redefine the frozen solvability, truth, verifier or S1-consumer
boundaries above.
