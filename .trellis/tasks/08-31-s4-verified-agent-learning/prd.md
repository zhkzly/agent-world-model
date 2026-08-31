# S4 Verified Agent Learning — Product Requirements

## 1. Product goal

Given exact current S1–S3 authority, train one target model through a verified
SFT path and a verified online GRPO path, then determine whether the automatically
generated environments, Tasks and Episodes produce real held-out Agent gains.

```text
EnvironmentRelease + TaskPack/CorpusManifest
+ EpisodeRecord/TrainingEpisodeView
+ target model
-> trainer-neutral learning data
-> SFT checkpoint
-> online S3-backed rollouts
-> terminal verified reward
-> GRPO checkpoint
-> frozen held-out evaluation
```

S4 closes the paper-grade causal claim. A training script that starts, a falling
loss, one optimizer step or one improved training Task is not completion.

## 2. What S3 verification means for S4

S3 does **not** assign a separate Task reward to every tool call.

There are three distinct layers:

### 2.1 Per-call execution integrity

For every proposed call, the shared Host records and validates:

```text
call parseability
known public tool name
input-schema validity
dispatch status
structured public ToolObservation
ordered public trace
```

This determines whether the action was a well-formed public environment action.
It does not determine whether the overall user Task was completed.

A malformed call, unknown tool or invalid argument can terminate the policy as a
valid policy failure. A provider outage, actor crash or invalid observation is a
trusted-path defect and therefore abstains.

### 2.2 Trajectory/process evidence

The full ordered trace is retained. A frozen checker may inspect the trace when
the Task has a real public process requirement, for example performing a
required action before another action. The trace is evidence; it is never
compared with an S2 witness route.

### 2.3 Terminal Task verification

After the policy emits a final answer or reaches a policy terminal state, S3:

```text
inspects pre-close state
closes the acting session
reopens the same native instance without reset
inspects authoritative post-reopen state
runs the frozen task-kind checker over:
  initial facts
  post-reopen facts
  actual public trace
  actual final answer
  fresh protected binding/condition context
```

The terminal checker evaluates the whole Task:

| Task kind | load-bearing truth |
| --- | --- |
| `Atom` | required effect/query truth, target binding, collateral, answer and required process |
| `ForEach` | complete selected member set, no omitted/extra member, member answers, collateral/process |
| `If` | fresh public condition, correct branch semantics, branch outcome, answer/process |

Therefore:

- tool-call validity alone is insufficient;
- final answer text alone is insufficient for state-changing or mixed Tasks;
- final state alone is insufficient when the Task requires an answer or public
  process;
- the terminal checker result is the only Task-success authority.

## 3. Base reward timing and mapping

S4 consumes the unchanged S3 policy:

```text
binary-task-success/1
```

The scalar is produced once per complete rollout, only after terminal
close/reopen verification:

| S3 outcome | S4 score | trainability |
| --- | ---: | --- |
| `verified_success` | `1.0` | trainable |
| `verified_failure` | `0.0` | trainable for RL, excluded from positive SFT |
| `abstain` | `null` | not trainable |

`verified_failure` includes policy-owned failures such as wrong target, partial
completion, collateral damage, wrong/missing answer, malformed public action or
healthy turn-budget exhaustion when the environment/truth path remains valid.

`abstain` includes provider, infrastructure, Environment, Task artifact,
Semantics, Verifier or evidence-integrity defects. S4 must never coerce an
abstention to zero.

No per-tool reward, process reward model or auxiliary shaping is part of the
initial product path. Intermediate call/checker facts may be reported as
metrics, but they cannot alter the binary terminal truth.

## 4. GRPO rollout semantics

For one TaskPack, veRL samples `G` independent rollouts:

```text
same frozen Task semantics
+ same logical StartCase
+ G fresh isolated native instances
+ dynamic identifiers rediscovered in each instance
-> G terminal S3 outcomes
```

Example:

```text
Task T
  rollout 1 -> 1.0
  rollout 2 -> 0.0
  rollout 3 -> 1.0
  rollout 4 -> 0.0
```

The Task/group key is frozen before rollout. veRL owns token generation,
log-probabilities, response masks, group-relative advantage, optimization and
checkpointing. S3 owns tool execution, environment state, terminal checker and
reward truth.

A group containing an S3 `abstain` is invalid for optimization. The initial
implementation records the affected Episode and aborts that optimizer group;
it does not silently replace the sample, retry until success or treat it as a
model failure.

A group whose valid rewards are all equal has zero/degenerate relative signal.
S4 must report the zero-advantage-group rate. It must not invent shaping merely
to force variance.

## 5. Inputs

S4 consumes only cold-verified current artifacts:

- exact EnvironmentRelease and prepared runtime;
- exact TaskPack and CorpusManifest identities;
- exact S3 EpisodeRecord/TrainingEpisodeView bundles;
- one frozen learning split;
- one exact target-model/tokenizer/chat-template profile;
- one exact upstream veRL revision and accelerator runtime.

S4 may request a narrowly demonstrated S3 refactor only when the current
whole-policy `PolicyDriver` boundary cannot support veRL's token-owned async
rollout without duplicating Host tool/checker logic. It cannot alter TaskPack,
checker or Episode truth.

## 6. Outputs

S4 publishes:

```text
LearningSplitManifest
DataReadinessReport
SFTDatasetManifest
TrainingRunManifest
CheckpointManifest
EvaluationRunManifest
LearningUtilityReport
```

Every output binds exact upstream Release, TaskPack, Episode, model, tokenizer,
veRL revision, config and checkpoint identities. Paths and credentials do not
enter semantic identities.

## 7. veRL integration policy

S4 does not copy veRL into this repository and does not fork it first.

Required order:

1. clone official `verl-project/verl` at one exact tested tag/commit;
2. install it editable in a separate environment/worktree;
3. keep Foundry integration code under this repository;
4. fail closed when the installed veRL revision/API differs from the frozen pin;
5. use upstream extension points (`AgentLoopBase`, rollout client, trainer and
   reward fields) before modifying upstream code;
6. permit a minimal recorded patch only after a focused compatibility test
   demonstrates that upstream cannot preserve model-generated token IDs,
   response masks, terminal reward or the shared S3 Host truth path.

The planning candidate is `release/v0.8.0`; Checkpoint 0 must resolve it to an
exact commit after compatibility and hardware tests. veRL Agent Loop remains an
alpha API, so tracking moving `main` is forbidden.

## 8. Offline SFT path

The first SFT dataset consumes only:

```text
verified_success
reward == 1.0
cold-valid TrainingEpisodeView
```

It converts each public Episode to the selected model's exact tool-use chat
format. The trainable mask is:

```text
system/user/reset/tool observation tokens -> 0
assistant tool-call/final-answer tokens    -> 1
```

Failed and abstained Episodes remain available for analysis and RL, but cannot
become positive imitation targets in the initial SFT path.

SFT completion requires a real checkpoint and S3-based evaluation against the
base model under the same evaluation budget; training loss alone is not
evidence.

## 9. Online GRPO path

Implement one custom veRL Agent Loop for one model family:

```text
veRL model generates exact token IDs
-> parse one public tool call or final answer
-> shared S3 Host validates/dispatches the call
-> public observation is encoded with mask 0
-> model continues with generated-token mask 1
-> terminal S3 close/reopen checker
-> reward_score = 1.0 or 0.0
-> veRL computes GRPO advantage and updates the model
```

The adapter must return the exact model-generated token IDs. It must not rebuild
the entire conversation with a decode/re-encode cycle that changes policy
tokens. Tool-observation tokens are environment tokens and therefore masked out
of the policy loss.

The S3 terminal reward is transported, not recomputed, by the veRL adapter.
No LLM Judge or second verifier is allowed.

## 10. Learning splits and final held-out

S4 distinguishes:

1. **instance-held-out** — known structure, unseen Start/binding;
2. **structure-held-out** — known release, unseen `task_structure_id`;
3. **release-held-out** — Need/EnvironmentRelease unseen during training and
   hyperparameter selection.

Existing Git, SQLite and maintenance releases are conformance/development
assets, not the final untouched release-held-out test. After the S4 code,
training recipe and allowed hyperparameter range freeze, select and generate a
new final held-out Need through the unchanged S1–S3 path.

No TaskPack, semantic structure or release assigned to final test may enter SFT,
RL rollout selection or hyperparameter tuning.

## 11. Required experiment matrix

Minimum product comparison:

```text
base model
SFT checkpoint
SFT -> GRPO checkpoint
```

Use matched evaluation budgets and the same S3 verifier. Report at least:

```text
verified success rate
macro success by Task structure/release
pass@1 and repeated-run reliability
wrong-target/partial/collateral/wrong-answer failures
average model turns/tool calls/tokens/latency
abstain rate and owner
GRPO reward variance and zero-advantage-group rate
```

Paper experiments may add RL-only and weak-data baselines after the minimum path
works. They are not allowed to delay or replace the product path.

## 12. Explicitly outside S4

- Task generation, admission, correction or new checkers;
- per-call scalar truth or a general reward DSL;
- LLM-as-Judge reward;
- a generic trainer/algorithm/plugin registry;
- HTTP Episode service, queue, scheduler or distributed environment platform;
- automatic curriculum or automatic Task evolution;
- simultaneous support for PPO, DAPO, GSPO and multiple model families;
- silently retrying/replacing abstained or failed rollouts;
- protected-state features in prompts or training views.

## 13. Acceptance criteria

S4 is complete only when:

- one exact veRL revision and one target-model profile are frozen and verified;
- TrainingEpisodeView deterministically produces a non-leaking SFT dataset;
- one SFT checkpoint is trained and evaluated through S3;
- a custom veRL Agent Loop drives the same S3 Host tool/checker path;
- generated-token and tool-observation masks are proven correct;
- every RL trajectory binds one EpisodeRecord and one transported S3 terminal
  reward;
- abstentions are excluded from optimization without becoming zero;
- one real GRPO optimizer update, checkpoint save/reload and continued rollout
  succeed;
- base, SFT and SFT->GRPO are compared under matched held-out evaluation;
- a newly selected release-held-out environment is evaluated after freeze;
- all gains and failures remain traceable to exact artifacts/config/checkpoints;
- S1–S3 truth and identities remain unchanged.

## 14. Fatal rejection criteria

Reject S4 completion if:

- tool-call success is mistaken for Task success;
- final answer text replaces native state/process/collateral verification;
- per-call shaping is introduced before terminal binary reward is validated;
- `abstain` becomes zero or is silently dropped/replaced;
- generated token IDs are reconstructed through a mismatching template;
- veRL uses a second environment/checker implementation;
- S2 witness or protected data enters model input;
- only training loss or training-Task success improves;
- groups have no reward variance and training is still claimed effective;
- the final held-out Need was used during implementation or tuning;
- a moving veRL `main` or undocumented fork is required for reproduction.
