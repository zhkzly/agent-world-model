# Task Materializer v3 integration contract

## Purpose and authority boundary

The Foundry turns a natural-language need into a real programmatic environment,
independently verifies and repairs it, and publishes an `EnvironmentPackage`
for rollout, evaluation, or reinforcement learning. Task Materializer v3 serves
that purpose by preventing generated candidate code from defining its own
instruction, evaluator goal, answer, solution witness, expected output, or
release evidence.

There is no task-v2 compatibility path and no transitional adapter. The frozen
`CurriculumRequirements` is the single task semantic input to Builder, Judge,
packaging, and consumption.

## Design contract

Every `TaskRequirement` directly owns:

- a recursively closed `initial_config_schema` for Runtime reset data;
- a recursively closed `public_goal_schema` visible to the training Agent;
- a recursively closed `evaluator_goal_schema` visible only to trusted framework
  evaluation;
- total `EvaluatorGoalBinding` identity projections from required public leaves
  to every required evaluator leaf.

Bindings have only `binding_id`, `public_pointer`, `evaluator_pointer`, and the
fixed `projection="identity"`. They are strict RFC 6901 pointers, may read only
required public leaves, cover every required evaluator leaf exactly once, and
cannot overlap. Every `task_goal` pointer read by success, failure, or terminal
Rules must be one of those projected required evaluator leaves. There is no
expression or default language.

## Candidate callable

The package descriptor is `TaskMaterializerDescriptor`:

```text
protocol = python-callable-v3
entrypoint = package.module:materialize
callable = materialize(seed, task_type, actor, difficulty)
task schema = task-materialization-v3
renderer = objective-public-goal-v1
projector = identity-bindings-v1
```

The candidate returns exactly:

```text
schema_version
task_schema_version
seed
task_type
actor
difficulty
public_goal
initial_config
```

The call identity must be echoed exactly. Extra fields fail the closed schema.
In particular, candidate output cannot contain `public_instruction`,
`evaluator_goal`, `private_goal`, `evaluation_witness`, an answer, or expected
output.

`TaskMaterializerV3Compiler(curriculum)` compiles the one output schema shared
by Builder and Judge. It validates framework-selected task type, actor, exact
difficulty keys/levels, call echo, public goal, and initial config. Framework
code then renders the public instruction from the frozen objective plus
canonical public-goal JSON and identity-projects the evaluator goal.

## Runtime and evaluator split

- The Agent receives actor, difficulty, framework-rendered instruction, public
  goal, reset observation, and tools.
- Runtime receives only seed, actor, and initial config.
- Trusted evaluation receives the framework-projected evaluator goal and closed
  WorldSpec Rule IR.
- Independent reachability drives a real episode; the candidate supplies no
  witness or answer.

Any materialization, projection, or reachability failure is a Task/Builder or
Judge finding. It must trigger targeted rework or rejection and cannot fall
back to replay data, templates, a permissive schema, or task-v2.

## Builder and package contract

Builder emits `task_materializer`, never `task_generator`, in
`EnvironmentCandidate`, `CandidateManifest`, and `EnvironmentPackageManifest`.
The candidate file role is `task_materializer`. Candidate consumer-adapter code
and manifest fields do not exist; framework consumption uses the released
Runtime/Task Materializer contracts directly.

The materializer output schema/protocol is packaged at
`tasks/materializer_protocol.json`, the single canonical task semantic artifact
at `tasks/curriculum.json`, WorldSpec at `world/world_spec.json`, and the closed
Rule IR/evaluator descriptor at `world/rule_ir.json`. A second copied
`task_requirements.json` is deliberately not emitted: task requirements already
live inside the typed curriculum and two copies could drift. The published
package is `envpkg-v3`; no envpkg-v2 compatibility path remains.

The candidate project is a virtual, non-installed uv root executed from a
read-only source tree. Dependencies install offline from hash-pinned registry
wheels in a framework-provided read-only cache; source builds, build backends,
path/Git/direct-URL/editable sources, custom indexes, and install-time network
are prohibited. Builder, Judge, and Registry continue to bind the exact
candidate file closure through `candidate_source_tree_digest`.

## Consumer-visible versioning

`EnvironmentSuiteSnapshot` uses `environment-suite-snapshot-v3`, and its
`consumer_protocol` is `agent-world.local-consumer.v3`.
`PublicTask.task_schema_version` is `public-task-v3`; the local service uses
`agent-world.local-env-rpc.v3`. No v2 package or consumer protocol is accepted.
