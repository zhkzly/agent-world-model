# S4 Verified Agent Learning — Technical Design

## 1. Design judgment

S4 should be a thin learning layer over frozen S1–S3 authority, not a new Agent
platform.

The shortest valid product path is:

```text
S3 TrainingEpisodeView -> one SFT dataset/checkpoint
S3 interactive Episode runtime + pinned veRL AgentLoop -> one GRPO checkpoint
base/SFT/GRPO -> frozen S3 held-out evaluation
```

The main implementation risk is not the optimizer. It is preserving one exact
policy token trajectory while veRL owns generation and S3 owns environment
execution and terminal truth.

## 2. Reward authority

### 2.1 What is checked at each tool call

The existing S3 Host remains responsible for:

```text
parse call
resolve known tool
validate arguments against ToolSpec
invoke real actor code
validate/record public observation
append the dispatched call to the checker-facing trace
```

These are action-integrity checks. They do not produce a scalar Task reward.

### 2.2 What is checked at the end

The frozen task-kind checker runs only after the policy terminates and S3 has
closed/reopened the same native instance. It consumes actual before/after facts,
trace and final answer. The result can include multiple axes, but one boolean
`satisfied` remains Task truth.

```text
Atom    -> target effect/query + answer + collateral + required process
ForEach -> every selected member + answer + collateral + required process
If      -> public condition/branch + branch Task truth
```

The S4 adapter never derives reward from call count, tool name, answer text alone
or an S2 witness. It transports the existing S3 `RewardOutcome`.

### 2.3 Terminal score transport

For a trainable rollout:

```python
agent_loop_output.reward_score = episode_record.reward.reward  # 1.0 or 0.0
```

Current veRL Agent Loop converts a present trajectory-level `reward_score` into
a reward tensor at the final response position. The configured GRPO estimator
then computes group-relative advantages. No custom model judge is required.

An S3 abstention is persisted first and then raises a typed S4 rollout failure so
that the current optimizer group does not update. It is never represented as a
numeric reward.

## 3. Upstream veRL strategy

Use upstream as an external pinned dependency:

```text
upstream: https://github.com/verl-project/verl.git
candidate ref: release/v0.8.0
resolved ref: exact commit frozen by Checkpoint 0
install: editable checkout in the training environment
```

Add to this repository:

```text
integrations/verl/
  REQUIRED_VERL.txt
  foundry_agent_loop.py
  foundry_sft_data.py
  configs/
  tests/
```

Do not vendor veRL source and do not create a fork by default. The integration
must fail closed when the installed upstream commit or required Agent Loop API
differs from the pin.

A minimal upstream patch is allowed only after a test proves that the pinned
extension API cannot carry one of:

```text
exact generated token IDs
response mask
terminal S3 reward
abstain group failure
shared S3 Host call/checker path
```

Any patch is stored as a small reviewable patch series with an upstream base SHA
and a deletion condition. General cleanup or redesign of veRL is outside S4.

## 4. One concrete S3 refactor for online rollout

Current S3 `run_task_episode` owns a complete synchronous `PolicyDriver` loop.
veRL's `AgentLoopBase.run` is asynchronous and must own model generation/token
truth. Nesting another complete policy loop would duplicate control and lose
exact token ownership.

S4 therefore permits one narrowly consumed refactor: extract the environment
side of the current S3 loop into an incremental, trusted session.

```python
session = open_interactive_episode(
    prepared_release,
    task_pack_path,
    expected_task_pack_id,
    policy_spec,
    rollout_index,
    instance_root,
)

public_input = session.public_input
step = session.apply_decision(driver_decision)
record = session.finalize(policy_completion_or_defect)
```

Required properties:

- the session exposes only `public_input`, public call application and terminal
  finalization to S4;
- it does not expose native facts, bindings, checker callbacks or reset authority;
- `apply_decision` reuses the existing Host parsing/schema/dispatch/observation
  implementation;
- `finalize` reuses the existing close/reopen/checker/reward implementation;
- current Responses `capture_public_episode` and `run_task_episode` become thin
  consumers of the same session rather than remaining a second implementation;
- EpisodeRecord/TaskPack/Reward formats and identities do not change merely to
  satisfy veRL.

Do not add HTTP, a service, a registry, an environment pool or a generic Gym API.
The incremental session exists because one current S4 consumer needs to drive
model turns asynchronously.

## 5. `FoundryAgentLoop`

Implement exactly one upstream extension:

```python
class FoundryAgentLoop(AgentLoopBase):
    async def run(self, sampling_params, **dataset_fields) -> AgentLoopOutput:
        ...
```

### 5.1 Input fields

Each dataset row identifies exact authority rather than embedding truth:

```text
release artifact/root + release_id
task-pack artifact/root + task_pack_id
task_id / task_structure_id
corpus_id
rollout/group key
```

The Task instruction, Start and ToolSpecs are cold-read through S3 at runtime.
No answer key, protected binding or checker data enters the row.

### 5.2 Rollout loop

```text
open fresh S3 interactive session
obtain PublicEpisodeInput
tokenize the initial public prompt once
call veRL LLMServerClient.generate(prompt_ids, request_id)
retain returned model token IDs exactly, mask = 1
decode a copy only to parse a tool call or final answer
for a tool call:
  convert to existing DriverDecision
  S3 validates/dispatches/records it
  encode the public observation block, mask = 0
  append tokens and continue on the sticky request
for final answer/policy failure:
  S3 finalizes close/reopen/checker/reward
persist EpisodeRecord/TrainingEpisodeView
return AgentLoopOutput with terminal reward_score
```

The parser may inspect decoded text, but it must never replace generated token
IDs by re-rendering the assistant message.

## 6. Token truth and masks

For each rollout, maintain:

```text
prompt_ids       immutable initial public prompt
response_ids     concatenated model chunks and environment observation chunks
response_mask    1 for model-generated tokens, 0 for environment tokens
```

Invariant:

```text
len(response_ids) == len(response_mask)
```

The following are mask `1`:

```text
assistant tool-call syntax and arguments
assistant final answer
assistant policy terminal text
```

The following are mask `0`:

```text
tool observations
Host-added tool-result wrappers
non-model continuation delimiters required by the frozen chat template
```

System, user, reset context and ToolSpecs belong to the initial prompt and are
not response-loss targets.

The initial implementation supports exactly one target model/tokenizer/tool-call
format selected at Checkpoint 0. Do not create a codec registry.

## 7. Policy failure, defect and trainability

### Policy-owned terminal

Examples:

```text
malformed tool call
unknown public tool
invalid arguments
turn budget exhausted
missing/invalid final answer
correct state but wrong answer
```

If S3 truth remains trustworthy, finalize the Episode and transport reward
`0.0`. The model-generated prefix remains trainable.

### Trusted-path defect

Examples:

```text
provider/TLS outage
actor or observation contract failure
Task/checker identity drift
trusted inspect/evaluator failure
incomplete close/reopen evidence
```

Persist the S3 abstained Episode when sealable, then fail the veRL optimizer
group. No gradient is computed from it.

### No generated policy token

A valid zero-reward Episode with no model-generated token cannot contribute a
policy gradient. Retain it in reports but exclude the affected group from
optimization; do not invent a dummy token or reward target.

## 8. GRPO grouping

Use one exact TaskPack as one group prompt identity. veRL repeats it `G` times;
each `FoundryAgentLoop` opens a fresh native instance.

Recommended initial group metadata:

```text
uid/group_id = digest(task_pack_id, training_split_id)
rollout_index = 1..G
```

Dynamic native identifiers do not define the group. Each rollout must rediscover
them through public observations.

Before every optimizer step, assert:

```text
all group members have numeric S3 reward
all EpisodeRecords cold-read
all task_pack_id/group keys match
at least one model-generated token per rollout
no protected field entered tokenized input
```

Report reward variance and zero-advantage groups. Do not filter all-equal groups
silently; their lack of learning signal is part of the data-readiness result.

## 9. Offline SFT data

`TrainingEpisodeView` is the only S3 input. The converter:

1. cold-reads and verifies the paired Episode bundle;
2. requires `verified_success` and reward `1.0`;
3. reconstructs the selected model's public tool-use conversation;
4. tokenizes with the same frozen tokenizer/template used in evaluation;
5. emits input IDs, attention mask and assistant-only loss mask;
6. writes a manifest binding every sample to its Episode ID.

There is no S2 witness dataset path in the initial product. If teacher/admission
witnesses are later studied, that is an explicit baseline, not hidden in the
proposed SFT data.

## 10. Learning authority and artifacts

### `LearningSplitManifest`

Binds exact release/task-structure/task-pack assignments to train/dev/test and
records the post-freeze final held-out selection rule.

### `SFTDatasetManifest`

Binds source Episode IDs, tokenizer/template ID, conversion config, sample token
counts and checksums.

### `TrainingRunManifest`

Binds:

```text
base/checkpoint model identity
veRL exact commit
Foundry integration commit
learning split/dataset/corpus
complete config and seed
optimizer-step range
output checkpoint identities
```

### `CheckpointManifest`

Binds checkpoint bytes/config/tokenizer and parent checkpoint. A path is not an
identity.

### `EvaluationRunManifest`

Binds checkpoint, exact S3 TaskPacks, evaluation budget and resulting Episode
Batch IDs.

### `LearningUtilityReport`

Compares base, SFT and SFT->GRPO under matched frozen evaluation and reports
confidence intervals, error categories and cost.

Do not create a database, artifact service or global model registry. Canonical
files and exact digests are sufficient.

## 11. SFT and RL execution order

```text
Data readiness
-> verified-success SFT dataset
-> SFT checkpoint
-> S3 evaluation
-> veRL AgentLoop compatibility
-> one terminal-reward rollout group
-> one real GRPO optimizer update
-> checkpoint save/reload
-> bounded training run
-> fresh release-held-out evaluation
```

RL-only is an experiment after the main path, not a prerequisite.

## 12. Failure ownership

```text
UpstreamDataInsufficient   not enough structures/success Episodes/reward variance
SFTConversionDefect        token/template/mask/projection mismatch
VerlCompatibilityDefect    pinned extension API cannot preserve required semantics
PolicyRolloutFailure       valid S3 reward zero
RolloutAbstain             S3 trusted-path defect; no optimizer update
OptimizerFailure           veRL/training engine failure after valid rollout
CheckpointDefect           save/load/identity mismatch
EvaluationDefect           S3 evaluation authority unavailable or inconsistent
NoLearningGain             valid experiment shows no held-out improvement
```

Fix the first causal owner. Do not weaken Task truth or hide failed/abstained
rollouts to make training green.

## 13. Minimal file layout

```text
src/agent_env_foundry/
  learning_data.py
  learning_splits.py
  learning_artifacts.py

integrations/verl/
  REQUIRED_VERL.txt
  foundry_agent_loop.py
  foundry_sft_data.py
  configs/
  tests/
```

The exact files may collapse further during implementation. Do not split by
algorithm, model family or environment until one current consumer requires it.

## 14. Anti-overdesign rule

Before adding a component, state the concrete current failure it resolves.
Forbidden without new evidence:

```text
trainer/algorithm/model registries
HTTP/RPC Episode service
Ray environment actor layer outside veRL's own runtime
reward plugin framework
step-reward infrastructure
automatic curriculum/task evolution
generic chat-template abstraction
multi-framework support
multiple RL algorithms
```

The first complete result must use one model family, one veRL pin, one SFT path,
one GRPO path and the existing S3 terminal verifier.
