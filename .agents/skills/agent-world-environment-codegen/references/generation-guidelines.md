# Environment Candidate Generation Guidelines

## Portability boundary

`candidate/` is the complete publishable source closure. Judge restores only that tree into a
fresh read-only workspace, installs locked dependencies offline, and exposes only the files needed
by the component being executed. Generation inputs are absent.

- Runtime sees Runtime-role source.
- Task Materializer sees Runtime plus Task Materializer source.
- Public Verifier sees Runtime, Task Materializer, and Public Verifier source.
- Public tests are launched separately; they do not become Runtime dependencies.

Declare package data with the role of every component that must read it. In particular, data
loaded during Runtime import/startup is Runtime source closure, not generic `configuration`.
Never rely on public tests seeing the full tree to mask a narrower Runtime or Verifier view.

Use `AGENT_WORLD_STATE_DIR` for writable episode state. Never depend on the generation workspace,
home directory, network, sibling input artifacts, caches, or an existing virtual environment.

## Runtime ABI v2

Use stdin/stdout JSONL. Implement only the operations frozen in the implementation contract:

- `handshake`: return the exact WorldSpec tool IDs, namespaces, names, input schemas, output
  schemas, and observation schemas. Each tool entry contains exactly those six fields and optional
  `description`; never expose `schema_version`, `transport`, semantics, or other ToolSurface fields.
- `reset`: deterministically initialize from seed, actor, and public initial config; bind actor and
  return its visible observation plus state digest.
- `invoke`: execute the selected WorldSpec transition; enforce permissions; return result,
  actor-visible observation, empty untyped channels, digest, and diagnostic lifecycle fields.
- `snapshot`: return full program state plus digest for Judge use.
- `close`: release episode resources.

Support both full WorldSpec tool IDs and only those aliases explicitly permitted by the frozen
contract. Emit protocol-shaped failures without mutating state when a tool or permission check
fails.

## Task Materializer v3

The materializer proposes public task parameters; it does not evaluate success. Validate each
task type, actor, and difficulty against the frozen curriculum. Return the closed v3 object and no
extra fields. The framework independently compiles public instructions, evaluator goals, sampling
campaigns, and reachability checks.

## Public validation

Public tests and self-checks are candidate diagnostics, not release authority. Make them
standalone, deterministic, offline, and read-only-source compatible. Test at minimum:

- import and handshake;
- same-seed reset reproducibility and different-seed variation;
- every declared tool through the full ABI ID;
- Task Materializer echo/schema behavior;
- one realistic state-changing workflow and one denied/invalid action.

For every task type/allowed actor, also trace one real materialized initial
state through each required tool before completion. Compare the state schema,
the materialized values, and the frozen tool precondition first. If they have
no common valid state, report the frozen paths as a blocked input conflict;
do not make Candidate code invent an undeclared lifecycle merely to satisfy a
local test.

Do not weaken a frozen schema or change a test merely to silence a failure. Repair implementation
and tests together only when the test encoded an obsolete candidate-local assumption.
