# Candidate Completion Contract

Inspect the final regular-file inventory and make `CandidateCompletion` match
it exactly. Framework code derives hashes and executable modes from physical
files; do not invent them in the declaration.

## Strict response envelope

The final Provider response uses a strict object schema. Keep every top-level
`CandidateCompletion` field present, including fields that are inactive for a
blocked result. For a blocked result, use this complete transport envelope:

```json
{
  "schema_version": "v2",
  "status": "blocked",
  "blocking_reason": "one safe current blocker",
  "project_root": null,
  "runtime": null,
  "task_materializer": null,
  "public_self_check": null,
  "public_test_paths": [],
  "files": []
}
```

Those `null` and empty values are transport placeholders, not Candidate
declarations. For a completed result, populate every declaration from the
final physical tree as described below.

## Entrypoints

`entry_path` is a Candidate-relative POSIX `.py` file path. Completion `argv`
is framework launch metadata, not a development command:

- `runtime.argv` and `public_self_check.argv` start with
  `.venv/bin/python -m <module>` or `.venv/bin/python3 -m <module>`.
- Do not declare bare `python`, `uv run`, or a script path.
- Derive the module from the physical path. For example,
  `candidate/runtime.py` maps to `candidate.runtime`, while root
  `runtime.py` maps to `runtime`.
- A Task Materializer entrypoint is `<module>:<callable>`. Do not add a
  `candidate.` prefix unless that package physically exists.

## File roles

List every final regular file exactly once with paths relative to the outer
`candidate/` project:

- `pyproject.toml` → `configuration`
- `uv.lock` → `dependency_lock`
- `LICENSE` → `license`
- `runtime.entry_path` → `runtime`
- `task_materializer.entry_path` → `task_materializer`
- `public_self_check.entry_path` → `public_verifier`
- every `public_test_paths` entry → `public_test`
- every additional Runtime/helper source module → `runtime`, unless it is the
  declared Task Materializer or public verifier entrypoint
- every non-code asset opened by Runtime, Task Materializer, or public
  self-check → a role visible to every component that opens it. A JSON/data
  file is a Runtime dependency when Runtime reads it; it is not
  `configuration` or `documentation` merely because it is not Python.

For a shared asset, choose the narrowest role that includes every reader:
`runtime` for Runtime plus any downstream public component,
`task_materializer` for Materializer plus public verifier, and
`public_verifier` only for the self-check. Do not solve a visibility failure by
asking a later runner to mount a broader tree.

The equality is exact in both directions: every file declared with role
`public_test` must also appear in `public_test_paths`. Do not add package
markers or helper files under `tests/` merely to make test discovery work;
run each standalone public test directly instead.

`files` is the complete physical inventory, not only the three entrypoints.
Do not omit imported helper modules such as state, storage, domain, protocol,
or tool implementation modules.

The outer project directory is already named `candidate/`. A physical
`<workspace>/candidate/candidate/task_materializer.py` is declared as
`candidate/task_materializer.py`, never
`candidate/candidate/task_materializer.py`.

Before returning:

1. Compare every declaration with the final physical tree.
2. Derive and check both launch modules.
3. Confirm no undeclared regular file, link, cache, or `.venv` remains.
4. Confirm the final public checks and tree preflight ran after the last edit.
5. Trace every Candidate-relative file opened through imports, package
   resources, or `Path(__file__)` to a role visible to its reader, then run the
   declared public self-check from this workspace.
6. Do not declare a workspace or dependency-execution mode. The framework owns
   the actual host workspace, clean-build command, and offline lock validation;
   they are not Candidate behavior for you to echo.

Return a full strict-envelope `CandidateCompletion`, not a patch or narrative.
