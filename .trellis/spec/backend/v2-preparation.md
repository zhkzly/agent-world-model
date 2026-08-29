# EnvironmentRelease v2 Preparation Contract

> **Status: Shared three-role materializer implemented; strict admission
> planned.** The current code verifies v2 closure and materializes actor,
> semantics and audit-only verifier projects through one canonical physical
> path. `prepare_release` still exposes actor/semantics only and does not yet
> validate a passed Qualification receipt. Mechanical fixtures remain test
> infrastructure, not product releases. Checkpoint D must close this gate before
> any S2 entry point exists.

## 1. Scope / Trigger

Use this contract when consuming an `environment-release/2` directory or ZIP for
S2/S3. Preparation turns verified bytes into two isolated uv runtimes; it does not
qualify semantics, publish a release, generate Tasks or define a public service.

## 2. Signatures

```python
prepare_release(
    release_path: Path,
    cache_root: Path,
    *,
    settings: PreparationSettings | None = None,
) -> PreparedRelease

materialize_project(
    project_input: ProjectMaterializationInput,
    runtime_root: Path,
    *,
    settings: PreparationSettings,
) -> RuntimeLock

with prepared.open(instance_directory) as session:
    session.actor.reset(...)
    session.actor.tools()
    session.actor.invoke(...)
    session.trusted.inspect(instance_directory)
```

`open` never resets or deletes the caller-owned instance.

## 3. Contracts

- Accept only canonical v2 bytes; v1 has no compatibility reader.
- Actor, semantics, verifier, release verification and materialization use one
  canonical project identity over exact relative path, normalized mode and
  content digest.
- Materialization copies only identity-bound project files. Author inputs,
  actor/candidate views, old `.venv`, caches and `dist` never enter the runtime.
- Checkpoint D target: admit only a strict passed
  `environment-qualification/2` receipt whose Core and evidence bindings
  recompute from archived bytes. Until implemented, preparation is structural
  test infrastructure and cannot authorize S2.
- Copy actor and semantics projects into different content-addressed runtime roots
  and run real `uv sync --frozen --all-groups --link-mode copy` in each.
- Checkpoint C target: use the same internal per-project materializer for
  pre-publication Qualification and sealed preparation. Qualification additionally
  materializes its audit-only verifier; `prepare_release` never exposes or
  installs that verifier for Consumers.
- Children run their own `.venv/bin/python -I -B`; scrub `VIRTUAL_ENV`,
  `PYTHONPATH` and `PYTHONHOME`. Generated packages are never imported by Host.
- The private request is exactly `{seq, op, args}`. Responses echo `seq` and are
  exactly success `{seq, ok, value}` or failure `{seq, ok, error}`.
- Duplicate stdout before loading generated code: keep one fd for the wire and
  redirect fd 1 to stderr. Generated `print()` must never corrupt the wire.
- At every open, verify project bytes and the installed editable module origin.
  Actor must not import semantics; semantics must not import actor.
- Manifest the instance before and after every trusted call, append a
  `TrustedCallEvent`, and reject mutation even when the child also raises.
- Structured semantics documents use exact-key decoders and existing constructors;
  no expression language, recipe or executable verifier crosses the wire.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| unsupported/malformed/tampered release | `EnvironmentDefect` or contract rejection before sync |
| missing/non-passed/mismatched Qualification receipt | Checkpoint D target: rejection before sync |
| source/copy/runtime project digest mismatch | role-owned defect before use |
| copy-time identity TOCTOU | role-owned defect; temporary/runtime staging removed |
| frozen uv sync unavailable/fails | `InfrastructureFailure` with command outputs |
| actor startup/factory failure | `EnvironmentDefect/child_startup_failed` |
| semantics startup/factory failure | `SemanticsDefect/child_startup_failed` |
| response timeout/EOF after healthy use | `InfrastructureFailure` |
| response seq or shape mismatch | fail closed; no value reaches caller |
| prepared source or `.pth` origin changes | reject before child launch |
| actor imports semantics | `EnvironmentDefect/runtime_import_leak` |
| semantics imports actor | `SemanticsDefect/runtime_import_leak` |
| trusted call changes instance tree | record event then `SemanticsDefect` |

## 5. Good / Base / Bad Cases

- Good: two releases use identical package names but different bytes; both remain
  live simultaneously and return their own behavior.
- Base: open, explicit reset/invoke, six trusted calls, close, reopen; state persists
  and reset count does not change during open.
- Bad: use Host Python, mutate `sys.path`, install actor into semantics, hardcode an
  `import_proofs=True` flag, or treat a mechanical fixture as release qualification.
- Bad: read child stdout directly after loading generated code without fd isolation.

## 6. Tests Required

- Current: directory and safe-ZIP identity equality plus unsupported format,
  byte/mode/symlink/extra-member rejection.
- Shared materializer: real actor/semantics/verifier locked sync, canonical
  author-input filtering, accepted verifier digest equality, multi-module import
  denial and role-specific error attribution.
- Checkpoint D: invalid/missing/non-passed receipt rejection before sync.
- Real frozen sync and real child interpreters for actor plus all six trusted calls.
- Same-name cross-release non-aliasing and reopen-without-reset persistence.
- Trusted mutation and mutate-then-error both produce an unchanged=false event and rejection.
- Both import-leak directions, ambient Host import, source and `.pth` tamper.
- Generated stdout noise, startup attribution, sequence mismatch and real timeout.
- Mutation licenses for manifest, runtime digest/origin, leak, wire seq/keys,
  frozen sync, stdout isolation, `-I`, startup attribution and no implicit reset.

## 7. Wrong vs Correct

Wrong:

```python
sys.path.insert(0, generated_src)
environment = importlib.import_module(factory_module)  # Host import cache aliases releases
```

Correct:

```python
subprocess.Popen([runtime_python, "-I", "-B", runner, factory], ...)
# Host validates JSON, schemas, origins and before/after tree manifests.
```
