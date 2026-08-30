# EnvironmentRelease v2 Preparation Contract

> **Status: strict product admission and cold preparation implemented for the
> SQLite and filesystem/Git C3+D verticals.** Public `verify_release_v2` and `prepare_release` reject
> mechanical fixtures, bind the strict receipt/evidence/Core, reproduce sealed
> ToolSpecs/CapabilitySpecs/StartCases and expose actor/semantics only.

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
- Admit only a strict passed `environment-qualification/2` receipt whose Core
  and positive capability evidence bindings recompute from archived bytes.
- Copy actor and semantics projects into different content-addressed runtime roots
  and run real `uv sync --frozen --all-groups --link-mode copy` in each.
- Use the same internal per-project materializer for pre-publication
  Qualification and sealed preparation. Qualification additionally materializes
  its Native Auditor; `prepare_release` never exposes or installs that auditor
  for Consumers.
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
- ZIP staging restores explicit directory entries and their Unix modes before
  admission. It must not rely on file-parent creation because sealed native
  trees can contain meaningful empty directories.
- Structured semantics documents use exact-key decoders and existing constructors;
  no expression language, recipe or executable verifier crosses the wire.

## S2 witness/assessment attempt lifecycle

Every S2 positive witness or model-relative assessment attempt uses one native
instance and two distinct prepared sessions:

```text
acting open -> reset once -> public episode -> trusted pre-close inspect -> close
-> reopen same instance without reset -> trusted inspect/checker -> close
```

The Host emits `ReloadEvidence/1` with a pre-generated attempt/native-instance
identity, ordered lifecycle events, distinct session identities, pre-close and
post-reopen fact digests, and post-reopen checker-result digest. It contains no
absolute temporary path and cannot reference its enclosing witness ID.

Action-bearing Atom wrong-target/wrong-answer and ForEach partial/wrong-target/
wrong-answer challenges use this same lifecycle. Noop remains a separate
initial-state check because it intentionally executes no public episode.

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
| ZIP drops an empty sealed directory or changes its mode | strict evidence tree mismatch before preparation |
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
- Directory-entry/mode round trip, including empty native Git directories whose
  presence is bound by Qualification evidence.
- Shared materializer: real actor/semantics/verifier locked sync, canonical
  author-input filtering, accepted verifier digest equality, multi-module import
  denial and role-specific error attribution.
- Checkpoint D: invalid/missing/non-passed receipt rejection before sync.
- Real frozen sync and real child interpreters for actor plus all six trusted calls.
- Same-name cross-release non-aliasing and reopen-without-reset persistence.
- S2 witness/assessment evidence rejects same-session reuse, another native
  instance, a second reset, missing close, reordered lifecycle and checker
  evaluation before reopen.
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
