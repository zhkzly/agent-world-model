# Batch Environment and Task Evidence Campaign — Design

## 1. Design boundary

This task adds no new product stage. It turns the existing S1 stage functions
into the already-specified direct coordinator, invokes the existing S2 product
API, and records an experiment campaign around them.

```text
Frozen NeedSuite/1
  -> generate_environment_v2(...)             existing S1 semantics
       Research
       actor Builder
       public-surface freeze
       Expected TaskSemantics freeze
       mutually blind semantic/verifier authors
       Qualification Core + physical Qualification
       immutable Publication + zip + cold preparation
  -> run_task_foundry_product(...)             unchanged S2 semantics
  -> CampaignNeedRecord/1

all CampaignNeedRecords
  -> CampaignManifest/1
  -> AggregateReport/1 + Markdown report + claim-evidence ledger
```

The coordinator and campaign runner are orchestration boundaries, not semantic
authorities. Generated code cannot decide release admission, Task admission or
published statistics.

## 2. Existing S2 sampling authority

The remote repository already implements the required sampling form. This task
must call it, not reconstruct it:

```text
prepare_release
-> compile_atom_tasks
-> compile_foreach_tasks where qualified
-> compile_if_tasks where qualified
-> task_structure_id + balanced structural selection
-> checker/instruction freeze
-> two fresh public-only witnesses
-> applicable physical negative challenges
-> TaskPack
-> independent TaskAssessment
-> CorpusManifest
```

`run_task_foundry_batch(...)` owns candidate compilation, structural selection,
admission and TaskPack persistence. `run_task_foundry_product(...)` owns the
subsequent assessment and corpus selection. The campaign observes their reports
and cannot change their truth, retry rules or identities.

## 3. S1 coordinator

### Public API

Add one domain-neutral module exposing the contract already recorded in
`.trellis/spec/backend/s1-coordinator.md`:

```python
generate_environment_v2(
    need_text: str,
    work_root: Path,
    output_root: Path,
    *,
    config: GenerationConfig,
    event_sink: Callable[[JSONObject], None] | None = None,
) -> Released | NotReleased | Unsupported
```

`GenerationConfig` holds existing route, Builder, Qualification and preparation
budgets explicitly. It does not expose semantic feature flags.

### Exact stage order

1. Preserve the complete natural-language Need in `NeedRecord`.
2. Execute `run_research(...)`; only `ResearchReady` can reach Builder.
3. Execute `run_builder(...)` in a new standalone uv workspace.
4. Freeze the public surface from actor-owned schemas, public documents and the
   real actor tool catalog without importing generated actor code into the Host.
5. Generate and freeze Expected TaskSemantics from the accepted projection and
   public surface.
6. Stage two fresh, mutually blind immutable author workspaces and run the
   TaskSemantics and Qualification Verifier authors.
7. Bind exact authored projects in `FrozenCoreInputs`, derive one Qualification
   Core and execute `run_v2_qualification(...)`.
8. Publish exact frozen bytes with `publish_release_v2(...)`, write the
   deterministic zip, verify it cold and call `prepare_release(...)` once.
9. Return a typed terminal outcome and a stage ledger. No exception text alone
   constitutes a campaign result.

Existing framework validation owns schemas, identities, subprocess isolation,
receipts and qualification truth. The coordinator must call those APIs rather
than reproduce their checks.

### Failure ownership

Map only observed exceptions/results to these report owners:

- `Research`
- `EnvironmentBuilder`
- `ExpectedSemantics`
- `TaskSemanticsAuthor`
- `QualificationVerifierAuthor`
- `Qualification`
- `Publication`
- `Infrastructure`

Preserve the original phase/code/message/details. Do not use a catch-all to
turn defects into unsupported Needs.

## 4. Frozen Need suite

Commit `experiments/batch-environment-task/needs.json` before official runs.
The canonical file contains exactly 20 ordered records with stable IDs,
natural-language Need text and analysis-only domain/backend labels. Labels are
never passed to Research, Builder or S2.

The suite spans transactional state machines, policy/refusal workflows,
document/repository operations and resource/scheduling workflows. Needs require
real resettable state and useful tools but do not prescribe SQLite, tool names,
Task types, reference paths or answers.

The suite digest is computed from canonical JSON bytes. Reordering or editing a
Need produces a different campaign identity.

## 5. Campaign runner and resume

Add a small library runner plus one CLI wrapper. The runner processes Needs
sequentially by default so local provider capacity does not become an
unmeasured confounder.

For each Need:

1. create a new immutable attempt directory;
2. run the S1 coordinator;
3. on `Released`, cold-open the exact zip and run
   `run_task_foundry_product(...)` with target=3 and assessment trials=3;
4. seal one `CampaignNeedRecord/1` referencing all artifacts;
5. atomically update the campaign manifest.

Resume never overwrites a terminal record. It cold-verifies completed artifacts
and continues missing Need IDs. Provider/transport retry remains inside the
already-configured stage budgets. A new source commit, Need digest or semantic
configuration produces a new campaign ID.

If a real Framework bug requires code changes after the official campaign has
started, retain the old campaign as aborted evidence and start a new campaign
identity from the corrected commit. This prevents result-driven patching from
being hidden.

## 6. Evidence model

### Machine-readable outputs

- `NeedSuite/1`: ordered Need IDs/text plus analysis labels and suite digest.
- `CampaignConfig/1`: exact source commit, route/model/budget parameters and
  prompt/runtime-skill digests.
- `CampaignNeedRecord/1`: stage timestamps, terminal owner/code, Release ID,
  S2 product report ID and resource counters.
- `CampaignManifest/1`: exact suite/config identities and one record per Need.
- `AggregateReport/1`: recomputed totals, denominators, distributions and
  representative artifact locators.

Hashes and elapsed/resource values come from Host observations. Models never
write manifests, counts, rates or verdicts.

### Published outputs

Commit small reproducible material under `reports/batch-environment-task/`:

- `summary.json` — canonical aggregate facts;
- `report.md` — definitions, tables, failure analysis and case studies;
- `project-results.md` — compact README/portfolio wording;
- `claim-evidence-ledger.json` — ASu-compatible confirmed/pending claims.

Raw projects, releases and TaskPacks remain under the campaign artifact root;
published reports bind their identities and relative locators. Secrets and
provider configuration values are never copied into reports.

## 7. Metrics

All rates publish numerator and denominator. Environment release rate is
`released Needs / frozen Needs`. Stage rates use the number entering that stage.
S2 reports enumerated candidates, actually attempted candidates, typed rejected
attempts, admitted TaskPacks and per-release structure count separately.

Model-relative assessment reports trial success, turns, tokens and latency; it
is never labelled verifier accuracy. Existing three-environment evidence is a
historical baseline and is not added to the 20-Need campaign denominator.

## 8. Validation and anti-overdesign constraints

- Unit tests may use controlled adapters to verify orchestration and failure
  propagation; they are never campaign evidence.
- Real acceptance uses the configured Codex SDK, Responses tool policy, Search,
  Fetch/Extract, real uv projects, physical Qualification and cold artifacts.
- No generic workflow engine, queue service, database, Registry, Graph sampler,
  retry framework or new verifier language is introduced.
- The existing S1/S2 contracts remain authoritative. Campaign statistics cannot
  affect individual environment or Task truth.
- Any diff that reimplements or forks Direct sampling is scope drift and must be
  removed unless a separately demonstrated Framework defect requires a focused
  repair.
