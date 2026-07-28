---
name: engineer-environment-codegen
description: Implement or repair one executable Agent World Candidate from frozen Builder inputs in the isolated workspace. Use only for runtime CandidateBuild work.
---

# Engineer Environment Codegen

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
   stubs, generated release checks, expected answers, evaluator goals, sealed
   cases, or verifier internals.
2. Implement the exact `agent-world.runtime.v2` JSONL handshake, reset, invoke,
   snapshot and close ABI in the frozen implementation contract. Runtime state
   belongs in `AGENT_WORLD_STATE_DIR`; candidate source is read-only under
   Judge isolation.
3. Implement the exact deterministic Task Materializer v3 entrypoint and
   output schema. It must handle unseen valid seeds, actors, task types and
   difficulty inputs without authoring evaluator-only material.
4. Deliver a real Python 3.12 virtual uv project: `pyproject.toml`, resolved
   `uv.lock`, non-empty declared `LICENSE`, runtime, materializer, public
   self-check and standalone public tests. Keep the root virtual and
   non-installed (`[tool.uv] package = false`), with only lock-pinned registry
   wheels installable offline. In `uv.lock`, the one `{ virtual = "." }` root
   package must be named exactly `[project].name`; every other package is a
   registry dependency. Remove caches, virtual environments, links and
   undeclared files before final output.
5. Run the actual local build and public tests when capability permits. Their
   result is diagnostic evidence, never release authority. If a real blocker
   prevents completion, report it honestly; do not weaken a frozen contract.

Before returning, inspect the final regular-file inventory and make the
completion declaration describe that exact tree. `entry_path` is always a
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
