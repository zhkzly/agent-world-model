# Initial contract (frozen)
Goal: execute 20 real Needs through S1 and the existing S2 sampler, then publish evidence-backed statistics.
Invariant: `run_task_foundry_batch` and `run_task_foundry_product` remain the sole Direct sampling path.
Invariant: every counted Environment/Task comes from real Codex/Responses execution and physical verification.
Invariant: all frozen Needs and typed failures remain in the official denominator.
Not doing: no replacement sampler, new Goal semantics, S3/S4 work, mock evidence or yield-driven gate weakening.
Gold references: `origin/main@6246740` Direct S2 path and the three retained real S1/S2 product reports listed in `research/current-evidence-baseline.md`.

## Append-only decisions

- 2026-09-01: Remote inspection confirmed S2 sampling is complete; this task only invokes it. Alternative: reimplement sampling. Reversal evidence: a demonstrated defect in the existing Direct production API that prevents a frozen Release from being sampled.
- 2026-09-01: Main stopped and deleted a 946-line hand-built coordinator test produced by the first worker. It was replaced by focused orchestration tests plus real Git/SQLite-derived actor execution; no ideal receipt/evidence fixture remains.
- 2026-09-01: Real maintenance preflight closed Need -> Research -> actor Builder -> public-surface freeze -> mutually blind authors -> Core -> Qualification -> Release `18792c793e4576400d6df30505d158b33c06bea26677a5e854a5dd18a79ecdd5` -> S2 Product `9ba41a4b1d404fef027bf4cde22832e70712126fa5dc0b89f0922d00ae443c81` -> Corpus `698dcdbd35d504a45665e91ce519ae9e695950c287a471b31dbf7aedc3444b04`.
- 2026-09-01: Physical failures exposed general author-context gaps for noop axis separation, refusal native-effect versus public-process separation, and unscoped enumeration process evidence. General contract examples were added; no maintenance/domain branch entered Framework.
- 2026-09-01: Repeated CPA 408/500 stream failures licensed OpenAI SDK transport `max_retries=2`; PolicySpec, prompts, tools and semantic retry behavior remain unchanged.
