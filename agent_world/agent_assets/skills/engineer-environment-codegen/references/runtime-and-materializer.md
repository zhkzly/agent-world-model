# Runtime and Task Materializer

## Runtime v2

Implement the exact `agent-world.runtime.v2` JSONL protocol from
`inputs/implementation-contract.json`: one request produces one response for
handshake, reset, invoke, snapshot, and close.

- Handshake `operations` is exactly the JSON string array
  `["handshake","reset","invoke","snapshot","close"]` in that order.
- Reset binds the episode actor. Invoke cannot accept or substitute another
  actor.
- Reset, invoke, and snapshot `state_digest` is exactly `sha256:` followed by
  64 lowercase hexadecimal characters.
- Runtime state lives in `AGENT_WORLD_STATE_DIR`; source remains read-only in
  Judge.
- Observation visibility, permissions, errors, idempotency, rollback, and
  state transitions come from the frozen WorldSpec. Runtime reward and
  termination fields are diagnostic only; framework rules decide outcomes.

### Reset and snapshot state projections

Read `only ActorBoundary.visibility fields` as an upper visibility boundary,
not permission to return `{}`. For `reset`, construct the observation from the
bound actor's visible root-state fields and make it satisfy that actor's
projection of `world-spec.state.root_state_schema`, including every required
field in the projected schema. A useful implementation shape is to select each
visible root field from the validated state; do not substitute an empty object
when the schema requires visible state.

`snapshot` is the framework's state-inspection boundary, not an Agent-facing
redaction. Its observation must satisfy the complete
`world-spec.state.root_state_schema`. It may therefore differ from the reset
observation when an actor cannot see every root field.

Before completion, use one valid state and every declared actor to exercise
both operations. Assert that reset returns exactly the permitted projection
with its required fields, and that snapshot returns a complete valid root
state. Keep this check separate from per-tool observation schemas: an empty
tool observation schema does not make reset or snapshot state observations
empty.

Exercise the full response boundary in the Agent's own workspace, not only a
successful ToolError path. For each declared operation, make one request and
check its complete wire shape against the frozen contract; include an unknown
operation and one ordinary runtime failure path when the Candidate defines one.
Do not assume a locally convenient error object has the required fields.

Before writing the handshake, extract every declared tool surface from
`inputs/world-spec.json`. Build each Runtime `tools[]` entry as the
implementation-contract projection: exactly `tool_id`, `namespace`, `name`,
`input_schema`, `output_schema`, `observation_schema`, plus `description` only
when present. `schema_version` and `transport` belong to the WorldSpec record,
not to an individual handshake tool; never copy the whole record. Preserve the
projected schemas losslessly: descriptions, `anyOf` branches, nullable forms,
required fields, and closed-object settings are part of the public Runtime
interface. During the Agent's own workspace check, launch the Candidate
handshake, assert each entry has that exact key set, then compare every
projected field against the frozen WorldSpec using canonical JSON. This is a
build-time self-check only; the released Candidate must not read `inputs/` at
Runtime.

Run the mounted `scripts/check_runtime_handshake_contract.py` after the final
Runtime edit. Supply the Candidate's physical import root and the same command
that will be declared as `runtime.argv`; it starts that command, sends the
actual handshake, and reports the first value-free frozen-schema coordinate if
the projection differs. Do not replace this with a hand-written subset
assertion or rephrase any frozen schema description.

Run standalone public Runtime tests that assert the wire envelope, exact
operations array, digest format, state transitions, permissions, failures,
idempotency, restart, and read-only source behavior.

## Task Materializer v3

Implement the exact callable and output shape declared by the implementation
contract and `inputs/task-materializer-output.schema.json`. Materialization
must be deterministic for the same `(seed, task_type, actor, difficulty)` and
must generalize to unseen valid inputs. Framework-only metadata never crosses
reset; a domain field declared by the WorldSpec remains ordinary semantics.

Before writing task generation, read the matching `oneOf` branch for every
task type and make a small local table of its required `public_goal` and
`initial_config` fields. A public goal is not automatically the same thing as
the argument object of the tool that may solve it. Invoke `materialize` for
each task type and validate the complete returned object against the frozen
schema before completion; a hand-written smoke assertion about a few keys is
not enough.

For every materialized task:

1. Make `initial_config` satisfy its JSON Schema.
2. Evaluate every frozen global or task-local initial-state Rule and sampling
   Rule whose sources exist at reset against the state produced by reset. The
   reset context contains actor, pre/post-state, observation, reset_config, and
   seed; it does not contain an action's `args`, `tool_result`, `error`, or
   `events`. In `inputs/world-spec.json`, global initial-state Rules are
   `world-spec.state.initial_state_constraints`; never fabricate empty action
   data to make such a Rule pass or fail. A global initial-state Rule applies
   to every task family; do not treat it as a suggestion.
3. Ensure the public goal and initial state make the required tools and
   success/terminal Rules reachable for the allowed actor.
4. Preserve required seed and difficulty diversity without violating any
   initial-state Rule.

Do not solve one side of a contradiction by silently breaking another. If a
global initial-state Rule requires an empty resource while a task requires an
unauthorized actor to operate on a pre-existing instance of that resource,
the frozen design is not implementable by changing materializer bytes alone.
Report a safe blocked result that names the conflicting frozen rule and task
family instead of weakening either.

Use small constructed seed samples during development, including every task
type, actor, difficulty level, repeated same-input calls, and unseen uint64
seeds. These are local self-checks; Integration still runs the authoritative
large campaign.

### Candidate-owned materializer campaign

Before writing the first Materializer slice, run the mounted
`scripts/candidate_contract_map.py --workspace .`. It compactly renders every
frozen task type, allowed actor, difficulty level, required project mode, and
the two diversity minima. It is a read-only input view, not a hidden Judge or
an outcome claim.

Turn its `task-materializer campaign` section into a real Candidate-owned
test or focused local command. For every listed task type and actor, use at
least the displayed base-seed count and assert all of the following from the
actual Materializer output:

- exact echo of seed, task type, actor, and difficulty;
- JSON-safe, same-input deterministic output;
- at least the displayed number of distinct canonical full materializations;
- at least the displayed number of distinct canonical `initial_config`
  values; and
- for each declared difficulty dimension, the lowest and highest level with
  the same seed change `public_goal` or `initial_config`.

Use the mounted `check_materializer_campaign.py` to run these repetitive,
input-derived checks after the entrypoint exists. Pass the actual physical
Candidate import root and the actual `module:materialize` entrypoint; do not
guess a Judge cwd or copy the script into Candidate. The script does not
validate full output schemas or Runtime reset, so keep the public schema and
Runtime checks in the Candidate's own test suite as well.

Use only frozen input facts as assertions—never future Judge paths, sealed
cases, hard-coded expected domain IDs, or a local fixture registry. Rerun this
campaign after the final Materializer or metadata edit. A passing campaign is
the Code Agent's own diagnostic; it does not claim Runtime reset correctness,
Integration, or release success.

## Component visibility

Candidate file roles are physical source visibility:

- A `runtime` source may import only files declared `runtime`.
- A `task_materializer` source may import `runtime` or
  `task_materializer`.
- A `public_verifier` source may import any executable role.
- Configuration, lock, license, documentation, and public-test files are not
  executable dependencies.

This applies to data assets as well as Python imports. If a component opens a
JSON, template, schema, or other Candidate-relative file through package
resources or `Path(__file__)`, declare that asset with a role visible to that
component. Put helpers or data shared with Runtime in the `runtime` role or
make components self-contained. Compare every import and file-open with final
file roles, then run the declared public self-check and module entrypoints from
the Agent workspace using only its relative Candidate import root.

Treat a package `__init__.py` as executable source: every re-export is an
import under that file's declared role. Do not use a `runtime` package entry as
an all-module convenience export; it may expose only runtime-visible modules.
Consumers that are allowed to use the materializer or public verifier should
import those concrete modules directly.
