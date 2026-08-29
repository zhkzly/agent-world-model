# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher or fallback survives.
Invariant 2: Framework owns deterministic identities, execution and verdicts; Codex-authored release code never self-authorizes.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks, dictionary worlds or green tests alone.
Not doing now: do not implement later S2 checkpoints while the v2 release/Qualification boundary is incomplete.
Gold reference: the contrasting real SQLite and filesystem/Git releases and the held-out Need gates in `implement.md`.

## Current execution boundary

- Selected: delete the entire v1 publication/Qualification/loader/CLI path and its positive fixtures before adding new v2 behavior.
- Rejected: retain a compatibility shim or reuse old Qualification artifacts to accelerate a nominal green path.
- Reconsider only if a current v2 consumer requires a physical primitive that cannot be expressed without an old semantic authority; no such evidence currently exists.
- Preserve only version-neutral physical assets that have a live v2 consumer, such as deterministic tree manifests and locked two-runtime preparation.
- After the deletion baseline is green, implement native v2 Qualification and Publication before S2 compiler/witness/admission.

## Evidence

- Deleted 12,000+ lines of v1 production code, positive fixtures, tests and stale active guidance; no compatibility adapter or fallback was added.
- Preserved tree-manifest integrity as a version-neutral v2 preparation primitive and killed a constant-digest mutant with the real trusted-mutation tests.
- Focused physical tests, 277 full tests, Ruff, format, Mypy, lock and zero-reference checks pass; this establishes only the clean v2 foundation.

## Contract reclosure after independent BLOCK

- Three independent reviewers agreed that `9ba397b` is a genuine v2-only base but blocked further implementation because Qualification depended on a not-yet-known Release ID and no independent native truth producer existed.
- Selected: derive an internal Core ID before Qualification, add one mutually blind qualification-only verifier project, then seal the passed receipt into the final Release ID.
- Selected: replace cross-run protected bindings with logical binding plans and run-local resolutions; add exact public value sources and bounded selected-sibling evaluation context.
- Rejected: weaken independence to TaskSemantics self-agreement, restore the deleted v1 Qualifier, add a provisional package, or create a universal State/SQL/effect DSL.
- Implementation remains paused until the amended PROJECT/PRD/design/implement/spec package passes a fresh independent review and receives subsequent user approval.

## Re-review result

- Identity/native-truth reviewer: `ALLOW`; Core → evidence → receipt → Release is acyclic and the mutually blind verifier is independently executable.
- Full-S2 reviewer: `ALLOW`; sealed manifests, qualified StartCases, logical selection/rebinding, event-level provenance, fresh episodes and pre-witness AdmissionPlan close the release → TaskPack → corpus chain.
- Overdesign/guidance reviewer: `ALLOW`; additions are bounded Host-derived records, not new lifecycles, DSLs, services or public runtimes; stale active S1/v1 guidance was removed.
- Repository validation after reclosure: Trellis context valid, 277 tests green, Ruff/format/Mypy/lock/diff checks green.
- Next authorized implementation boundary, after user approval: Checkpoint A contracts/decoders/tests only; no author run, Qualification, Publication or S2 execution claim.

## Checkpoint A implementation evidence

- Implemented one clean-break semantic encoding: `PublicValueSource`, exact public leaf sources, run-local evaluation bindings/context, and no read/write scope algebra.
- Implemented acyclic Qualification Core, strict receipt, public/catalog/coverage/StartCase manifests and a native verifier request with no protected TaskSemantics projection.
- Replaced concrete TaskDefinition/checker bindings with logical refs/selections; added run-local resolutions, event-level value occurrences, fresh episode identity and pre-witness AdmissionPlan.
- Migrated every fixture/consumer without adapters or optional legacy fields. Full 292-test suite, Ruff, format, Mypy, lock and diff checks pass.
- Forty-one final behavior-level mutants were killed across the three target modules and recorded individually in `research/checkpoint-a-mutation-licenses.md`. Redundant-layer survivors that did not change external behavior were replaced by behavior-level mutants or the duplicate check was removed; none is counted.
- No Author, Qualification, Publication, compiler or Responses execution has run; Checkpoint A authorizes contracts only.

## Checkpoint A first high-level review and correction

- Two high-level reviewers returned `BLOCK`: task-literal values were dropped; logical selections/sibling sets were underbound; witness occurrences, ordering and AdmissionPlan were not consumed by TaskPack; native wire decoders and public binding uniqueness were incomplete.
- Root cause: immutable records existed but their downstream consumer invariants were missing, so unit-shape GREEN could not prove the advertised causal chain.
- Corrected without new product nodes: per-binding literal values, selector-bound selections, exact siblings, public-binding uniqueness, exact wire decoders, trace occurrence resolution, TaskPack-owned plan/ordering and exact witness resolution sets.
- Fresh re-review then found member slot identity conflated with shared selector identity, making a valid multi-member ForEach unrepresentable. `LogicalSelection` now owns one SelectorSpec while multiple uniquely slotted logical refs point to its selector ID; an accepted two-member TaskPack plus missing/extra-member negatives prove the boundary.
- The next re-review found GoalProgram references/cardinality and ordered member multiplicity were not closed. Blueprint and Task construction now recursively validate ForEach selector/capability/`all` cardinality, Atom/If logical slots, checker-goal equality and exact ordered binding tuples; missing selectors, wrong cardinality, duplicates and reordering are RED.
- The following re-review found fresh witness resolutions still compared as a set. TaskPack now compares the exact frozen logical-ref tuple, and a reversed second materialization is RED even with recomputed admission evidence.
- The next review found inverse Goal closure missing: unused selectors/bindings and duplicate composition/ForEach annotations could survive. Duplicate annotations were deleted; recursive Goal validation now consumes every logical binding, with selector consumption derived from exact non-empty selection membership.
- The next review found set-based inverse consumption could count one duplicate AllGoal leaf twice, plus unbound checker answer/preimage and witness StartCase edges. All simultaneously-required children must now consume disjoint slots, and TaskDefinition/TaskPack explicitly reconcile these three identity pairs.
- The final semantic review found selector cardinality was not reconciled with frozen membership. `exactly_one`/`any_one` now require one member and `all` retains the complete ordered tuple.

## Checkpoint A final review

- Semantic/full-Task reviewer: `ALLOW`; all former literal, ambiguity, Goal, ForEach, order, provenance, plan and identity bypass probes now fail closed, while a valid two-member ForEach TaskPack succeeds.
- Qualification/identity reviewer: `ALLOW`; Core/receipt/manifests/native wire remain acyclic/exact and final Task/checker/witness bindings are mechanically reconciled.
- Final stable evidence: 292 tests, Ruff, format, Mypy, lock, diff and Trellis context GREEN; 41 auditable behavior mutation licences.
- Checkpoint A is complete. This authorizes Checkpoint B verifier authoring only; it is not a Qualification, Publication or S2 completion claim.
- Full gates and final mutation suite are GREEN again. A fresh high-level re-review is required before Checkpoint B.

## Checkpoint B implementation candidate

- Added one mutually blind verifier-author input projection, one fixed
  qualification-verifier codegen skill/contract and one Codex SDK author/repair
  route. Framework owns immutable inputs, source/output rejection, locked build,
  import separation, identity and typed invocation.
- Closed the actor schema handoff with exact mechanical paths; schema meaning
  remains Builder-authored and Framework contains no domain field branch.
- Reused the Checkpoint A `public-surface/2` type exactly; legacy v1 dictionaries
  are rejected and actor factory identity remains Host-owned.
- Real ocean/SQLite execution produced verifier digest
  `a9784a74ec963d962a5b11c8b891d270863c8792faa1ba9a06e11fbeeddeeb0e`.
  Query/state/refusal positives, no-op, wrong answer and missing process all
  changed the intended axes; full before/after trees remained unchanged.
- Full repository Pytest, Ruff, format, Mypy, uv lock and diff checks are GREEN;
  fifteen targeted behavior mutations were killed.
- Semantic, prior-blocker and identity/scope reviewers independently returned
  `ALLOW` on the final boundary. Checkpoint B is complete and authorizes
  Checkpoint C shared materialization/Qualification only. It is not
  Qualification, Publication, Release or S2 completion evidence.

## Checkpoint C1 shared materializer candidate

- Replaced the actor/semantics-only runtime installer with one three-role
  `materialize_project` while preserving the existing uv/cache/origin path.
- Unified Builder, Semantics Author, Verifier Author, release and runtime project
  identity over path/mode/content; no translation identity or compatibility
  profile exists.
- Real accepted verifier `a9784a74...eb0e` filtered, installed and passed all
  three import denials without copying author inputs/view/old runtime.
- Six materializer/identity mutants were killed; full repository gates and the
  original B physical matrix remain GREEN.
- Two independent reviewers returned `ALLOW` after an initial identity-handoff
  `BLOCK` was corrected with the actual accepted verifier. C1 is complete. It
  is not physical Qualification or S1 completion and authorizes C2 Core and
  three-runtime Qualification wiring only.
