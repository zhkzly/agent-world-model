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

`s3-baseline-harness|介入0|返工1|archived S2 authority path+python -m pytest|红线违反0`

`s3-cp1-contracts|介入0|返工1|25 focused+392 full+Mypy/Ruff+4 semantic mutants|红线违反1`

The CP1 violation was using missing-module import noise as the initial RED.
Mutation evidence later proved the contract tests, but did not rewrite that
history; every later checkpoint must begin with a reachable behavioral RED.

`s3-cp2-public-loop|介入1|返工2|behavioral RED+37 focused+425 full+live Responses+semantic mutation+independent review|红线违反1`

The CP2 redline was temporary overgrowth of the existing 350-line public loop
to 1202 lines despite the anti-overdesign guard. It was reduced to one 866-line
Host/adapter implementation before review. Live evidence then found the blank
Responses terminal bug; independent rework corrected that and three adjacent
attribution defects before acceptance. No CP3 or later component was introduced.

`s3-cp1r-deletion|介入1|返工1|structural JSON RED+remove checkpoint/freeze-thaw+427 full+mutation licence+independent review|红线违反0`

The user challenged future-oriented retention. CP1R therefore removed the
producer-less checkpoint field and non-JSON deep-freeze framework instead of
preserving them for CP4/S4. Current consumers require only caller-alias
snapshotting and fresh document projection; directory layout remained unchanged.

`s3-cp2r-deletion|介入1|返工1|single-snapshot RED+single capture ledger+427 full+live Responses+2 mutation licences+independent review|红线违反0`

CP2R deleted the caller/actor divergence check, adapter-side pending-result
ledger, parallel mutable TraceEvent list, duplicate defect details and the
self-attribution rule. The current Host, Responses owner split and S2 success
projection remain. Package and directory restructuring were explicitly deferred
by the user.

`s3-plan-merge-lifecycle|介入1|返工1|delete standalone CP3+merge into exact runtime+independent plan review|红线违反0`

The standalone callback lifecycle had no current production consumer. It and
the TaskAssessment side repair were deleted; the exact Task Episode runtime now
owns only the lifecycle facts required by its EpisodeRecord. No directory or
package split is part of S3.

`s3-cp3-exact-runtime|介入1|返工2|If authority RED+Atom/ForEach/If runtime+452 full+4 mutation licences+Git/SQLite physical+independent review|红线违反1`

The CP3 redline was allowing the new runtime to reach roughly 990 lines before
its first focused test existed. Main stopped the worker, required tests first,
and deletion review removed extra catalog dependencies, over-tight If/ForEach
truth, a duplicate checker-result ledger and future carriers before acceptance.

`s3-cp4-paired-view|介入1|返工2|checker-binding RED+paired canonical cold reader+476 full+3 mutation licences+real relocation+independent review|红线违反0`

CP4 exposes only one non-leaking view contract and two paired IO functions.
Independent review found and fixed four fresh-ID malformed checker-request
acceptances; no independent view trust, artifact framework or future consumer
surface was added.

`s3-cp5-exact-batch|介入1|返工2|shared-root RED+exact Corpus serial batch+486 full+3 mutation licences+Git/SQLite physical+independent review|红线违反1`

The CP5 redline was allowing the new 709-line batch source to appear before its
own focused tests. Source expansion was frozen; subsequent work added tests and
only fixed unattributed-abort and same-Task stop behavior. The final batch has
one class, one public function and no scheduler/retry/framework surface.

`s3-cp6-frozen-acceptance|介入0|返工0|486 full+all authority cold IDs+live Responses batch+scripted Git/SQLite/maintenance+independent frozen review|红线违反0`

CP6 froze `bc778aa` and introduced no production code. The exact current S3
runtime transferred across Git, SQLite and held-out maintenance authority, and
the real Responses adapter plus scripted second driver used the same serial
batch/Host path without trainer or service scope.

`batch-env-task-harness|介入2|返工3|focused RED+6 mutation licences+full suite+real S1 Release+real S2 Product/Corpus|红线违反1`

The redline was a worker creating a 946-line idealized coordinator fixture
after prolonged exploration. Main stopped it, deleted the file, and replaced
it with focused orchestration tests and physical actor/Qualification evidence.
Remote inspection proved the existing Direct sampler remained the sole S2 path;
real execution then closed one new Release and three assessed TaskPacks before
the official 20-Need campaign freeze.

`batch-author-context|介入1|返工1|cross-run roleplay trace+author scaffold RED+6 mutation licences+497 full tests|红线违反0`

Agent-owned semantic errors remain Agent-owned, while deterministic pytest
setup and complete same-turn validation feedback moved to Framework. No Need,
Qualification rule, S2 sampler or domain-specific instruction changed.

`batch-logical-repair-rollback|介入1|返工1|two real Qualification counterexamples+mutual-blindness audit+499-to-497 test rollback|红线违反1`

The rejected approach inferred author ownership from a failed logical axis.
That inference could make independent readers converge on one observed case,
so it was removed before any Release; logical disagreements remain terminal.

`batch-answer-source-placement|介入1|返工1|real Need-4 artifact+shared-validator RED+3 mutation licences+498 full tests|红线违反0`

The unchanged AnswerField source validator now runs while the Semantics Author
still has correction authority and again at final Qualification. The old
Qualification-local copy was deleted; no source rule or admission gate changed.

`s1-s2-realignment-cp-a|介入0|返工1|authority docs+v3 contract RED/green+5 mutation licences|红线违反0`

Checkpoint A changes product/spec authority and adds an unexported pure v3
descriptor contract only. Public release/generation/preparation behavior stays
v2 until the atomic Checkpoint C cutover; no compatibility reader was added.

`s1-s2-realignment-cp-b|介入0|返工1|real Codex actor+physical refusal/mutation/reopen/readback+7 mutation licences+522 full tests|红线违反0`

Checkpoint B adds one task-neutral state reader in the actor project, one
stdlib child and one Host proxy. The first real boundary caught and repaired a
schema lie that business assertions would otherwise miss; no Release or Task
path was switched.

`s1-s2-realignment-cp-c|介入0|返工1|internal v3 conformance+ZIP/cold relocation+shared physical runtime+5 mutation licences+537 full tests|红线违反0`

Checkpoint C adds one unexported environment-only S1 vertical and leaves the
sole public v2 API unchanged until atomic cutover. A pre-commit code-volume
audit rejected a copied 735-line preparation implementation; task-neutral uv,
child transport, Actor proxy and protected snapshot behavior now exist once in
`physical_runtime.py`, while an isolated-process import test proves the v3
coordinator loads no old semantics, Qualification, Verifier or Task module.

`s1-s2-realignment-cp-d|介入1|返工3|real Git+SQLite Releases+native truth/reopen/refusal proof+5 mutation licences+543 full tests|红线违反0`

Checkpoint D produced two contrasting cold Release IDs and retained earlier
failed artifacts instead of counting them. Live evidence moved only uniquely
determined ABI/exogenous corrections into Framework: missing input object root,
an exact ToolObservation wrapper around `output_schema`, and Host-assigned
instance-root replay projection. A malformed native Git history identifier was
not normalized by Framework; Codex repaired the actor and added independent Git
truth tests. No Task, checker, reward or domain branch entered S1.

`s1-v3-20-need-campaign|介入1|返工3|42 attempts+20 unique Releases+204 tools+cross-attempt context audit|红线违反0`

The exact official suite reached 20/20 current Releases without counting the
two Checkpoint-D diagnostic Needs. The campaign exposed concurrency-three auth
exhaustion, two schema/replay candidate defects and five post-release ambient
clock defects. Final actors contain no raw ABI drift or ambient entropy calls.
Known failures now become same-thread Builder preflight feedback through full
environment Conformance and an AST entropy scan; Framework does not infer
nullable domain semantics from one observed value. The evidence report states
that S2 Task/reward and training-gain claims remain unproven.

`s1-v3-host-diagnostics|介入0|返工1|real Codex 9-step canary+dual-instance Host replay+5 mutation licences+560 full tests|红线违反0`

The diagnostic carrier contains only reset input, public tool arguments,
success/refusal expectation, stable refusal code and protected-state effect.
Framework owns execution, schema validation, refusal atomicity, two-instance
replay and reopen. Exact keys prohibit instructions, answers, rewards,
checkers, witnesses and admission claims, so this strengthens S1 mechanics
without creating Task truth or a second verifier authority.

`s1-s2-realignment-cp-e|介入0|返工1|real v3 Release+5-turn/9-tool proposal+Codex checker+8 mutation licences+572 full tests|红线违反0`

The proposal policy saw only public Need/Brief/reset/tool material while Host
captured protected state. One immutable checker project became the candidate's
only semantic code authority and froze a new Task identity before any witness.
The sole rework removed an unsupported Responses `uniqueItems` keyword while
retaining deterministic Host deduplication; no retry, compatibility path,
domain branch or old `evaluate_atom` dependency was added.

`s2-direct-sampler-cut|介入3|返工1|revert 2637 lines+delete old S2/S3 9379 lines+real zero-challenge TaskPack+full suite|红线违反1`

The user identified that per-Task physical challenges were pressure-testing
our checker implementation rather than sampling Tasks. Commit `219d318` was
reverted intact. The replacement uses one universal path—executed proposal,
checker sanity and two fresh public solves—and emits no challenge categories.
Old ForEach/If, batch/assessment and Episode product code was deleted before
further feature work; the retained canary artifacts remain diagnostic only.

`s1-s2-old-authority-deletion|介入0|返工0|v2/semantics/verifier零引用+351 tests+release mutation licence|红线违反0`

Only EnvironmentRelease/3 and the Direct Task sampler remain as product
authority. Shared canonical ZIP/hash/path helpers survive without a v2 reader,
descriptor, publisher or compatibility switch; actor/checker are the only
authored project roles.

`s2-sampling-measurement|介入0|返工0|stage latency+turn/tool/token evidence+mutation licence|红线违反0`

`s1-semantic-qualification|介入1|返工1|SQLite+Git+Clinic real Releases+4 semantic mutants+5 mutation licences+full suite|红线违反0`

The fresh reviewer consumes only frozen Requirement groups, public ToolSpecs
and a Host-derived evidence projection. Full evidence remains release-bound;
the model view deduplicates initial snapshots and represents all state changes
as complete JSON leaf diffs plus exact reopen/reset equality. No domain branch,
Builder self-verdict, Task, answer or reward enters S1 acceptance.

`s1-s2-projection-identity|介入0|返工0|cold Release projection digest→TaskContract exact rename+focused tests|红线违反0`

`qualified-campaign-scheduling|介入0|返工0|serial warmup→same-id parallel resume+mutation licence|红线违反0`

`s2-exhaustive-budget-sampling|介入0|返工0|15 attempts+no Task quota+pre-checker structural dedup+2 mutation licences|红线违反0`

`s2-task-campaign-handoff|介入0|返工0|cold TaskPack+relocation+resumable records+CorpusManifest+2 mutation licences|红线违反0`

`s2-effect-structure-dedup|介入1|返工1|15-candidate real Library replay: duplicate recall 2/13→13/13; live cross-domain validation pending|红线违反0`

Task structure is conservatively keyed by normalized protected state-effect
shape (and refusal outcome when present), not incidental public inspection order,
entity array position, paraphrase, or answer-field spelling. Previously accepted
public instructions are fed only to the next proposal role to encourage a new
objective; they never enter the acting-policy view or Task truth.

`responses-schema-projection|介入1|返工1|nested additionalProperties+uniqueItems live failures→shared official-subset projection+local 8317 probe+2 mutation licences|红线违反0`

Release and Task schemas remain full Draft 2020-12 Host authority. Responses
tool/answer requests use one shared mechanical projection of that frozen schema:
all wire-visible object fields are required, objects are closed, and unsupported
wire-only constraints are omitted. `contains` supplies `items` when possible;
a genuinely untyped array is returned to the Proposal Agent before checker
construction. A 26-Candidate/29-ToolSpec preflight found exactly the two known
bare arrays and no further wire-shape failure. The exact model result is still validated
against the original schema, so the adapter cannot turn an invalid answer into a
passing Task.
