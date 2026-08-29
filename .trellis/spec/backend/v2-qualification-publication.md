# EnvironmentRelease v2 Qualification and Publication Contract

> **Status: SQLite and filesystem/Git C3+D production paths implemented and
> physically proven with unchanged Framework code.**
> The Host-owned `run_v2_qualification` binds mutually blind Authors into one
> Core, seals physical cases and executable reader mutants, issues a strict
> receipt, publishes deterministic directory and ZIP bytes, verifies live sealed
> catalogs, and cold-replays archived readers. This closes the required
> cross-environment C/D repeat; Checkpoints E-G remain incomplete.

## 1. Scope / Trigger

Use this contract after actor, expected semantics, TaskSemantics and the
qualification-only verifier have frozen. It defines the only path from those
projects to an S2-admissible EnvironmentRelease v2.

It does not define Task generation, a public service, Registry behavior or any
v1 migration.

## 2. Signatures

```python
derive_qualification_core(inputs: FrozenCoreInputs) -> QualificationCore

run_v2_qualification(
    inputs: FrozenCoreInputs,
    core: QualificationCore,
    destination: Path,
    cache_root: Path,
    *,
    route: AgentRoute,
    budget: QualificationBudget,
    settings: PreparationSettings | None = None,
) -> QualificationReport

publish_release_v2(
    core: QualificationCore,
    report: QualificationReport,
    destination: Path,
) -> PublishedRelease | PublicationFailure

verify_release_v2(path: Path) -> ValidatedReleaseV2

prepare_verifier_author_workspace(...) -> PreparedVerifierAuthorWorkspace
run_verifier_author(prepared, *, config) -> VerifierBuild
repair_verifier_author(prepared, build, findings, *, config) -> VerifierBuild
invoke_verifier_transition(
    verifier_root,
    request,
    *,
    expected_verifier_project_digest,
    expected_report_field_ids,
    config,
) -> NativeVerificationResult
```

Qualification verifier factory:

```python
generated_qualification_verifier.release:make_verifier
```

Verifier call:

```python
verify_transition(request: NativeVerificationRequest) -> NativeVerificationResult
```

## 3. Contracts

### Identity

- `core_id` is RFC 8785/SHA-256 over expected-semantics, actor, semantics,
  verifier, factory, schema and public-document digests.
- Core identity excludes evidence, receipt and final Release ID.
- Qualification evidence and receipt bind `core_id`.
- Publication copies Core bytes unchanged, then adds evidence/receipt and
  computes payload and final descriptor digests.
- Directory-mode physical evidence is part of sealed instance identity. The
  deterministic ZIP writer must therefore emit every directory, including empty
  native directories, with its Unix mode; extraction must recreate and chmod
  directory entries before strict evidence verification.
- Qualification never consumes final Release ID. Publication never rewrites Core
  bytes or Qualification evidence.
- Core derivation re-verifies the immutable Expected Semantics/Public Surface
  bytes and identical actor view actually received by both Authors. In-memory
  replacement bytes cannot be rebound to unchanged generated projects.
- Actor, semantics and verifier project roots are distinct, non-nested and
  disjoint from the Qualification cache. Core-addressed materialization rejects
  any post-Core source drift before use.

### Independent verifier

- Verifier Author never receives TaskSemantics source/output/tests/feedback.
- Semantics Author never receives verifier source/output/tests/feedback.
- Verifier receives public descriptor/trace/answer and before/after native paths;
  it never receives TaskSemantics protected bindings or facts.
- If those public inputs cannot identify the intended native referent, the
  capability is Unsupported; Host never supplies a hidden identifier.
- Verifier cannot import actor, semantics or Host packages and cannot mutate
  either instance.
- Host compares every result axis and report value and owns the verdict.

Checkpoint B enforces the author/invocation boundary as follows:

- Author inputs use exact `public-surface/2`, frozen Expected Semantics, the
  fixed verifier contract and a manifested actor view; legacy surface
  dictionaries are rejected.
- Project identity binds path, mode and content. Repair accepts only typed
  Framework/native factual findings and requires the same root, Codex home,
  thread and current project digest.
- Host scans generated authority artifacts before and after project tests and
  factory loading. Every invocation recomputes the accepted project digest,
  rejects resolved before/after aliases, exact-decodes the result, checks frozen
  report field IDs and proves verifier/before/after trees unchanged.
- The user requires full-access code authoring without a product sandbox.
  Therefore B proves causal/context blindness and runtime import denial, not
  OS-level containment against malicious arbitrary filesystem scanning.

### Shared materialization

- Qualification and sealed preparation call one internal project materializer.
- Actor, semantics and verifier use separate locked interpreters and project roots.
- Sealed `prepare_release` installs actor/semantics only. The verifier is installed
  only for Qualification or cold audit.
- There is no `allow_unqualified`, pending release or alternate cache/transport.

### Task-kind and answer-schema closure

- `task_kind` uses state-effect precedence. A success that requires any
  business-state change is `state_change`, even when it also requires public
  process evidence. `process` and `query` are state-preserving.
- Production Qualification compares TaskSemantics `inspect(before/after)` for
  every positive and fresh replay and rejects a mismatched kind before sealing.
- Every Taskable capability has a structured final answer. Answer-field schemas
  must be strict structured-output subschemas: arrays have `items`; objects
  declare all properties as required and set `additionalProperties=false`.
- Capabilities sharing one ConditionSpec use identical branch-neutral answer
  field IDs/labels; an irrelevant selected binding returns `abstain` and does
  not create an If Blueprint.

### Receipt

The receipt has exact fields:

```text
format
verdict
core_id
expected_semantics_digest
actor_project_digest
semantics_project_digest
verifier_project_digest
public_surface_manifest_digest
qualified_catalog_digest
requirement_coverage_digest
qualified_start_cases_digest
evidence_manifest_digest
```

`format` is `environment-qualification/2`; `verdict` is `passed`. Every digest
must match recomputed archived bytes.

Bound data documents are:

```text
public-surface.json        public schemas/docs and exact ToolSpec catalog
qualified-catalog.json     exact capability/condition/composition catalog
requirement-coverage.json  every Requirement disposition and evidence IDs
qualified-start-cases.json exact reset inputs/regimes S2 may use
evidence-manifest.json     public/native/negative/replay/mutation evidence
```

Every prepared session must reproduce the sealed ToolSpec and CapabilitySpec
catalog digests. The live StartCase generator must reproduce the sealed qualified
set; unlisted generated cases are not S2-admissible.

Evidence manifest requires public success, applicable negatives, fresh replay,
cross-reader agreement, no-mutation/import evidence and executable mutation
results.

### Runtime versus audit projection

- S2 receives an `AdmittedReleaseView` containing only identity, sealed public
  surface/catalog/StartCases and actor/TaskSemantics session factories.
- Native evidence, verifier paths and Qualification traces exist only in a
  separate `QualificationAuditView` used for cold replay.

### Release admission

- Checkpoint D changes `verify_release_v2` from the current structural verifier
  into closed-byte plus strict-receipt admission.
- Checkpoint D makes `prepare_release` reject structural/mechanical fixtures.
  Current fixture preparation is test infrastructure, never S2 admission.
- Directory and ZIP forms must resolve to the same descriptor/Release ID.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Core member changes after evidence | `QualificationFailure(core_changed)` |
| Author attestation Expected/Public/view differs | Core derivation rejection |
| Project roots alias/nest or cache overlaps a source | rejection before cache writes |
| Semantics/verifier axis disagreement | `SemanticsDefect` or `VerifierDefect`; fail closed if unresolved |
| Verifier imports actor/semantics/Host | `VerifierDefect(import_leak)` |
| Semantics/verifier mutates instance | corresponding typed defect |
| Verifier project differs from accepted digest | `VerifierDefect` before invocation |
| Before/after paths resolve to one instance | `VerifierDefect` before invocation |
| Verifier returns missing/aliased report fields | `VerifierDefect`; factual same-thread repair |
| Generated tests/factory/invocation write authority/project bytes | `VerifierDefect`; reject |
| Missing applicable physical case | Qualification not passed |
| Declared task kind disagrees with semantic before/after state | `qualification_task_kind_mismatch` |
| Answer field cannot be submitted as strict structured output | Semantics Author rejection before public Agent call |
| Executable required mutant survives | Qualification not passed |
| Provider/dependency/process unavailable | `InfrastructureFailure`; no semantic repair |
| Receipt missing/unknown field or non-passed verdict | release rejection |
| Receipt/Core/evidence digest mismatch | release rejection |
| Live tools/capabilities/StartCases differ from sealed documents | release/session rejection |
| Mechanical fixture receipt | release rejection |
| Publication changes frozen project/evidence byte | `PublicationFailure(core_changed)` |
| Final descriptor/payload/ZIP tamper | release rejection |
| ZIP omits or changes a sealed empty directory/mode | `qualification_case_tree_mismatch` during strict admission |

## 5. Good / Base / Bad Cases

- Good: actor and semantics agree on a success, the independently authored
  verifier reaches the same axes from native before/after state, and no-op/wrong
  target/collateral/wrong-answer cases are rejected by both.
- Base: a Core is qualified, sealed once, relocated, cold reopened and replayed;
  all identities recompute exactly.
- Bad: write a canonical `{verdict: "mechanical_fixture_only"}` receipt and call
  it a release.
- Bad: let the verifier read TaskSemantics protected facts or copy its evaluator.
- Bad: prepare a pending release through a private flag and later replace its
  receipt.
- Bad: implement a second uv installer for Qualification.

## 6. Tests Required

- Per-field Core preimage mutation and explicit proof that final Release ID is
  absent from Qualification inputs.
- Mutual author-view denial and source/import scans.
- Exact v2 author input, same-lineage typed repair, path/mode/content identity,
  post-test artifact rescan and accepted-digest invocation tests.
- Real query/state/refusal, no-op, wrong-answer and missing-process verifier
  calls with exact report fields and immutable verifier/native trees.
- Real separate actor/semantics/verifier interpreters against the same instances.
- Mutate-on-success and mutate-then-error no-mutation tests for semantics/verifier.
- Axis/report mismatch, no-op, wrong target, near miss, answer, collateral,
  process and fresh replay cases.
- Executable inspector/evaluator/verifier mutants; crash/syntax mutants excluded.
- Exact receipt schema, category completeness and every digest mismatch.
- Exact public-surface/catalog/coverage/StartCase documents, live equality and
  rejection of unqualified generated StartCases.
- Type/projection test proving S2 cannot deserialize verifier/evidence/reference traces.
- Mechanical fixture cannot pass `verify_release_v2`/`prepare_release` admission.
- Publication byte preservation, directory/ZIP relocation and cold replay.
- Empty native directory and directory-mode preservation through the production
  ZIP writer/extractor, plus a real Git release containing empty `.git` directories.
- Real SQLite and filesystem/Git releases with unchanged Framework code.

## 7. Wrong vs Correct

Wrong:

```text
temporary release ID -> Qualification -> replace qualification.json -> new release ID
```

Correct:

```text
frozen Core bytes -> Core ID -> Qualification receipt -> final descriptor -> Release ID
```

Wrong:

```text
TaskSemantics.inspect -> TaskSemantics.evaluate_atom -> "independent" agreement
```

Correct:

```text
same physical before/after instances
├─ TaskSemantics evaluation
└─ mutually blind verifier native evaluation
Host compares exact axes and physical negatives
```

Wrong:

```text
ZIP only regular files -> extractor recreates parent directories incidentally
```

Correct:

```text
ZIP binds files + directory entries/modes -> extractor restores the same tree
-> sealed before/after tree digests still match
```
