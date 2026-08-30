# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher, or fallback survives.
Invariant 2: Framework owns identities/execution/verdicts; generated code never self-authorizes.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks or green tests alone.
Not doing: do not implement S3 reward or training inside S2.
Gold reference: contrasting real Git and SQLite releases plus a held-out Need.

## Accepted deletion-first correction

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

## Current implementation state

- v1 production paths remain absent.
- S1 source authority and positive-only evidence formats are implemented.
- Native Auditor contract has been reduced to native effects/collateral.
- full cold historical replay and pseudo mutation evidence are removed.
- Atom/ForEach/If minimal admission is implemented.
- deterministic full-suite quality gates are green after the deletion.
- prior `/tmp` v1/v2 Author outputs are diagnostic only and are not accepted artifacts.

## Executed real evidence

1. Fresh-generated Expected Semantics with per-capability minimal answers.
2. Fresh-authored TaskSemantics and Native Auditor under the new contracts.
3. Ran one real positive Qualification case per Git capability.
4. Published, relocated, prepared, and invoked the Git release.
5. Compiled and admitted Atom/ForEach/If TaskPacks with minimal gates across
   environments that actually declare those Goal semantics.
6. Repeated on SQLite with unchanged Framework code.

## Real closure evidence — 2026-08-30

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

## Assessment and corpus closure — 2026-08-30

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

## Documentation self-review — 2026-08-30

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

This review authorizes presenting the plan to the user. It does not authorize
Checkpoint A implementation until the user accepts the revised plan.
