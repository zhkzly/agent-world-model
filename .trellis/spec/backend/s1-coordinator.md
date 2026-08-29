# S1 v2 Coordinator Contract

## 1. Scope / Trigger

Use this contract for the future direct Python coordinator from one natural
language Need to one admitted EnvironmentRelease v2. The coordinator does not
currently exist at HEAD and must not be claimed implemented until its real
cross-domain acceptance passes.

## 2. Signature

```python
generate_environment_v2(
    need_text: str,
    *,
    config: GenerationConfig,
) -> Released | NotReleased | Unsupported
```

The imperative order is:

```text
Research
-> actor Builder
-> expected-semantics freeze
-> mutually blind TaskSemantics and Verifier Authors
-> Core derivation
-> physical Qualification
-> Publication
-> cold verification/replay
```

A CLI may wrap this API after the API exists. CLI existence never proves the
coordinator or release is complete.

## 3. Contracts

- Preserve `NeedRecord.original_need` exactly and derive wrapping-invariant
  coverage anchors.
- Generated projects are standalone uv workspaces created with absolute paths
  and `uv init --no-workspace`; parent project bytes remain unchanged.
- Freeze expected semantics before exposing actor source/native details.
- TaskSemantics and verifier workspaces/threads are fresh and mutually blind.
- Derive one acyclic Core ID; Qualification binds Core, not final Release ID.
- Publish only from a passed strict receipt and immutable frozen bytes.
- Cold verification uses archived actor/semantics/verifier/evidence bytes.
- Any stage failure returns a typed non-release outcome; there is no v1 fallback.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Empty Need | `NotReleased(invalid_need)` |
| Research cannot close | typed Research failure; no Builder |
| Actor build fails | `EnvironmentDefect` or Infrastructure; no semantic authors |
| Expected semantics incomplete | fail before source exposure |
| Semantics/verifier author failure | typed owner; no Core Qualification |
| Core byte changes | invalidate all descendant evidence |
| Qualification not passed | no Publication |
| Receipt/layout/cold replay fails | no released ID |
| v1 input/output requested | unsupported; no conversion |

## 5. Good / Base / Bad Cases

- Good: SQLite and filesystem/Git Needs use the same coordinator and Framework
  code with separate generated projects.
- Base: exact Core qualifies, seals, relocates and cold replays to one Release ID.
- Bad: restore deleted `api.py/cli.py/qualification.py/publication.py` wholesale.
- Bad: let one generated semantic package authorize its own receipt.
- Bad: expose an unqualified/pending release to S2.

## 6. Tests Required

- Need wrapping equivalence and parent workspace immutability.
- Three author input-visibility matrices and immutable input checks.
- Per-stage fail-closed absence of later calls/artifacts.
- Core/receipt/Release identity DAG mutations.
- Real public/native Qualification and cold replay for SQLite and filesystem/Git.
- S2 opens only exact admitted bytes without development-checkout imports.

## 7. Wrong vs Correct

Wrong:

```text
Builder -> self-authored tests -> package -> release
```

Correct:

```text
Builder + mutually blind semantic/verifier artifacts
-> Host physical agreement/negatives
-> strict receipt
-> immutable v2 release
```
