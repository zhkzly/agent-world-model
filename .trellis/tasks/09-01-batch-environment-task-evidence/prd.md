# Batch Environment and Task Evidence Campaign

## Goal

Run the existing paper-grade S1 and S2 product path over a frozen cross-domain
Need suite and publish reproducible evidence about environment generation and
good-Task sampling. The result must support honest project, resume, portfolio
and later paper claims without changing Task truth or retrying failures into a
misleading success-only showcase.

## Background and confirmed facts

- `PROJECT.md` defines the product chain as Need -> S1 EnvironmentRelease -> S2
  TaskPacks/TaskAssessments/CorpusManifest.
- S1 and S2 already have real cross-domain evidence for Git maintenance, an
  SQLite ocean-demurrage workflow and one post-freeze held-out equipment-
  maintenance Need.
- The three retained product reports cover 42 enumerated candidates, 32
  per-release unique structures, 9 admitted TaskPacks and 27 independent Luna
  assessment trials, of which 26 succeeded.
- `run_task_foundry_product(...)` is the production S2 entry point.
- Remote inspection at `origin/main@6246740` and the newer
  `origin/s4-verified-agent-learning` confirms that the complete S2 Direct
  sampler is already implemented. Both refs use `run_task_foundry_batch(...)`
  and `run_task_foundry_product(...)`; no newer alternative sampling path
  exists on the remote.
- The individual S1 stages and the `generate_environment_v2(...)` contract
  exist, but `.trellis/spec/backend/s1-coordinator.md` explicitly records that
  the single direct Python S1 coordinator is not implemented at current HEAD.
  The previous three releases were closed through stage-by-stage execution.
- Therefore a repeatable campaign needs one minimal S1 coordinator or an
  equivalent one-off script. A one-off script would produce numbers but would
  not substantiate a reusable environment-generation system.

## Key decisions

- Implement the already-specified thin `generate_environment_v2(...)` API
  before running the campaign; do not use a one-off stage-pasting script.
- Freeze 20 cross-domain Needs for the first official campaign.
- Request three structurally distinct admitted Tasks per released environment
  and run three independent assessment trials per admitted Task.
- Reuse the existing Direct Goal-first sampler unchanged. This task implements
  no replacement sampler, Goal compiler, admission rule or corpus selector.
- Treat the 20-Need run as an official publishable result. A later 50-100 Need
  paper run is a separate scale extension, not permission to discard failures
  from this campaign.

## Requirements

### R1. Frozen campaign authority

- Freeze the ordered Need suite, campaign configuration, code commit, model
  routes and prompt/skill digests before the first counted run.
- Needs must be domain descriptions, not task answers, reference trajectories
  or environment-specific implementation instructions.
- The official denominator includes every frozen Need, including unsupported,
  blocked and failed outcomes.

### R2. Minimal repeatable S1 execution boundary

- Provide the already-specified direct `generate_environment_v2(...)` boundary
  by composing the existing Research, Builder, semantic author, mutually blind
  verifier, physical Qualification, publication and cold-verification stages.
- This work may add orchestration and typed run records only. It must not add a
  product node, weaken Qualification, introduce domain branches or alter the
  existing S1/S2 semantic contracts merely to increase yield.
- A failed stage must stop later stages for that Need and preserve one typed
  owner/code/message record.

### R3. Execute the existing S2 sampler

- Run every Need in a fresh work root and retain immutable stage artifacts.
- For every qualified EnvironmentRelease, call the unchanged
  `run_task_foundry_product(...)` path with a fixed target of three structurally
  distinct admitted Tasks and three independent assessment trials per Task.
- Preserve its current production sequence: Direct Atom/ForEach/If candidate
  compilation from qualified release semantics, structural deduplication and
  balanced selection, checker/instruction freeze, two fresh public witnesses,
  applicable physical challenges, TaskPack persistence, independent assessment
  and CorpusManifest selection. All remains unsupported unless a release
  actually supplies a qualified CompositionRule.
- Low Task yield and justified abstention are valid results; the campaign must
  not lower gates or patch one domain to reach a numeric floor.
- Restarting the campaign must cold-verify completed identities and resume
  unfinished Needs without silently rerunning or replacing counted outcomes.

### R4. Metrics and provenance

- Emit a machine-readable campaign manifest binding the Need-suite digest,
  source commit, route/config digests and every S1/S2 run/artifact identity.
- Report at least:
  - Need count and domain/backend distribution;
  - Research, Builder, Qualification and Release outcomes;
  - end-to-end release rate and typed failure attribution;
  - elapsed time, model calls/turns, tokens and available cost data per stage;
  - public tool, qualified capability, StartCase and Qualification-case counts;
  - candidate, per-release structural, admitted and rejected Task counts;
  - Goal-kind distribution and rejection codes;
  - admission witness count, assessment reliability, turns, tokens and latency;
  - held-out or cross-domain transfer results separately from conformance data.
- Never calculate a yield from candidates that the target-stopping policy did
  not actually attempt. Every percentage must publish its numerator,
  denominator and metric definition.

### R5. Evidence-backed project material

- Publish one human-readable experiment report with representative environment,
  Task and failure case studies linked to exact artifacts.
- Publish a compact project-results section and ASu-style claim-evidence ledger.
- Resume wording must distinguish implemented capability, observed experiment
  results, model-relative assessment and future scale claims.
- Do not use “large-scale”, “production adoption”, “accuracy” or an invented
  improvement percentage unless the campaign evidence directly licenses it.

### R6. Evidence hygiene

- Correct stale public documentation that still says S2 is unimplemented.
- Make the full deterministic repository quality command green; archived task
  movement must not leave authority tests pointing at deleted active paths.
- Keep exploratory/debug artifacts outside the official campaign denominator
  and label retained historical baselines separately.

## Acceptance criteria

- [ ] The frozen Need suite and campaign configuration have stable digests and
      are committed before official counted execution.
- [ ] One direct, domain-neutral S1 coordinator can produce a passed cold-opened
      Release or a typed terminal non-release from each Need.
- [ ] Every frozen Need has exactly one terminal campaign record; no failure is
      omitted, overwritten or counted as a success after an unrecorded retry.
- [ ] Every released environment is cold-opened and passed unchanged to the
      production S2 product API.
- [ ] Every admitted TaskPack retains two fresh public-only witnesses and the
      applicable physical negative evidence required by S2.
- [ ] The campaign report exposes all required counts, rates, resource metrics,
      definitions and artifact links and can be regenerated from the manifest.
- [ ] The ASu-facing project statements each map to a confirmed evidence-ledger
      entry with responsibility boundary and interview-expandable detail.
- [ ] README and deterministic repository checks agree with the final observed
      implementation state.
- [ ] No mock provider, canned environment, handwritten success Task, domain
      Framework branch, compatibility path or weakened gate enters official
      campaign statistics.

## Out of scope

- S3 rollout/reward implementation and S4 training.
- Graph, Programmatic or other alternative Task samplers.
- New Goal types, verifier DSLs or environment semantic contracts.
- Per-domain prompt/Skill tuning after counted outcomes are observed.
- Claiming downstream training improvement before S3/S4 experiments exist.
