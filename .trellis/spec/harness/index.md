# Agent Harness Contract

## Scenario: Alignment Patrol boundaries

### 1. Scope / Trigger

Use Patrol only when a discussion is persisted as a candidate task proposal or
when a supported active-task implementation/lifecycle action is attempted.
Chat-only discussion and read-only research are never gated. Compact/resume
emits a deterministic reminder and never invokes a model.

### 2. Signatures

```bash
python3 .trellis/scripts/run_alignment_patrol.py hook

python3 .trellis/scripts/run_alignment_patrol.py check \
  --trigger plan-document-write \
  --candidate-task .trellis/tasks/<planning-task> \
  --transition "<reviewed plan action>"

python3 .trellis/scripts/run_alignment_patrol.py check \
  --trigger transition \
  [--task .trellis/tasks/<expected-active-task>] \
  --transition "<exact supported action>"
```

### 3. Contracts

- Candidate mode requires a non-symlink task under `.trellis/tasks` with
  `task.json.status == "planning"` and `prd.md`.
- Candidate documents are `candidate_task`, never `authority`. Stable authority
  is `PROJECT.md` plus `DECISIONS.md`.
- Active mode resolves the canonical non-stale Trellis task. `--task` only
  asserts that resolved path.
- The request digest covers authority, proposal/active task, transition,
  staged/unstaged/repo-visible untracked content, and unavailable fingerprints.
- The reviewer returns exactly F1–F5 and `ALLOW|BLOCK|ASK`. Stored requests and
  verdicts are diagnostic, not reusable authorization.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Chat, explanation, read-only research | No Patrol |
| Compact/resume/fork | Neutral context; no model dispatch |
| Missing/invalid candidate | `ASK`, `CANDIDATE_TASK_INVALID`, exit 3 |
| Missing active task | `ASK`, `NO_ACTIVE_TASK`, exit 3 |
| `--task` differs from active task | `ASK`, `TASK_AUTHORITY_MISMATCH`, exit 3 |
| Trigger outside plan-document-write/worker-turn/transition | `ASK`, `UNSUPPORTED_TRIGGER`, exit 3 |
| Provider/timeout/malformed output | Non-ALLOW; supported action does not run |
| Reviewer `BLOCK` / `ASK` | Exit 2 / 3 |

### 5. Good / Base / Bad Cases

- Good: honest planning proposal, no execution claim → F1 normally `N/A`.
- Base: active implementation slice with evidence → judge only that transition.
- Bad: candidate task appears in authority → reject as self-authorization.
- Bad: mock/dict work claims real completion → `BLOCK`.
- Bad: compact hook dispatches Patrol or emits verdict language → reject.

### 6. Tests Required

- Candidate path, status, symlink, proposal/authority separation, and observed
  boundary assertions.
- Active-task assertion and request-digest invalidation tests.
- Closed public-trigger enum test.
- Neutral hook test proving no repo resolution or Patrol dispatch.
- Raw-byte/unavailable fingerprint, authority symlink, verdict schema, channel
  startup/error/undeliverable, and worker cleanup tests.
- Real benign candidate and adversarial false-completion Patrol smokes.

### 7. Wrong vs Correct

Wrong: run a full LLM Patrol after compact, or let a candidate PRD authorize
itself.

Correct: compact only restores the neutral boundary; candidate plans are
reviewed as proposals, then become implementation authority only after explicit
activation.
