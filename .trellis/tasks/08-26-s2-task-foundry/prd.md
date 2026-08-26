# S2 Task Foundry

## Goal

Consume an exact qualified S1 `EnvironmentRelease` and synthesize Tasks that are
grounded in a real initial world, have at least one publicly executable solution,
carry independently challenged task-local verification, and can be handed to S3
without exposing protected truth to the acting Agent.

## Current phase

This child owns semantic and cross-layer design only. It has no implementation
plan and is not authorized for code. S1 is implemented first after the S1/S2
contract is frozen; S2 design is then revalidated against a real S1 release
before an S2 implementation plan is written.

## Inputs and outputs

S2 consumes exactly:

- an exact qualified `EnvironmentRelease` identity and runtime project;
- its public `start_schema`, `reset_observation_schema` and validated initial
  observation;
- `ToolSpec[]` from `tools()`, uniform `ToolObservation {ok,data,error}` results and public
  Brief/environment documentation;
- caller-owned isolated episode instances and trusted read-only access to each
  instance directory for task-specific native inspection;
- the S1 qualification summary and declared limitations.

This input is complete for both candidate lanes. S2 cannot require S1 to add
Graph, Programmatic, Task, verifier, reward or trajectory-specific fields.

S2 outputs either:

- `Admitted(TaskPack)`;
- `QuarantinedCandidate` for a reference-solved Task that has not yet shown
  stable recoverability from the public Agent view;
- `RejectedCandidate` for a bad, leaky, ambiguous or publicly unsolved Task;
- `VerifierDefect` for a Task whose verifier cannot discriminate outcomes;
- `PackageDefect` for a reproducible violation of the S1 release contract;
- `InfrastructureFailure`, which may retry identical identities but cannot
  change package, Task or verifier semantics.

## Requirements

### R1. Exact release and trust separation

- Every candidate and TaskPack binds one exact EnvironmentRelease identity.
  No `latest`, mutable current alias, range resolution or compatibility
  migration exists.
- Candidate generators see public docs, ToolSpecs and public observations.
  They never receive raw native state as user-facing knowledge.
- The trusted materializer loads the release in a fresh caller-owned instance
  directory and invokes `reset(start)`; later state changes use only public
  `invoke()` calls.
- Reference solvers see the same public interaction surface as the acting Agent.
- Verifier authoring owns a protected task-local pair: a `TruthExtractor` that
  reads the trusted episode instance directory and a separate `OutcomeVerifier`
  that judges an episode against extracted facts, public trace and final answer. The acting
  Agent receives neither artifact, only its public Task projection, ToolSpecs
  and structured observations.

### R2. Reproducible initial world

- A private `StartRecipe` binds release identity, canonical `reset(start)` input,
  any ordinary package-asset references selected by that input and ordered
  public setup calls.
- A separate `StartRecord` attests one materialization, public setup trace,
  protected native baseline, close/reload persistence, fresh-reset replay and
  runtime identity.
- S1 Qualification already attests release-level reset, persistence and
  isolation. S2 checks the candidate Task by validating reset/setup observations,
  replaying its public reference on another fresh materialization and rerunning
  its task-local TruthExtractor. It consumes no generic machine-readable
  invariant manifest from S1.
- Agreement across fresh materializations means both task-local fact sets satisfy
  the same frozen business predicates. Dynamic referents are aligned by their
  public binding role/provenance within each run, never raw incidental ID or byte
  equality and never an unconstrained subset match.
- Dynamic values used by setup calls must come from the instruction, public
  observations or bindings to earlier public results. A recipe depending on a
  hidden native value is inadmissible.
- Every dynamic value needed by the Graph witness, Programmatic witness or later
  acting policy must likewise be present in actor-visible Task context,
  independently discoverable through public tools, or bound from an earlier
  public result. Protected native sampling may select a candidate referent, but
  it cannot become a hidden operand.
- S2 never writes SQLite, files, Git internals or simulator state directly and
  never restores a generic native snapshot.

### R3. Both constructive solvability mechanisms are required

Graph-based and Programmatic generation are complementary mandatory candidate
sources, not mutually exclusive Task types.

- Graph-based generation constructs candidates backward from empirically
  witnessed public tool/data/state dependencies and a successfully replayed
  public action chain.
- Programmatic generation constructs a candidate instruction and a bounded
  reference Python program that uses only the public environment client, then
  executes and repairs the program until it succeeds or the candidate is
  rejected.
- Either mechanism may cover the same capability. Sampling/ranking may prefer a
  lane for efficiency or coverage, but lane choice is provenance, not proof.
- Both mechanisms are required at the S2 system/corpus level; one Task does not
  need two redundant existence witnesses.
- Both lanes must pass the same fresh-start reference execution and admission.

### R4. Graph-based generation is execution-derived

- `tools()`, docs and LLM analysis propose weighted adjacency for sampling;
  proposed links are not world truth.
- An `output_binding` is witnessed when an earlier public result supplies a
  later argument in an executed trace. Weak/independent links may diversify
  sampling but impose no required order.
- Graph exploration maintains an environment-neutral pool of actor-visible
  typed values and JSON-Pointer provenance. Random walk is conditioned on tools
  whose required arguments can currently be bound; it never samples blindly
  from the complete catalog or hardcodes domain field names.
- Every value feeding another call must come from `data` in a successful
  `invoke()` observation validated against its ToolSpec output schema,
  Task-visible context or a documented
  public constant. Missing public roots/operands make the capability unreachable.
- `contract.*` observations are invalid-action feedback. They never enter the
  public value pool and cannot witness business refusal, state change, ordering
  or Task truth.
- A state-precondition or required-order claim needs a scoped omission/reversal
  execution on replay-equivalent starts. Full counterfactual testing is not
  required for edges that remain sampling scaffolding.
- Random walk or another coverage sampler proposes chains from these labels. It
  is not solvability proof, and distractor calls are never required solution
  steps.
- After pruning, the final public `tau*` chain must execute successfully on a
  fresh start. That execution is the Graph lane's constructive existence
  witness; no second reference-solver abstraction is required.
- Task wording expresses the achieved business goal and constraints, not tool
  names, database schema, hidden values or the sampled solution sequence.

### R5. Programmatic generation is public-only

- The candidate instruction is grounded in the public Brief, qualified tool
  surface and a real materialized world.
- The reference program may call `tools()`/`invoke()`, branch, loop,
  aggregate and perform local deterministic computation.
- It cannot import package business code, read instance roots, call the
  inspector, alter initialization or write private state.
- Restricting `pi_code` to the same public Environment API as the acting Agent is a
  deliberate strengthening over implementations that load tool code directly:
  it proves public-agent solvability rather than privileged-code solvability.
- Every acting-time operand follows the same public-value provenance rule as the
  Graph lane.
- Actual public observations and independently observed native outcomes—not
  literals or expectations embedded in the program—produce ground truth and any
  required final answer.
- The reference program is trusted admission evidence. S3's acting policy still
  performs its own think/action/observation tool loop.

### R6. Task truth and final answers are type-specific

- State-changing Tasks primarily use native before/after relations and
  collateral-damage checks; final text is optional unless the instruction asks
  for a report or identifier.
- Read/query Tasks require a final answer derived from actual public execution
  and cross-checked against native truth where relevant; unintended mutation is
  normally a failure.
- Process-constrained Tasks use the host-owned trace for declared milestones,
  ordering and minefields in addition to the final relation.
- Composite Tasks combine only the truth channels required by their subgoals.
- Deterministic native-state, structured-answer and trace checks are preferred.
  A bounded criterion-specific LLM Judge is permitted only for an irreducibly
  semantic open-text residual, must abstain when evidence is insufficient, and
  cannot override a deterministic failure.
- S2 produces verifier facts and an answer contract; it does not define a
  universal scalar reward.

### R7. Independent task-local verifier

- Before source access, the truth author freezes Task/Brief-derived expected
  relations and acceptance predicates. It may then inspect candidate source
  read-only solely to locate/decode native representation, with purpose and
  ordering recorded. It may not import/call candidate code or copy its business
  predicates/expected literals.
- It authors a digest-bound task-local `TruthExtractor` from the instruction,
  StartRecord, Brief, terminal public observations and trusted baseline/terminal
  instance access. The host executes it on baseline and terminal state. There is
  no universal state adapter or candidate self-report.
- For outcome Tasks it sees instruction, StartRecord, terminal public
  observations and claim-scoped native before/after facts, not the complete
  reference path.
- For a declared process-constrained Task it may see the minimal trace projection
  needed to state the process predicate.
- The separate `OutcomeVerifier` is authored in a source-free context over
  extracted task facts, answer contract and only the minimal declared-process
  trace. Neither protected program receives reference program source or the full
  ordinary-outcome reference path, calls candidate business functions as oracle,
  or requires exact reference-path equality.
- Fresh challenge runs include the positive reference, no-op, wrong parameter,
  near miss, collateral damage, wrong/stale final answer when applicable, and an
  alternative valid public path when one exists.
- Claim-scoped task/verifier/environment mutations or physical negatives must
  show that challenges depend on the intended semantic relation.
- TruthExtractor mutations and native near-miss roots must show that fact
  extraction itself distinguishes the intended entity, field and relation.

### R8. Common admission and trials

- Both lanes rematerialize the exact start and execute a public-only reference
  solution. This physical execution proves existence of at least one solution.
- Verifier challenges follow reference success; no model verdict overrides
  process/native evidence.
- Repeated independent acting-Agent trials occur after provisional admission and
  before final sealing. They measure public recoverability, Task wording
  stability, verifier false negatives, practical feasibility and empirical
  difficulty—not logical solvability.
- A bounded S2-owned pilot harness runs these trials and emits only protected
  trial evidence. It does not create S3 EpisodeRecords or Rewards. The immutable
  sealing policy requires at least one pilot policy/model lineage independent of
  the candidate generator and records all policy/runner identities.
- A Task cannot be sealed into the current public-agent corpus without the
  later-calibrated repeated-success requirement. All-policy failure leaves a
  logically solved but unsealed `QuarantinedCandidate`; it cannot negate the
  executed existence proof. A demonstrated Task/verifier flaw rejects it.
- Numeric trial counts and thresholds are calibration choices for the later S2
  implementation task, not architecture constants.

### R9. Immutable TaskPack and invalidation

- TaskPack identity binds exact release identity, private StartRecipe/StartRecord,
  public instruction and answer contract, verifier bytes/dependencies, reference
  evidence, challenge evidence, immutable sealing-policy digest, exact trial
  evidence and final admission status without circular self-inclusion.
- Provisional candidate identity is distinct from the sealed TaskPack identity.
- The acting projection excludes initialization, controls, protected baseline,
  reference solution/trace, verifier source and challenge evidence.
- A Task or verifier correction creates a new TaskPack identity and does not
  rewrite the EnvironmentRelease.
- A reproducible package defect quarantines new admissions and is returned to
  S1 for cold requalification. A confirmed defect marks that immutable release
  unavailable for new use and invalidates every descendant TaskPack without
  rewriting historical bytes.

### R10. S3 handoff

S3 receives the TaskPack public projection for the acting Agent and the protected
projection for its trusted runtime. S3 loads the exact EnvironmentRelease,
recreates the start with `reset`, exposes ToolSpecs through its selected Agent
adapter, owns the episode loop and public trace, captures final answer/native evidence, executes
the frozen verifier, and emits EpisodeRecord plus Reward or abstention. S2 does
not implement rollout scheduling, trajectory formats, scalar reward mapping or
training.

## Design acceptance criteria

- [ ] Graph-based flow records public output provenance, executes and freshly
  replays `tau*`, and uses scoped intervention only for asserted order or state
  necessity.
- [ ] Programmatic flow proves public tool-call solvability without making code
  execution the acting policy interface.
- [ ] Booking and filesystem/Git each traverse both generation, truth,
  verification and TaskPack boundaries without hardcoded framework support.
- [ ] After S1/S2 generic artifacts freeze, an independently selected held-out
  multi-Need suite exercises both lanes without new domain bindings, field-name
  rules or private-value adapters in the framework.
- [ ] Task types and final-answer behavior have explicit truth sources.
- [ ] Public/protected role projections prevent answer, path and native-state
  leakage.
- [ ] Every S2 operation maps to a named, physically tested S1 capability; the
  S1 plan contains no unconsumed S2 schema/reward mechanism.
- [ ] A fresh cross-layer review finds no S2 operation that would require direct
  state mutation or an S1 package compatibility redesign.

## Deferred until S2 implementation planning

- Models, prompts, Skills, code layout and service/process topology.
- Lane sampling ratios, graph persistence, ranking, deduplication and corpus mix.
- Trial counts, difficulty thresholds and curriculum policy.
- TaskPack serialization/storage, verifier dependencies and access controls.
- Mutation automation, batch execution, scaling and operational budgets.
- EpisodeRecord schema, reward mapping, SFT/RL integration and training.

## Evidence basis

- Agent-World Graph/Programmatic synthesis: <https://arxiv.org/html/2604.18292>
- PROVE live tool synthesis/replay: <https://arxiv.org/html/2606.03892>
- AWM executable environment generation: <https://arxiv.org/html/2602.10090>
