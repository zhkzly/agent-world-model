# Batch Environment and Task Evidence Campaign — Implementation Plan

## 1. Execution rules

- Implement and verify the repeatable harness before freezing official inputs.
- No official campaign result may come from mocks, fixtures or handwritten
  TaskPacks.
- Do not change S1/S2 semantic gates to improve observed yield.
- Every unexpected failure is first attributed to Framework, generated project,
  model/provider, infrastructure or Need before editing code.
- Keep the previous official/aborted run immutable when a source change is
  necessary.
- Treat `run_task_foundry_batch(...)` and `run_task_foundry_product(...)` as
  completed upstream production code. Invoke them unchanged; do not implement a
  second sampler in this task.

## 2. Checkpoint A — Baseline hygiene and RED coordinator contract

### Work

- correct the stale README S2 status and archived S2 authority-test paths;
- add RED tests for the specified `generate_environment_v2(...)` order;
- cover typed early termination, immutable stage input, mutually blind author
  preparation, publication absence on failure and one successful cold handoff;
- prove existing stage APIs are reused rather than copied.

### Exit

- the complete deterministic suite is green;
- deleting/bypassing a required S1 stage kills a focused test;
- no coordinator implementation has introduced a domain literal or second
  release/qualification path.

## 3. Checkpoint B — Direct S1 coordinator

### Work

- implement `GenerationConfig` and typed terminal outcomes;
- derive/freeze the public surface from exact actor bytes and real tool output;
- compose Research, Builder, Expected Semantics, both authors, Core,
  Qualification, publication, deterministic zip and cold preparation;
- persist an append-only Host stage ledger with timing and available usage;
- preserve exact failure owner/code/details.

### Real exit

- regenerate one Git/filesystem and one SQLite EnvironmentRelease through the
  single API using unchanged gates;
- both zips cold-verify and prepare; a physical failure produces no release;
- compare observed stage order and identities with the retained S1 baseline.

## 4. Checkpoint C — Campaign identity, resume and aggregation

### Work

- implement canonical NeedSuite, CampaignConfig, CampaignNeedRecord,
  CampaignManifest and AggregateReport records;
- implement sequential runner, atomic record persistence and strict resume;
- add the thin CLI wrapper;
- connect each released environment directly to the existing S2 product entry
  point with the frozen sampling/assessment parameters;
- test tampering, duplicate terminal record, commit/config drift, interrupted
  resume, failed Need retention and honest denominators;
- ensure report aggregation reads sealed records only.

### Exit

- a deterministic controlled campaign containing success, unsupported,
  infrastructure and S2-low-yield outcomes produces correct statistics;
- resume cold-verifies success artifacts and never repeats a terminal Need;
- mutation of any bound input or report count fails.

## 5. Checkpoint D — Freeze official 20-Need campaign

### Work

- author and review 20 domain-diverse Needs without implementation, tool, Task
  or answer leakage;
- freeze NeedSuite, model routes, budgets, target=3, assessment trials=3,
  runtime-skill digests and source commit;
- run deterministic checks and a non-counted infrastructure preflight;
- commit the frozen harness/config before counted execution.

### Exit

- suite/config/source digests are stable and published;
- provider, SearXNG, Fetch/Extract, Codex SDK and uv prerequisites are healthy;
- the preflight only validates infrastructure and is excluded from official
  statistics.

## 6. Checkpoint E — Execute all Needs

### Work

- run every frozen Need through S1 and, when released, unchanged S2;
- monitor without editing frozen semantic code or Need text;
- preserve typed terminal records, event logs and exact artifacts;
- use strict resume only after interruption or infrastructure recovery;
- publish concise progress updates without declaring partial completion.

### Exit

- all 20 Need IDs have exactly one terminal campaign record;
- all released zips and S2 artifacts cold-verify;
- failures and abstentions have typed owners and remain in the denominator.

## 7. Checkpoint F — Publish statistics and project material

### Work

- generate `summary.json` from sealed campaign records;
- write the human-readable report with metric definitions, environment/Task
  distributions, costs, failures and representative cases;
- write compact project/README results and ASu claim-evidence ledger;
- distinguish baseline, official campaign and future S3/S4 claims;
- verify every number by recomputing it from the machine report.

### Exit

- every external-facing claim links to exact evidence and has an ownership
  boundary;
- no pending/unsupported claim enters the final project summary;
- the published report can be regenerated without model calls.

## 8. Checkpoint G — Independent final check and finish

- run Ruff, format, Mypy, full pytest and `git diff --check`;
- run cold verification over all official Release/TaskPack/Corpus locators;
- independently inspect for semantic drift, domain patches, retry-to-success,
  denominator errors, secret leakage and ASu claim inflation;
- update only the relevant coordinator/experiment spec with learned executable
  conventions;
- commit and push code/config first, then final evidence/report commits.

## 9. Validation commands

```bash
uv lock --check
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen mypy src
uv run --frozen python -m pytest -q
git diff --check
```

Focused tests and campaign verification commands will be added with the public
APIs. Real model execution logs and exit status are required in addition to
these deterministic checks.

## 10. Rollback points

- Before B: deterministic baseline hygiene commit.
- After C: fully verified reusable coordinator/campaign harness commit.
- Before E: frozen suite/config/source commit defining the official campaign.
- During E: never rewrite a terminal run; start a new campaign identity after a
  Framework source change.
