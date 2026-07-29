---
name: engineer-environment-codegen
description: Implement or repair one executable Agent World Candidate from frozen Builder inputs in the isolated workspace. Use only for runtime CandidateBuild work.
---

# Engineer Environment Codegen

## Isolated workspace operating rules

You are already at the isolated workspace root. Use only relative paths:
`inputs/...` for frozen framework inputs and `candidate/...` for the project
you create. Do not reconstruct absolute host, Codex, profile, or parent paths,
and do not search outside the workspace for a toolchain. Use the framework
commands `./.agent-world-tools/uv` for every uv operation and
`./.agent-world-tools/python3.12` for focused JSON inspection. Bare `uv`, bare
`python`, and a generation-workspace `.venv` are not provisioned interfaces.
For uv commands that select or create a Python runtime, pass
`--python ./.agent-world-tools/python3.12` explicitly; do not rely on PATH or
`UV_PYTHON`.

Read all frozen inputs through the fields needed for the next implementation
step; do not dump whole JSON documents into tool output and then re-query them
because the output was truncated. After the initial concise pass, create the
`candidate/` project skeleton before deeper schema lookups and validate in
small increments. If a shell command fails, run `pwd`, correct the relative
command once, and continue from the frozen inputs. Do not spend the turn
probing host directories or substituting an undeclared build tool.

Read the frozen Builder inputs before editing:

- `inputs/world-spec.json`
- `inputs/curriculum.json`
- `inputs/implementation-contract.json`
- `inputs/task-materializer-output.schema.json`
- `inputs/implementation-plan.md`, when present, as non-authoritative guidance

The JSON inputs are authoritative. The optional plan may improve execution
order but cannot change semantics. Create the complete project only under
`candidate/`; never read Builder inputs at candidate runtime.

1. Implement every WorldSpec state transition, permission, observable field,
   error, idempotency and rollback behavior in real program code. Do not use
   fixed task replay, environment-id branches, fixture registries, mocks,
   stubs, generated release checks, or a generic blacklist of framework-only
   names. Implement only fields and behavior declared by the frozen schemas.
2. Implement the exact `agent-world.runtime.v2` JSONL handshake, reset, invoke,
   snapshot and close ABI in the frozen implementation contract. Runtime state
   belongs in `AGENT_WORLD_STATE_DIR`; candidate source is read-only under
   Judge isolation.
   The handshake result `operations` is exactly the JSON string array
   `["handshake","reset","invoke","snapshot","close"]` in that order;
   never emit operation objects or metadata there. Assert that exact shape in a
   standalone public Runtime test. For every reset, invoke, and snapshot result,
   `state_digest` must be exactly `sha256:` followed by 64 lowercase hexadecimal
   characters; a bare hash digest is invalid. Assert that exact wire format in a
   standalone public Runtime test.
3. Implement the exact deterministic Task Materializer v3 entrypoint and
   output schema. It must handle unseen valid seeds, actors, task types and
   difficulty inputs using only its declared output fields. Framework-only
   metadata never crosses reset, but an identifier defined by WorldSpec (for
   example a tool `task_id` argument) is ordinary domain semantics and must be
   implemented exactly.
4. Deliver a real Python 3.12 virtual uv project: `pyproject.toml`, resolved
   `uv.lock`, non-empty declared `LICENSE`, runtime, materializer, public
   self-check and standalone public tests. Keep the root virtual and
   non-installed (`[tool.uv] package = false`), with only lock-pinned registry
   wheels installable offline. In `uv.lock`, the one `{ virtual = "." }` root
   package must be named exactly `[project].name`; every other package is a
   registry dependency. Copy `inputs/implementation-contract.json`
   `python_requires` verbatim into `[project].requires-python`; `uv.lock`
   must use that same range or uv's canonical `==3.12.*` range, never a broad
   `>=3.12` shorthand. Remove caches, virtual environments, links and
   undeclared files before final output.
5. Run the actual local build and public tests when capability permits. Their
   result is diagnostic evidence, never release authority. If a real blocker
   prevents completion, report it honestly; do not weaken a frozen contract.
   Judge invokes each declared public test as an isolated standalone script
   with the candidate project root and optional `src/` layout importable. Use
   ordinary imports from declared candidate modules; do not edit `sys.path`,
   rely on `PYTHONPATH`, or depend on a writable source tree.

## Component source visibility

Candidate file roles describe physical source visibility under isolated
execution, not merely documentation categories. A `runtime` source may import
only files declared `runtime`; a `task_materializer` source may import
`runtime` or `task_materializer`; a `public_verifier` source may import any of
those three executable roles. Configuration, documentation, lock, test, and
license files are not reusable executable dependencies. When a helper is
needed by Runtime and another component, declare it `runtime` (or make each
component self-contained); do not label a shared Python module `configuration`
just because it mostly contains constants. Before returning, compare every
declared Python import with the final file roles and make each component
independently importable from its allowed source view.

Before returning, inspect the final regular-file inventory and make the
completion declaration describe that exact tree's paths and roles. The
framework derives hashes and executable modes from physical regular files; do
not declare or infer executable metadata in `CandidateCompletion`. `entry_path` is always a
candidate-relative POSIX source-file path ending in `.py`; it is not an import
module. For example, a physical file
`candidate/candidate/runtime.py` has `entry_path="candidate/runtime.py"`,
while its launch argv is `['.venv/bin/python', '-m', 'candidate.runtime']`.
Likewise a materializer at `candidate/materializer.py` uses
`entrypoint="candidate.materializer:materialize"` and that `.py` entry path.
Conversely, a materializer file directly at `candidate/task_materializer.py`
uses `entry_path="task_materializer.py"` and
`entrypoint="task_materializer:materialize"`; do not add a `candidate.` module
prefix unless there is an actual `candidate/` package directory inside the
project root.
List every final regular file once in `files`, using the fixed roles for runtime,
materializer, public verifier, public tests, `pyproject.toml`, `uv.lock`, and
`LICENSE`. Do not put workspace prefixes, filesystem paths, or filenames before
the materializer colon.

Return only the requested `CandidateCompletion` JSON. Declarations are paths
relative to `candidate/`, not the outer workspace. Do not create Candidate,
Judge, envpkg, SBOM, supply-chain, validation, or release artifacts; framework
code derives those after it independently inspects the physical project.
