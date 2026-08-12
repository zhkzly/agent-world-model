# Foundry Consumer SFT and RL proof — design

## Boundary

```text
Registry exact refs -> SuiteSnapshot -> Consumer
                                      -> current PackageUseAdmission
                                      -> materialize task privately
                                      -> isolated Runtime Episode
                                      -> public trajectory
                                           +-> SFT exporter
                                           +-> online RL adapter
```

Consumer is a framework-owned local component over the existing Runtime
protocol. It is not a new Foundry authority or network microservice. SFT and RL
are replaceable callers of the same public Episode API.

## Closed v1 contracts

```text
SuiteSnapshot:
  suite_id
  exact_package_refs: nonempty tuple[EnvironmentPackageRef]
  task_selection
  seed_policy, created_at, snapshot_digest

EpisodeRequest:
  suite_ref, package_ref, task_type, seed
  actor, difficulty: DifficultySelection

MaterializedEpisodeInput:  # framework-private
  episode_request_ref, materializer_result_ref
  public_task, initial_config, evaluator_goal

PublicTask:
  episode_id, package_ref, task_commitment
  public_instruction, actor, tool_schemas[]

EpisodeAction:
  episode_id, step_index, tool_id, arguments, idempotency_key

EpisodeStep:
  episode_id, step_index, observation
  public_result?, public_error?, reward
  terminated, truncated

EpisodeResult:
  episode_id, package_ref, task_commitment
  public_trajectory_ref, total_reward
  termination_reason, step_count

SFTExample:
  package_ref, task_commitment, messages_or_turns[]
  tool_calls_and_public_results[], terminal_summary
```

The online RL adapter maps public task-selection arguments to
`reset(EpisodeRequest)`, then receives `PublicTask + initial observation`; it
maps `step(EpisodeAction)` to `EpisodeStep`. It cannot supply `initial_config`
and adds no second state, reward or termination implementation.

`snapshot_digest` binds the ordered full released refs, including package and
manifest digests plus Registry receipts. Consumer re-resolves and revalidates
each receipt and physical package before an Episode and after restart. It also
reads current Registry status and appends the episode-purpose
`PackageUseAdmission`; changed identity, quarantine, supersession or non-release
blocks startup rather than mutating Suite.

Before Materializer starts, Consumer loads the exact task family's
`DifficultySchema` from the cold-read package and verifies its digest against
TaskRequirement/protocol/manifest. `DifficultySelection` is the same closed
ordered mapping used by Direct Integration and Judge: every declared dimension
appears exactly once in schema order and every value is one declared level.
Missing, extra, duplicate, reordered and unknown values fail admission. The
Consumer neither defaults a level nor defines a parallel schema.

## Public/private enforcement

Framework calls the exact package Materializer with the selected seed/task/
actor/difficulty. Its `public_goal + initial_config` result is validated, then
bound into `MaterializedEpisodeInput`; only Consumer scoped private state sees
the reset config and evaluator binding. Runtime receives seed, actor and
`initial_config`, while the training caller receives PublicTask and initial
observation. A closed allowlist serializer creates every public record. Tests
reject a caller `initial_config`, seed private canaries into reset config, full
state, evaluator goal, sealed cases and source paths, and assert absence from
public APIs, SFT rows, RL inputs, logs and Observe.

Runtime remains an untrusted process. Consumer verifies package, manifest and
receipt digests,
launches package-relative, enforces lifecycle/time/resource limits, recomputes
or verifies framework rules, and closes the process on every terminal/error.

## Optional feedback

An optional aggregate `CapabilityFeedback` may contain suite digest, capability
dimension, bounded aggregate outcome and sample count. It contains no
trajectory, evaluator goal or release mutation. Expand may read it only as a
priority projection; removing it leaves Campaign behavior valid.

## Observe

Observe shows Suite/package commitments, current admission verdict/reason and
Registry revision, Episode lifecycle, step count, public reward/termination and
failures. It never stores private state or acts as an Episode controller.

## Anti-overdesign

Use the existing Runtime process boundary and a small Python Consumer API. Add
one exporter and one adapter. Do not add a training server, queue, dataset
platform, trainer abstraction hierarchy or framework-specific optimizer code.
Difficulty validation reuses the package contract/compiler helper; it is not a
new registry, schema service or policy layer.
