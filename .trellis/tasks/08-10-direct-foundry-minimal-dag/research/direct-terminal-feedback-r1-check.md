# Direct terminal-feedback R1 check

Date: 2026-08-11
Scope: deterministic review only; no provider, Agent, candidate, runtime, or Observe call was made.

## Decision

Decision: allow

- Recomputed raw-byte SHA-256 of `research/direct-terminal-feedback-plan.md`:
  `894b5addfba25e5f4dade7d72c9bf70ad00b9dee2236880e7645fc88eb343025`.
  It matches the current terminal-feedback R1 allow in
  `cross-layer-review-894b5add-terminal-feedback-r1.md` and is recorded in
  `check.jsonl`.
- The predecessor block `cross-layer-review-3c6d3d85-terminal-feedback.md`
  required distinct packet identity and explicit-evidence precedence. The
  focused regression supplies packet A on attempt one, distinct packet B on
  terminal attempt two, and parameterizes explicit evidence as `None`, `{}`,
  and a nonempty safe object.

## Review

- `GraphRunner.execute` uses the exact terminal selection
  `exc.evidence if exc.evidence is not None else exc.correction`. Therefore an
  explicit `{}` wins; absent explicit evidence stores the terminal packet B,
  not the prior correction packet A.
- Local correction eligibility remains ordinal-one only. The focused test
  proves calls exactly `[None, packet_a]`, two attempt records
  (`correction_requested`, `failed`), and no third operation invocation.
- The terminal failure is persisted in the failed WorkRecord's
  `assurance_refs`; its Finding is route-free and contains the same failure
  Artifact in `evidence_refs`. The test cold-reads both closures and the
  failure payload.
- The existing `CorrectionPacket` remains bounded to code, JSON path, short
  condition, and expected category. Artifact safety still rejects forbidden
  prompt/raw-response/sealed/evaluator/secret fields and secret-like values.
- Observe remains the existing read-only projection: it exposes work and
  Finding safe fields/evidence IDs, not the failure payload. The future Repair
  contract continues to re-derive any route from `Finding.subject_ref` and
  immutable provenance, not evidence content.
- The R1-scoped implementation is limited to the terminal evidence choice and
  its focused test. It introduces no Prompt, model, route, retry/budget,
  graph-node/edge topology, Artifact schema, public Observe, Candidate, Repair,
  Expand, Consumer, or later-child change.

## Verification

- `uv run pytest`: pass (`100 passed`).
- `uv run ruff format --check .`: pass.
- `uv run ruff check .`: pass.
- `uv run mypy agent_world`: pass (`13 source files`).
- `uv run python -m compileall -q agent_world`: pass.
- `uv run pytest tests/test_legacy_firewall.py`: pass (`2 passed`).
- `git diff --check` and `git diff --check 9562c058b61562c11f76d8127f56b68b0f5be2d9`: pass.

## Non-claims

This deterministic allow proves only safe terminal feedback attribution for
the existing graph transaction. It does not prove a live Luna or Spark result,
Direct/Agent invocation, Candidate/Runtime/Integration/Judge behavior, Registry
publication, public Observe of a live run, Repair, Expand, Consumer, or an
end-to-end `EnvironmentPackage`.
