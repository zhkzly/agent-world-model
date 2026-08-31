# S4 Verified Agent Learning — Implementation Plan

## 1. Execution rules

- S3 remains the sole environment/checker/reward authority.
- Tool calls receive execution validation and trace capture, not Task reward.
- Terminal reward is transported from S3 only after close/reopen verification.
- Start each checkpoint with a reachable behavioral RED, then implement the
  smallest current consumer.
- Use one model family, one tokenizer/tool-call format, one veRL pin, one SFT
  path and one GRPO path.
- Do not fork/patch veRL before an extension-point test proves it necessary.
- Green CPU tests do not replace a real GPU rollout, optimizer update,
  checkpoint reload or S3 held-out evaluation.
- Do not implement S1–S3 corrections inside S4 unless a concrete interface
  blocker is causally demonstrated and the upstream truth remains unchanged.

## 2. Baseline and branch

Base:

```text
main@6246740e74be51fc10d933bd70c4f7ba804282f9
```

This base contains completed S1–S3 and exact current Release, TaskPack,
CorpusManifest, EpisodeRecord and TrainingEpisodeView authority.

Rollback is Git history. No compatibility mode, duplicate S3 runtime or vendored
veRL tree is permitted.

---

## 3. Checkpoint 0 — Learning readiness and external authority freeze

### Product claim

The available data, hardware and upstream APIs can support a meaningful first
SFT/GRPO experiment before training code is written.

### Work

Create a read-only readiness command/report that cold-reads current artifacts and
reports:

```text
Release count
TaskPack count
unique task_structure_id count
Goal/capability/Start distribution
verified-success/failure/abstain Episode count
assistant-generated token count estimate
base-policy success distribution
candidate GRPO group reward variance
zero-advantage-group rate
maximum trajectory/context length
```

Freeze:

```text
one exact target model/tokenizer revision
one public tool-call/chat template
one accelerator/training backend
one exact veRL tag/commit
one SFT and one GRPO budget
train/dev/instance-held-out/structure-held-out assignments
rule for selecting a new final release-held-out Need after code freeze
```

Repository additions:

```text
integrations/verl/REQUIRED_VERL.txt
src/agent_env_foundry/learning_splits.py
src/agent_env_foundry/learning_artifacts.py
scripts/s4_readiness.py
```

The planning candidate is `release/v0.8.0`; record the resolved commit after
checking the actual AgentLoop/AgentLoopOutput API and the selected GPU runtime.

### Behavioral RED

At least these must fail before implementation:

- same TaskPack/structure/release assigned to incompatible split roles;
- nonexistent or tampered Episode/Task/Release identity;
- verified failure or abstain counted as positive SFT data;
- moving/unresolved veRL ref accepted as frozen;
- model/tokenizer/template identity absent;
- readiness claims GRPO signal when all group rewards are equal;
- protected field appears in a prospective learning sample.

### Real exit

- install the exact veRL checkout in an isolated environment and import the
  required Agent Loop APIs;
- run one current model/tokenizer encode/decode/tool-template preflight;
- produce a cold-readable readiness report;
- either declare data ready or stop with `UpstreamDataInsufficient` and an exact
  S1/S2/S3 expansion request.

### Stop conditions

Stop S4 training when:

```text
no verified-success SFT trajectories
too few independent Task structures
base policy is uniformly 0% or 100% under the intended budget
all candidate GRPO groups have no reward variance
abstain rate makes truth unreliable
available context cannot contain the public trajectory
```

Do not solve these by lowering checkers or fabricating data in S4.

---

## 4. Checkpoint 1 — Trainer-neutral verified SFT data

### Product claim

Every SFT sample is a deterministic, non-leaking transformation of one cold-valid
S3 verified-success Episode.

### Work

Implement:

```python
build_sft_dataset(
    episode_bundles,
    learning_split,
    model_profile,
    output_root,
) -> SFTDatasetManifest
```

For exactly one selected model format:

- reconstruct public system/user/reset/tool conversation;
- include exact public ToolSpecs in the model-supported form;
- retain assistant tool-call arguments and final answer;
- retain tool observations as non-trainable context;
- emit token IDs and assistant-only loss mask;
- bind sample ID to source Episode ID, TaskPack, Release and structure;
- reject any failed/abstained or non-cold-valid Episode;
- store counts/checksums/config, not protected state.

Suggested files:

```text
src/agent_env_foundry/learning_data.py
integrations/verl/foundry_sft_data.py
tests/test_learning_data.py
integrations/verl/tests/test_sft_data.py
```

### Behavioral RED

- tool-observation token receives loss mask 1;
- assistant tool-call token receives mask 0;
- model-generated assistant tokens are changed by a second render pass;
- final answer or tool argument is dropped;
- failed/abstained Episode enters positive SFT;
- protected/checker/S2 witness data enters the sample;
- one Episode produces nondeterministic bytes/config identity;
- train/test structure leakage passes.

### Real exit

- build a real dataset from current verified-success Episodes;
- decode several samples and compare them with their source TrainingEpisodeViews;
- run one forward/loss batch on the selected target model;
- report actual trainable versus observation token counts.

### Stop conditions

- the selected model cannot represent the public tool schema/call format without
  changing Task semantics;
- generated assistant token spans cannot be separated from environment spans;
- the dataset is too small or structurally redundant for the declared claim.

---

## 5. Checkpoint 2 — SFT checkpoint and frozen S3 evaluation

### Product claim

The verified SFT dataset can produce a real checkpoint whose Agent behavior is
measured by unchanged S3 truth rather than training loss.

### Work

Use the pinned veRL SFT path or its documented dataset interface. Keep model and
training configuration fixed and minimal. Publish:

```text
TrainingRunManifest
CheckpointManifest
EvaluationRunManifest
```

Required comparisons under the same S3 Task/rollout budget:

```text
base model
SFT checkpoint
```

Evaluate through the current S3 runtime/TaskPacks. Record success, failure,
abstain, turns, calls and tokens.

### Behavioral RED

- checkpoint manifest does not bind base model/tokenizer/data/config;
- evaluation uses a different prompt/tool template from training without an
  explicit comparison;
- training or S2 admission witness trajectory is used as test truth;
- only loss is reported;
- a checkpoint cannot be cold loaded into the S3/rollout policy path;
- evaluation silently retries failures.

### Real exit

- complete a nonzero SFT run;
- save, cold-load and resume/evaluate the checkpoint;
- run matched base versus SFT S3 evaluation on dev and instance-held-out Tasks;
- report gains or an honest `NoLearningGain` result.

### Stop conditions

Do not proceed to RL merely because SFT loss decreased. If the checkpoint cannot
produce valid tool calls or is materially worse on all dev metrics, diagnose the
data/template path first.

---

## 6. Checkpoint 3 — Shared incremental S3 episode seam

### Product claim

veRL can own asynchronous model generation while all environment actions and
terminal truth still pass through the same S3 Host implementation.

### Work

Begin with a behavioral test against current S3 showing that an async external
generator cannot interleave one model turn and one tool result through
`run_task_episode` without taking over the whole synchronous PolicyDriver loop.

Extract only the currently consumed environment-side seam:

```python
open_interactive_episode(...) -> InteractiveEpisodeSession
session.public_input
session.apply_decision(DriverDecision) -> public call results / terminal state
session.finalize(...) -> EpisodeRecord
```

Refactor current Responses/S3 execution onto the same primitives. Preserve:

```text
EpisodeRecord/TrainingEpisodeView format and identity
TaskPack/checker truth
existing Responses behavior
close/reopen lifecycle
failure/abstain ownership
```

Suggested files:

```text
src/agent_env_foundry/public_agent.py
src/agent_env_foundry/episode_runtime.py
tests/test_interactive_episode.py
```

Do not create a service, generic environment protocol, async framework or second
artifact type.

### Behavioral RED

- S4 can call actor.invoke directly and bypass Host validation;
- session exposes trusted facts/binding/checker;
- Responses and veRL use different call/observation ledgers;
- finalization before close/reopen yields reward;
- reset can be called twice;
- Task/Release/checker identity changes mid-session;
- current S3 physical success/failure/abstain results change after refactor.

### Physical exit

- current Responses driver passes existing Git/SQLite/maintenance episodes via
  the refactored shared core;
- a deterministic externally driven multi-turn session produces the same
  Episode semantics;
- one policy failure after a real mutation still closes/reopens/checks and gets
  zero.

### Stop conditions

If current `PolicyDriver` can be used by veRL with exact token ownership through a
smaller proven adapter, delete the session refactor. Keep only the smallest
working shared path.

---

## 7. Checkpoint 4 — Pinned veRL Agent Loop and terminal reward bridge

### Product claim

The training model itself performs multi-turn tool use, and one S3 terminal score
is attached to the exact generated token trajectory without decode/re-encode
mismatch.

### Work

Implement:

```python
class FoundryAgentLoop(AgentLoopBase):
    async def run(...) -> AgentLoopOutput:
        ...
```

Under the frozen model/template:

- cold-resolve exact Release/TaskPack authority;
- open one fresh interactive S3 Episode;
- build initial prompt IDs once;
- call veRL `LLMServerClient.generate` with token IDs and sticky request ID;
- retain every returned model token ID with response mask 1;
- decode only a parsing copy;
- apply public tool calls through the S3 session;
- encode returned ToolObservations with response mask 0;
- finalize S3 on final answer/policy terminal;
- persist/cold-read the Episode bundle;
- set `AgentLoopOutput.reward_score` from S3 `1.0` or `0.0`;
- raise a typed rollout-abstain after persistence for S3 `null`.

Suggested files:

```text
integrations/verl/foundry_agent_loop.py
integrations/verl/configs/foundry_grpo.yaml
integrations/verl/tests/test_foundry_agent_loop.py
```

### Behavioral RED

- generated assistant tokens are replaced by tokens from re-rendered messages;
- tool observation token has mask 1;
- assistant tool-call/final-answer token has mask 0;
- reward is computed before S3 finalization;
- reward differs from the EpisodeRecord;
- `null` is converted to zero;
- S2 witness/protected binding/checker enters the prompt;
- one rollout reuses another rollout's native instance or driver/session;
- all-equal group is hidden from metrics.

### Upstream compatibility gate

First prove the overlay against the exact unmodified veRL pin. Only if a focused
test fails because the extension API cannot preserve the required contract may a
minimal patch be proposed. Record:

```text
upstream SHA
failing API contract
patch diff
compatibility test
upstream issue/PR when appropriate
deletion condition
```

### Real exit

Run one group of at least two fresh rollouts from the same TaskPack using the
actual veRL inference server and current checkpoint. For every member retain:

```text
AgentLoopOutput token IDs/mask
Episode ID
S3 reward/disposition
TaskPack/group identity
```

Prove numeric rewards match and an injected abstain prevents optimizer use.

### Stop conditions

- exact token/mask truth cannot be established;
- the model format cannot reliably separate tool calls/final answers;
- upstream modification grows beyond the named compatibility defect;
- the adapter needs a second verifier or environment runtime.

---

## 8. Checkpoint 5 — One real GRPO update and checkpoint resume

### Product claim

A valid S3-terminal reward group drives one real veRL GRPO optimizer update and
produces a reloadable checkpoint.

### Work

Initial RL configuration:

```text
parent checkpoint: accepted SFT checkpoint
advantage estimator: GRPO
reward: S3 binary terminal only
group size: one frozen value
no auxiliary shaping
no reward model
no automatic curriculum
no silent rollout retry/replacement
```

Before update, validate every group:

```text
exact group/task identity
cold-valid EpisodeRecord
numeric reward for every member
at least one model-generated token
response mask consistency
no protected-token leakage
```

Persist optimizer/run/checkpoint identities and the exact Episode IDs used by
the step.

### Behavioral RED

- abstain member reaches advantage computation;
- missing Episode or mismatched reward reaches optimizer;
- two TaskPacks share one GRPO group;
- response masks are ignored;
- no-reward-variance group is reported as a useful update;
- checkpoint does not bind its parent/data/config/veRL pin;
- rollout weights are not updated/synchronized before the next generation.

### Real exit

```text
fresh S3 rollout group
-> terminal rewards
-> GRPO advantages
-> backward/optimizer step
-> checkpoint save
-> cold reload
-> another fresh S3 rollout
```

Report parameter/checkpoint change and training diagnostics. A step with zero
advantage everywhere does not satisfy this exit.

### Stop conditions

- all available groups are zero variance;
- abstain frequency repeatedly blocks updates;
- checkpoint/rollout weights are not synchronized;
- the only way forward is to change S3 reward truth.

---

## 9. Checkpoint 6 — Bounded training and final learning utility

### Product claim

The proposed automatically generated verified data improves Agent behavior on
frozen held-out Tasks under a matched budget.

### Work

Freeze before final test:

```text
Framework/integration commits
veRL/model/tokenizer pins
SFT/GRPO configurations
allowed hyperparameter range
learning split policy
training/evaluation budgets
primary metric
```

Then select a new final release-held-out Need and run the unchanged pipeline:

```text
S1 release
-> S2 TaskPacks/Corpus
-> S3 evaluation Tasks/Episodes
-> base/SFT/SFT->GRPO matched evaluation
```

Minimum report:

```text
verified success with confidence interval
macro result by release/structure
pass@1/repeated reliability
wrong-target/partial/collateral/wrong-answer categories
calls/turns/tokens/latency
abstain owner/rate
GRPO reward variance/zero-advantage groups
training tokens/rollouts/optimizer steps
```

### Required comparisons

```text
base model
verified-success SFT
verified-success SFT -> terminal-reward GRPO
```

Paper baselines such as unverified trajectories, parameter-only redundant Tasks
or RL-only require a separate matched-budget experiment after the minimum path.

### Behavioral RED

- final Need appears in code, data or tuning history before freeze;
- same TaskPack/structure leaks across train and final test;
- evaluation budget differs across checkpoints;
- success is computed outside S3;
- failed/abstained runs are dropped from the report;
- result claims improvement from loss or one cherry-picked Task;
- config/checkpoint/artifact identities cannot be reconstructed.

### Real exit

Publish a cold-reproducible LearningUtilityReport. Completion may be:

```text
SUPPORTED: stable held-out gain under the frozen protocol
NOT SUPPORTED: valid experiment finds no gain or unacceptable cost
```

A negative result is scientifically complete; weakening S1–S3 truth to obtain a
positive result is forbidden.

---

## 10. Required validation

At every checkpoint run the existing deterministic project gates plus focused S4
tests. After veRL is introduced, also record:

```text
exact upstream commit/submodule state
Python/CUDA/PyTorch/vLLM-or-SGLang versions
model/tokenizer revisions
GPU topology
full resolved training config
one hardware smoke result
```

Do not claim GPU/veRL completion from fake clients or CPU-only unit tests.

## 11. Completion

S4 completes only when Checkpoints 0–6 satisfy their real exits. Additional RL
algorithms, models, services, distributed environment scheduling, curriculum or
Task evolution are later research tasks, not completion gates.
