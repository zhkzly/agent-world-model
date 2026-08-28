# S1 Direct Coordinator Contract

## 1. Scope / Trigger

Use this contract for the public `Need -> EnvironmentRelease` coordinator and
for any generated uv workspace created beneath the Foundry checkout. It prevents
formatting-only Need changes from changing semantic coverage and prevents `uv`
from attaching a generated Candidate to the Foundry's own workspace.

## 2. Signatures

```python
generate_environment(need_text: str, *, config: GenerationConfig) -> (
    Released | NotReleased | Unsupported
)
```

```bash
foundry generate --need-file NEED.md [--run-store PATH] [--release-store PATH]
foundry verify-release --release RELEASE_DIRECTORY_OR_ZIP
```

The coordinator is imperative: Research, Builder, Qualification, cold
verification, then publication. There is no workflow engine or compatibility
path.

## 3. Contracts

- Preserve `NeedRecord.original_need` byte-for-byte as decoded text.
- Derive coverage anchors from Markdown paragraphs/list items and complete
  sentence boundaries. Ordinary prose line wrapping must not change anchors.
- Resolve run and release stores to absolute paths at invocation construction.
- Builder workspace setup uses an absolute target and `uv init --no-workspace`.
  The parent Foundry `pyproject.toml` and `uv.lock` must remain byte-identical.
- Publish only after the exact archive passes cold locked installation and the
  admitted Qualification replay.
- Any Research, Builder, Qualification, cold-use or publication failure returns
  `NotReleased`; it cannot publish a release ID.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Empty Need | `NotReleased(invalid_need)` |
| Research cannot close before budget | typed Research `NotReleased`; Builder absent |
| Builder command/workspace failure | phase-attributed `NotReleased`; Qualification absent |
| Qualification not passed | no assembly/publication |
| Malformed release ZIP | `not_verified`, `extraction/zip_invalid`, no traceback |
| Cold replay fails or changes probe bytes | no publication |
| Published archive differs from cold-tested archive | `NotReleased(published_archive_digest_mismatch)` |

## 5. Good / Base / Bad Cases

- Good: wrapped and unwrapped forms of the same prose preserve different
  `original_need` text but produce identical complete anchors.
- Good: a Candidate under `.artifacts/foundry-runs/...` is a standalone uv
  project and never appears in the parent workspace members.
- Base: an accepted Research handoff produces one Candidate, one independent
  Qualification lineage, one cold replay and one content-addressed release.
- Bad: each visual line becomes a clause (`invoice` / `dispute environment...`).
- Bad: `uv init` discovers the Foundry parent and edits its `pyproject.toml`.
- Bad: a structural ZIP check is called release success without cold execution.

## 6. Tests Required

- Wrapped/unwrapped Need equivalence while preserving exact original text.
- Relative Builder target resolves once and parent `pyproject.toml` bytes do not
  change; mutations removing either `.resolve()` or `--no-workspace` must fail.
- Every pre-publication stage failure prevents the publication function call.
- Malformed ZIP returns a typed CLI failure.
- A live public command must produce `research-ready.json`, `candidate.json`,
  passing positive/negative Qualification evidence, cold evidence and a release
  whose directory and ZIP verify to the same ID.

## 7. Wrong vs Correct

Wrong:

```python
for line in need.splitlines():
    clauses.append(line)
subprocess.run(["uv", "init", str(relative_workspace)], cwd=relative_parent)
```

Correct:

```python
anchors = paragraph_list_and_sentence_anchors(need)  # wrapping invariant
workspace = requested_workspace.resolve()
subprocess.run(["uv", "init", "--no-workspace", str(workspace)], cwd=workspace.parent)
```
