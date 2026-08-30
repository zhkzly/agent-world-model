# S2 Direct Good-Task Sampling Foundry — Technical Design

## 1. System boundary

```text
S1 EnvironmentRelease
  public actor + protected qualified semantics
                         |
                         v
S2 Direct candidate enumeration -> admission -> TaskPack corpus
                         |
                         v
S3 public episode + deterministic reward/abstention
```

S2 trusts only exact qualified release bytes and calls release-local semantics
through the prepared process boundary. It contains no environment-domain code.

## 2. Actual production path

The only required path is:

```text
prepare_release
-> compile_atom_tasks
-> compile_foreach_tasks where supported
-> compile_if_tasks where supported
-> future compile_all_tasks only with a real CompositionRule
-> task_structure_id
-> balanced structural selection
-> physical Task admission
-> persisted TaskPack / typed rejection
-> fresh TaskAssessment
-> CorpusManifest
```

`run_task_foundry_batch` owns candidate compilation, structural grouping,
selection, admission and persistence. `run_task_foundry_product` owns downstream
assessment and corpus selection. No second product path or feature flag exists.

## 3. Direct candidate semantics

### Atom

For each qualified Capability, StartCase and eligible Binding:

- freeze release, Start, capability and stable logical referent;
- freeze answer schema/checker identity before rendering instruction;
- reject an initially satisfied mutation/process goal;
- render only public descriptor values and qualified answer labels.

### ForEach

ForEach is legal only when the Capability supports it and public enumeration
produces a complete deterministic selection. The Task freezes the selector and
logical member constraints, not incidental run IDs.

### If

If is legal only for a qualified ConditionSpec whose truth is publicly
observable and whose selected branch licenses a qualified capability. Each
fresh run resolves the condition and binding again.

### All

All remains unsupported until a real release publishes a Qualification-backed
CompositionRule. Framework must not manufacture a composition to satisfy a
coverage target.

## 4. Structural identity and deduplication

`task_structure_id` describes training-relevant semantics rather than Task text
or entity IDs. It preserves applicable differences in:

- Goal/selector/condition shape;
- capability and answer contract;
- Start regime/state condition;
- parameter dependency/information shape where the current contract exposes it.

Paraphrases, concrete IDs and parameter substitutions do not create a new
structure. A structure hash collision with different canonical structure bytes
fails closed.

Candidate and admitted counts are reported separately. Batch selection cannot
override Task admission.

## 5. Public witness and provenance

The public Agent receives exactly the final instruction, fresh reset
observation, ToolSpecs and ToolObservations. Host resolves every argument leaf
to one of:

```text
instruction literal
reset observation
prior successful ToolObservation
ToolSpec constant
AgentChoice
```

Protected/native values never enter acting-time arguments. AgentChoice is legal
only where Task semantics permits the Agent to choose it.

Every admitted Task has two independent successful witnesses. A witness proves
existence, not uniqueness.

## 6. Physical verification

All positive witnesses use the shared lifecycle:

```text
open -> reset -> public episode -> inspect -> close
-> reopen same native instance without reset -> inspect/check -> close
```

Admission freezes challenge applicability before witnesses. Production runs one
discriminating physical case for each applicable class:

- initial/no-op;
- wrong public target;
- wrong/stale structured answer;
- omitted member/partial completion;
- prohibited collateral effect;
- required process/reload violation when process is semantically required.

Challenges evaluate the Task goal, not a single reference trace. Broader
mutation matrices and alternative-route sampling are paper experiments unless a
real defect makes them product-critical.

## 7. TaskPack

A TaskPack binds:

```text
release identity
Task definition/checker/instruction identities
two fresh witness identities
argument provenance
reload evidence where used
applicable physical challenge results
```

TaskAssessment, model identity, difficulty and corpus policy are excluded.

The strict current reader must recompute identities from canonical bytes and
return:

- trusted host projection: Start/checker/identities;
- PublicTaskView: instruction and final-answer schema only.

Reset observation and ToolSpecs are obtained freshly from the release.

## 8. Assessment and corpus

Assessment runs after admission on fresh materializations. It records policy
identity, successes/failures, attribution, calls, tokens, latency and cost. It
cannot weaken a checker or retry failures out of the record.

Corpus selection consumes exact `(TaskPack ID, TaskAssessment ID)` pairs,
deduplicates semantic structures and balances declared release/Goal/Start/
condition buckets under a seed. Selection does not invalidate omitted
TaskPacks.

## 9. Optional sampler experiments

Graph, Programmatic, backward dependency planning and other search strategies
are optional candidate/witness discovery experiments. They may be introduced
only when:

1. Direct fixed-budget evidence demonstrates a named coverage gap;
2. the experiment feeds the same Task admission path;
3. matched-budget evaluation measures additional non-redundant admitted Tasks,
   truth error, cost and downstream value;
4. zero or negative incremental value removes the experiment.

They never become Task types, truth authority or S2 completion gates.

## 10. Failure ownership

```text
CandidateUnsupported  release semantics cannot express the Task
BindingFailure        fresh public logical binding cannot be reconstructed
NoPublicWitness       exact frozen instruction not solved within budget
CheckerDefect         checker contradicts its frozen Task contract
TaskChallengeFailure  a physical counterexample defeats validity
EnvironmentDefect     actor or qualified release semantics are wrong
InfrastructureFailure provider/dependency/process unavailable
RejectedForCorpus     valid Task omitted by corpus policy
```

Fix the first owner. Never add a compatibility adapter, hidden operand or domain
exception to make a batch green.

## 11. Anti-overdesign rule

Before adding a node, field, Agent role or module, state which Good-Task or
corpus claim cannot be proved by the current Direct components and show the real
counterexample. No demonstrated gap means no new component.
