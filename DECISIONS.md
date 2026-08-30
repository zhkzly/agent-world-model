# Accepted Decisions

## Product stages

- S1 publishes one qualified immutable executable EnvironmentRelease.
- S2 samples and admits Good Tasks, then publishes TaskPack, TaskAssessment and
  CorpusManifest identities.
- S3 runs acting-Agent episodes and maps frozen verifier facts to
  Reward/abstention.
- S4 performs SFT/RL over verified episodes.

## S1 trust boundary

- Actor, TaskSemantics and qualification-only Native Auditor are isolated
  release-local projects.
- S1 qualifies one representative positive execution per declared capability.
- Native Auditor independently checks required native effects and collateral;
  public process, AnswerFields and final answer remain TaskSemantics/Host owned.
- S1 may publish reusable capability, condition, Start, binding and atomic
  evaluator semantics. It does not select or publish the S2 Task distribution.
- Only EnvironmentRelease v2 is supported; no legacy reader, provisional
  release, compatibility switch or fallback.

## S2 required sampling path

- The only required production sampler is Direct Goal-first enumeration over
  qualified Capability/Start/Binding/Condition/Composition semantics.
- Current Goal shapes are Atom, ForEach and If; All is implemented only after a
  real qualified CompositionRule exists.
- Graph, Programmatic and backward-planning mechanisms are optional experiments
  after a measured Direct coverage gap. They never block product completion,
  define Task truth or become persistent Task types.
- Candidate count is not admitted Task count. Structure identity and admission
  are evaluated separately.
- Parameter/entity substitutions and paraphrases do not count as new semantic
  structures.

## Good Task intrinsic validity

- Every final instruction is frozen before witness execution.
- Every acting operand is publicly grounded in instruction, reset context,
  ToolSpec constants or prior ToolObservations.
- Two fresh public-only witnesses prove existence of a solution, not a unique
  reference route.
- Verification checks required outcome, answer, collateral and genuinely
  required process semantics rather than trace equality.
- Production admission executes one discriminating physical case for each
  applicable no-op, wrong-target, wrong-answer, partial, collateral or reload
  failure class.
- Starts are reset-only. Dynamic IDs are rediscovered on every fresh instance.
- Declared persistence is evaluated after real close/reopen of the same native
  instance.
- Unsupported or low-yield sampling returns typed evidence; gates are never
  weakened to hit a Task count.

## Assessment and corpus

- TaskPack identity excludes model trials, difficulty and corpus policy.
- TaskAssessment runs fresh policy trials after admission and preserves all
  failure attribution, calls, tokens, latency and cost.
- CorpusManifest binds exact TaskPack/Assessment pairs and may select a subset
  without changing Task validity.
- Diversity is semantic/execution-structural, not text or entity variation.
- Downstream learning utility is established only by S3/S4 experiments.

## S3 episode and reward boundary

- S3 consumes current cold-verified Release/TaskPack/Corpus authority and cannot
  generate, repair, re-admit or weaken a Task.
- One Host-owned public-policy/tool/lifecycle path is shared by S2 witnesses,
  S2 TaskAssessment and S3 target-policy Episodes. No second Responses loop or
  verifier path is allowed.
- Healthy policy failures preserve their complete public trajectory and receive
  deterministic reward zero after post-reopen verification; they are not
  discarded as exceptions.
- Provider, infrastructure, Environment, Task artifact, Semantics, Verifier and
  evidence-integrity defects abstain with `reward=null`. They never become model
  failures or hard-Task labels.
- The initial reward policy is `binary-task-success/1`: verified success is
  `1.0`, valid verified failure is `0.0`, and untrustworthy evidence abstains.
- TaskAssessment reliability, S2 witness traces and corpus selection cannot
  alter Episode reward.
- The target policy receives only instruction, reset observation, ToolSpecs,
  prior ToolObservations and answer schema. Start input, semantic keys,
  protected bindings, expected branch, native facts, checker data and S2
  witness/admission evidence remain trusted-only.
- Provider-private reasoning/chain-of-thought is not a required Episode artifact.
  S3 stores public function calls, observations, final structured answer or
  public terminal failure and usage.
- The current research-specific hard-coded `AgentRoute` does not identify S3
  target policies. S3 introduces a non-secret PolicySpec and one small
  PolicyDriver boundary, with Responses as the production driver and a later S4
  adapter using the same public Host path.
- EpisodeRecord identity binds exact Task/Release/policy/public trajectory,
  close/reopen evidence, frozen checker result and Reward/abstention. Paths and
  credentials are excluded.
- TrainingEpisodeView contains public trajectory and reward labels only; it
  cannot expose protected facts/checker inputs or TaskPack witnesses.
- S3 does not implement trainer-specific formatting, tokenization, logprobs,
  token masks, optimizer steps or checkpoints. Those remain S4.

## Clean-break and anti-overdesign

- The abandoned RequirementObligation/TaskSpecification/V0 parallel path is
  deleted; Git history is its audit record.
- The actual S2 production APIs are `run_task_foundry_batch` and
  `run_task_foundry_product`; no second candidate/admission path or feature flag
  is allowed.
- Framework code contains no Git/SQLite/booking/domain branches.
- Universal State/Rule/Task/reward ontology, unrestricted per-Task verifier
  code, hidden setup, fake result mutation and mandatory optional samplers remain
  forbidden.
- S3 adds no service, registry, queue, database, plugin system or Agent framework.
  Add a component only for a demonstrated Episode trust or S4 handoff claim that
  existing code cannot prove.

## Execution record

`s2-deletion-first|介入1|返工1|remove duplicate S1/S2 gates+full deterministic suite|红线违反0`

`s2-assessment-corpus|介入1|返工1|fresh public trials+exact TaskPack/assessment corpus binding+real product run|红线违反1`

The violation was starting a reviewer without a fresh explicit user request;
the unfinished verdict was discarded.

`s2-checkpoint-a-reload|介入1|返工1|shared physical lifecycle+mutation licences+SQLite/Git/ForEach/If reopen|红线违反0`

`s2-direct-authority-restoration|介入1|返工1|user correction+RED authority audit+delete parallel B path+restore Direct plan|红线违反1`

The violation was promoting optional Graph/Programmatic mechanisms and an
isolated contract path into mandatory product authority without rechecking the
accepted Direct sampling plan.

`s3-plan-convergence|介入1|返工1|adversarial review+exact input cold-read+scope deletion|红线违反1`

The violation was allowing the candidate plan to accumulate multi-defect and
atomic-publication machinery before the user restated the anti-overdesign
boundary; both were removed before task activation or product implementation.
