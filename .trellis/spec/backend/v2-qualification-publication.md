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

Qualification evidence contains positive cases only and covers every qualified
capability. Wrong-answer/target, partial, alternative-route, AgentChoice,
collateral-manufacture, and checker-mutation evidence belongs to Task admission
or optional paper experiments.

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
