# EnvironmentRelease v2 Qualification and Publication

## Scope

This contract is the only path from frozen actor/TaskSemantics/Native Auditor
projects to an S2-admissible EnvironmentRelease v2. It defines no v1 migration,
Registry, service, Task generator, or reward system.

## APIs

```python
derive_qualification_core(inputs) -> QualificationCore
run_v2_qualification(inputs, core, destination, cache_root, *, route, budget) -> QualificationReport
publish_release_v2(destination, *, core, receipt, actor_project, semantics_project,
                   verifier_project, expected_semantics_payload, public_surface,
                   qualified_catalog, requirement_coverage, qualified_start_cases,
                   evidence_root) -> ValidatedReleaseV2
verify_release_v2(path) -> ValidatedReleaseV2
prepare_release(path, cache_root) -> OpenPreparedRelease
```

## Authored roles

- Actor owns public environment behavior.
- TaskSemantics owns protected effects, process, final answer, and report truth.
- Native Auditor independently owns only native required effects and collateral.

The Native Auditor request contains capability/start IDs, public descriptor and
trace, and before/after instance paths. It never receives final answer,
protected binding, TaskSemantics facts, checker, Task, or reward.

The Native Auditor result contains exactly:

```text
required_effects_ok
collateral_ok
failure_codes
```

## Answer source authority

Every AnswerField has exactly one source kind:

```text
task_literal
task_descriptor
reset
tool_observation
tool_schema_constant
```

Tool observation pointers are rooted at the full `{ok,data,error}` envelope.
Qualification statically resolves every pointer against sealed schemas and
physically matches each reported value to a real occurrence.

Each capability declares only answer values necessary for its user objective.
Condition branches may use different answer schemas. Process/state/collateral
evidence is not padded into final answers.

## Positive qualification

Framework executes one representative eligible binding per capability. A case
passes only when:

- public execution completes;
- TaskSemantics accepts effects, process, and final answer;
- Native Auditor agrees on effects/collateral;
- AnswerField report values match public occurrences;
- task kind matches the physical semantic state transition;
- all authored projects and native instances remain within their mutation roles.

Qualification evidence contains one positive and one physical noop case for
every qualified capability. Wrong-answer/target, partial, alternative-route, AgentChoice,
collateral-manufacture, and checker-mutation evidence belongs to Task admission
or optional paper experiments.

## Scenario: Noop axis qualification

### 1. Scope / Trigger

Every new or repaired release-local TaskSemantics/Native Auditor pair must pass
this scenario before publication. It prevents effect, collateral and public
process truth from collapsing into one aggregate boolean.

### 2. Signatures

```python
validate_qualification_case_outcome(category, semantic, verifier) -> None
run_v2_qualification(...) -> QualificationReport
```

### 3. Contracts

- Current evidence format is `qualification-evidence/3`.
- Each capability contributes exactly one `noop` and at least one `positive`.
- Noop uses distinct, identically reset before/after native directories, empty
  public trace and empty final answer.
- Unchanged state requires `collateral_ok=true`. A state-change effect may be
  absent; a process/refusal native no-mutation relation may already hold, while
  `process_ok` remains false and the Task remains unsatisfied.
- Answer-source occurrences are required only for a satisfied positive case.

### 4. Validation & Error Matrix

| Condition | Error |
| --- | --- |
| Semantics/Auditor effect or collateral disagreement | `qualification_reader_disagreement` |
| noop is satisfied, collateral false, or process true | `qualification_case_outcome_invalid` |
| any capability lacks noop evidence | `qualification_noop_coverage_missing` |
| failed positive has no public answer occurrence | attribute `qualification_positive_failed` before source checking |

### 5. Good / Base / Bad Cases

- Good: state change noop is effect=false, collateral=true, process=false.
- Base: query/refusal noop may have native effect=true but public process=false.
- Bad: required effect missing automatically sets collateral=false.

### 6. Tests Required

- One-sided Semantics and Auditor collateral mutants must each fail.
- Evidence sealing/cold reading requires both categories per capability.
- A failed positive must not be misreported as AnswerField source corruption.

### 7. Wrong vs Correct

Wrong:

```python
collateral_ok = required_effects_ok
```

Correct:

```python
required_effects_ok = required_native_relation(before, after)
collateral_ok = no_prohibited_unrelated_change(before, after)
```

## Receipt

The strict receipt binds:

```text
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

Generated code never writes receipts, manifests, digests, or verdicts.

## Publication

Publication verifies all bound digests, copies exact project/evidence bytes,
writes canonical payload and receipt documents, and derives the final Release
ID from the descriptor. No provisional release exists.

## Cold preparation

Preparation verifies package bytes and digests, installs exact actor and
TaskSemantics projects, checks live ToolSpecs/catalog/StartCases against sealed
values, and opens a real session. It does not replay every historical
qualification case whenever a Consumer opens the release.

## Forbidden

- v1 compatibility or alternate readers;
- `allow_unqualified` or provisional packages;
- Native Auditor public answer/process/report authority;
- global requirements for a state-change capability, multi-binding query, or
  disjoint workflow;
- result-object boolean flipping described as executable mutation testing;
- S1 copies of S2 Task challenge matrices;
- domain-specific Framework branches.
