# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher, or fallback survives.
Invariant 2: Framework owns identities/execution/verdicts; generated code never self-authorizes.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks or green tests alone.
Not doing: do not implement S3 reward or training inside S2.
Gold reference: contrasting real Git and SQLite releases plus a held-out Need.

## Historical deletion-first checkpoint — superseded for S2 completion

This section records why S1 duplication and fake robustness machinery were
deleted. Its S1/anti-compatibility decisions remain active, but its minimal S2
challenge set and “optional” alternative/collateral language no longer define
S2 completion; the Good Task correction below supersedes them.

- S1 qualifies one representative positive execution per capability.
- Native Auditor checks only required native effects and collateral.
- Host/TaskSemantics own public process, AnswerFields, and final answer.
- S1 does not duplicate S2 Task challenges.
- AnswerField singleton profiles and `reportable_field_ids` are deleted.
- Condition branches may use different necessary answer schemas.
- Atom keeps two witnesses plus no-op/wrong-target/wrong-answer.
- ForEach keeps two witnesses plus no-op and one representative partial.
- If keeps two witnesses for the condition-selected branch.
- Alternative route, reverse order, every AgentChoice perturbation, collateral
  manufacture, and result-object mutation are optional paper experiments.
- Corpus-count/structure floors are experiment metrics, not product gates.

## Historical implementation checkpoint at `189be1b`

- v1 production paths remain absent.
- S1 source authority and positive-only evidence formats are implemented.
- Native Auditor contract has been reduced to native effects/collateral.
- full cold historical replay and pseudo mutation evidence are removed.
- Atom/ForEach/If minimal admission is implemented.
- deterministic full-suite quality gates are green after the deletion.
- prior `/tmp` v1/v2 Author outputs are diagnostic only and are not accepted artifacts.

## Historical executed evidence (checkpoint only)

1. Fresh-generated Expected Semantics with per-capability minimal answers.
2. Fresh-authored TaskSemantics and Native Auditor under the new contracts.
3. Ran one real positive Qualification case per Git capability.
4. Published, relocated, prepared, and invoked the Git release.
5. Compiled and admitted Atom/ForEach/If TaskPacks with minimal gates across
   environments that actually declare those Goal semantics.
6. Repeated on SQLite with unchanged Framework code.

## Historical vertical evidence — not S2 closure

- Git Release `bdb1f97e3cded9960df7cf2c8c7112406ded1525c5e2529c962d2d3059d4e810`
  passed simplified positive Qualification, ZIP relocation, cold preparation and
  Consumer invocation. Its qualified semantics produced Atom and ForEach Tasks;
  it declared no condition, so Framework did not manufacture an If Task.
- SQLite Release `e37f86f8628ab33254c53604b8c9f9c5488227b881c297f8f34b17c6affca3d9`
  passed the same Framework path with four capabilities and real SQLite state.
  Its public eligibility condition naturally compiled If Tasks.
- SQLite batch `79719d008f935129c85e444fcf10a3cc41304b639336f4fe71da8700c92b2edf`
  admitted one Atom, one ForEach and one If structure with two fresh public
  witnesses each and zero rejected attempts. The If pack binds a separately
  admitted Atom branch dependency.
- Full deterministic gates passed after the real runs: lock check, Ruff, format,
  Mypy, 337 pytest cases and `git diff --check`.
- Alternative routes, forced condition coverage, corpus floors, held-out Needs
  and downstream utility remain paper evaluation work, not individual release
  or TaskPack admission gates.

## Historical assessment/corpus checkpoint evidence

- TaskAssessment runs fresh public-only trials after TaskPack admission. It binds
  the acting model/route/prompt policy and records checker failures instead of
  retrying them into success or changing Task truth.
- Corpus selection is deterministic over exact TaskPack/TaskAssessment pairs,
  removes duplicate structures within a release, round-robins release/Goal
  buckets, and applies an explicit reliability policy. Corpus size is not a
  release or TaskPack gate.
- SQLite product run
  `ba15b5e51cd2447ce537126a8a89232068683d2e70e0ae505732db64850a7950`
  admitted Atom/ForEach/If, executed three fresh assessment trials per TaskPack,
  observed reliability `1.0` for all three, and sealed CorpusManifest
  `394ae82573ccac6e22bd67b3f5f2bac5666de9d013820f39aed800b275b8c9f8`.
- Main-session artifact recomputation confirmed all three assessment identities,
  all nine run identities, the product report and CorpusManifest digests; the
  nine assessment materializations are unique and disjoint from admission
  witness materializations. No subagent verdict is used for this closure.

## S2 Good Task correction — 2026-08-30

The preceding evidence remains valid for the implemented execution checkpoint,
but it does not complete S2 Task sampling. User correction: S2 must sample and
admit a quality-controlled Task corpus for later tool-calling Agentic RL, using
the previously agreed Good Task definition rather than merely compiling and
solving three Tasks.

Selected correction:

- retain the v2 runtime, public Agent loop, provenance, fresh starts and current
  identity foundations;
- use direct, Graph and Programmatic mechanisms as proposal samplers feeding one
  common CandidateTaskProposal boundary;
- freeze a bidirectionally anchored TaskSpecification and bounded V0 before
  witness search;
- require public solving, physical reload where declared, and applicability-
  planned semantic challenges before TaskPack seal;
- calibrate and select a corpus separately from Task truth;
- keep S3 reward, messages/tokens/masks/logprobs and training out of S2.

Alternatives rejected:

- restoring the deleted legacy implementation wholesale;
- making GraphTask/ProgrammaticTask separate persistent formats;
- restoring universal State/Rule IR, unrestricted verifier code, exhaustive
  perturbation matrices or compatibility readers;
- treating the real `189be1b` vertical as paper-grade S2 completion.

Evidence that would reverse this correction: an end-to-end physical proof that
the current minimal compiler satisfies bidirectional obligation coverage,
reload persistence, the Good Task challenge set, multi-policy discrimination
and held-out corpus transfer. The existing SQLite “reopen” instruction accepted
without any close/reopen event is a concrete counterexample, so that evidence
does not currently exist.

No product code may be changed from this correction until the revised PRD,
design and implementation plan pass the main-session drift/overdesign review
and the user accepts the plan.

## Historical main-session self-review — superseded by independent REVISE

Main-session review passed after correcting detected drift. Verified:

- S2 product goal is a Good Task corpus for tool-calling Agentic RL, not a
  three-Task execution demo;
- direct/Graph/Programmatic share one proposal/admission boundary;
- all six intrinsic Good Task properties and corpus-level quality are explicit;
- parameterized semantics freeze before Start, concrete public bindings append
  later without changing meaning, and the bound Task freezes before witness;
- obligation IDs, public applicability, executed Graph edges and the bounded
  four-operation Programmatic proposal are implementable rather than prose-only;
- physical reload and applicable semantic challenges are required without an
  exhaustive Cartesian matrix;
- current code is labelled an incomplete checkpoint; no code change is claimed;
- legacy ABI, universal State/Rule IR, persistent sampler types, hidden setup,
  domain branches and S3 reward/training remain out of scope;
- all eight checkpoints contain a product claim, RED acceptance and real exit;
  the ten-item completion checklist, task JSON/JSONL and Markdown diff validate.

This review authorized presenting the draft only. A later independent review
found unresolved semantic-authority and process-necessity ambiguity, so it does
not authorize Checkpoint A.

## Independent S2 responsibility/Good Task review correction — 2026-08-30

Independent Terra review returned `REVISE`, not `ALLOW`:

- instruction/schema disclosure could still be used to self-authorize checker
  meaning;
- S2 could propose its own applicability/irrelevance and thereby omit an
  obligation;
- witness/state-enablement could still be frozen as a mandatory process route;
- CandidateTaskProposal and ReloadEvidence lacked exact compact contracts;
- historical minimal-admission wording remained easy to misread as current.

Critical corrections now applied in the authority documents:

- S1 seals RequirementObligation IDs, semantic kinds and finite applicability
  handles; S2 only evaluates/references them;
- only S1 obligations/qualified operations authorize semantic predicates;
  instruction/schema sources provide disclosure/provenance evidence;
- a required process must cite an S1 process obligation. Graph edges guide
  search only; AdmissionEvidence proves checker sensitivity by trace ablation,
  physical omission when constructible and known alternatives;
- CandidateTaskProposal/1, PublicClosureEvidence and ReloadEvidence/1 have
  compact canonical fields without new services or generic DSLs;
- deletion-first sections are explicitly historical and superseded for S2
  completion.

The wholesale legacy implementation remains rejected. Checkpoint A remains
blocked until these corrected documents pass a new independent review and the
user accepts the plan.

## Independent corrected-plan review — ALLOW

Fresh Terra max re-review confirmed all prior CRITICAL/HIGH/MEDIUM findings are
closed:

- S1 obligations/qualified operations exclusively authorize semantics;
- applicability is finite, sealed before S2 and cannot be self-waived;
- required process cites an S1 process obligation and cannot be inferred from a
  sampler/witness route;
- process evidence uses trace ablation, physical omission when constructible and
  known alternatives;
- CandidateTaskProposal/1, PublicClosureEvidence and ReloadEvidence/1 are compact
  and bounded;
- historical deletion-first language is explicitly superseded;
- Checkpoint A correctly owns reusable lifecycle/reload evidence, while final
  TaskPack decoder/PublicTaskView waits for unified format freeze in F;
- no world ontology, large DSL, dual ABI, second native reader or S3 work was
  introduced.

Independent verdict: `ALLOW`. No code was reviewed as implementing these future
stages. Checkpoint A may begin only after explicit user acceptance.

## Checkpoint A activated — physical lifecycle and ReloadEvidence

User explicitly accepted implementation. This slice is limited to one reusable
attempt lifecycle used by Atom/ForEach/If and assessment:

```text
open acting session -> reset once -> public episode -> inspect -> close
-> open a distinct session on the same native instance without reset
-> inspect -> trusted checker -> close
```

Selected design:

- every new witness/assessment attempt evaluates after a real reopen; a later
  TaskSpecification decides whether reload is also a user-required process
  predicate;
- ReloadEvidence binds a pre-generated attempt_id rather than witness_id, avoiding
  an identity hash cycle;
- lifecycle events and facts/checker digests are Host-generated and included in
  each witness; no absolute temporary path is identity;
- one shared lifecycle module owns ordering; Goal modules own only preflight and
  checker evaluation.
- challenge episodes remain explicitly owned by Checkpoint E and are not claimed
  complete by this slice.

Rejected alternatives:

- three duplicated close/reopen implementations;
- a reload feature flag selecting old/new execution paths;
- writing a cold reader for the provisional current TaskPack format;
- treating Graph state-enablement or instruction wording as reload authority.

Evidence that would reverse this design: a qualified release whose legitimate
TaskSemantics cannot survive close/open of the same reset instance despite S1's
replay/persistence contract. Such a failure is an upstream Environment/Start
defect, not permission to restore same-process checking.

## Checkpoint A execution evidence — GREEN

Implemented one shared Host-owned lifecycle and `ReloadEvidence/1`; Atom,
ForEach and If positive witnesses plus model-relative assessment now evaluate
through a distinct reopened session on the same native instance. Witness formats
bind the evidence as `atom/foreach/if-witness/2`. Challenge episode migration
remains Checkpoint E scope.

Deterministic evidence:

- 353 tests, Ruff, formatting, Mypy, lock and diff checks pass;
- ReloadEvidence rejects same-session reuse, lifecycle reordering/second reset,
  another native instance and missing post-reopen checker;
- one initially toothless same-session test caused mutation-license rejection;
  the test was corrected before implementation acceptance;
- four ReloadEvidence enforcement mutants and one witness-binding mutant for
  each Goal module were killed and restored GREEN.

Real physical evidence:

- SQLite state-change Task `1bfe37441b10657d9db0f42bbe87217bfc82ed1ba173c24f4f1d42530d8a42b5`
  produced two successful fresh reload witnesses. One earlier public-policy
  attempt failed `public_witness_failed` and remains part of the honest run
  record; no gate was weakened or failure relabelled.
- second retained SQLite witness:
  `bd74390287054400c9e065859bf7a27d88e519432cdfc2b22d9330b5e022ad51`;
  acting/reopened sessions differ and pre-close/post-reopen facts match.
- Git query Task `10d1cd1aa6e47da993becd9c649f3283b69ffba330f6b6f8263004ffb93c7b37`
  passed two fresh reload attempts with witness IDs
  `aff84610c3cb75c36041c72bbe4bedcf8fc031a0da63933e530f2bdcfb09fb76`
  and `47c454fbe0b2ab1e5497c82f957359b060ad67ce756738cf8be338f25c97144a`.
- real SQLite ForEach witness
  `d6a4d907d7d745b151efa22e31067acacdb44dc047ecb5d3ac853e252d58705e`
  and If/refusal witness
  `e13e34c9026c53793ca065f27db11a991a350b9364d5a5e449e8d99fd368b9b6`
  both passed after physical reopen with persisted facts.

Generated run details are retained under `.artifacts/checkpoint-a/` and remain
non-authoritative generated evidence rather than source code.

## Checkpoint A post-GREEN overdesign/identity audit

Selected: keep the single nine-event lifecycle because each event is required
to distinguish reset, act, close, reopen and post-reopen checking, while closing
the one discovered identity gap: `attempt_id` now recomputes from exact Release,
Task and native-instance identities. The emitted checker digest field now uses
the approved `post_reopen_checker_result_digest` name.

Rejected: deleting lifecycle/fact fields merely to reduce LOC, adding a reader
or signature layer before the unified TaskPack format freezes, or expanding the
slice into challenge migration. The existing Host execution path is the
physical authority; Checkpoint F will own strict cold decoding.

Evidence: the pre-fix implementation accepted an unrelated 64-hex attempt ID;
the new focused test observed that RED, the corrected code is GREEN, and an
attempt-identity-check mutant is killed. The audit found no sampler, S3,
compatibility, domain-specific or extra service/node drift.

## Checkpoint B activated — sealed Requirement obligation boundary

Smallest observed gap: one real Git Requirement currently covers list, read and
status capabilities, so its free-text outcomes cannot tell S2 which clauses
apply to one concrete Task. Requirement-to-capability coverage alone therefore
cannot support bidirectional Task coverage.

Selected: each expected-semantics clause carries one finite applicability
handle; Framework derives its stable obligation ID and text digest. Taskable
clauses must carry a handle, while non-Taskable background clauses must not.
The catalog remains inside the already-digested expected-semantics payload, so
no new Agent, receipt field, package, service or generic expression language is
introduced.

Rejected: treating every Requirement clause as always applicable, asking S2 or
a witness trace to decide relevance, model-authored hashes/manifest IDs, or a
separate obligation-authoring turn. Evidence that would reverse this choice is
a deterministic mapping from the current free-text clauses to per-Task
applicability across Git and SQLite; the existing multi-capability Requirements
are direct counterexamples.

## Checkpoint B1 execution evidence — sealed obligation input

Implemented `expected-task-semantics/2` with Framework-derived obligation IDs,
finite applicability handles, strict Publication/cold-read reference checks and
a read-only prepared-release projection. The existing expected-semantics digest
binds the catalog; no extra receipt field or generated runtime method was added.

The first live request failed before model execution because the strict
Responses schema allowed an unconstrained array/object facet literal. The
responsible Framework boundary was corrected by restricting facet literals to
comparable JSON scalars and reusing one deterministic strict-output schema
preflight for both AnswerFields and Expected Semantics.

The next Luna live turn passed and produced canonical SQLite-derived expected
semantics digest
`e0e08a3f647f178d7c59ad130a80def73333e27737f8c6a125a89da27dc93704`
with three sealed obligations. This is live B1 contract evidence only: it is
not a new qualified Release and does not complete TaskSpecification/V0 or
Checkpoint B.
