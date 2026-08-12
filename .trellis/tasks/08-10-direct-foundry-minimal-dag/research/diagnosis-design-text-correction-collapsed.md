# Diagnosis — Design text correction collapses the actionable reason

- Date: 2026-08-12
- Real run: `run_f3a75200f65f4c93b84aa749eadac11e`
- Boundary: `design/shared_tool_semantics[1-2-3-4-5-6-7]`
- Safe terminal: `$.ordering`, expected `string`, two Luna calls, no output,
  `release=not_published`

## Expected behavior

Direct LLM proposes bounded semantic text; framework validates exact source
contracts and, for the one authorized local correction, tells the same model
the rejected path and one condition it can act on. Framework owns validation,
attempt count, Work/Artifact and release. SharedTool remains Direct with no
Skill, tool or workspace.

## Observed chronology

1. The immutable-parent suffix used the exact prior Evidence/Architecture.
2. Both primary Luna calls returned parseable JSON.
3. Both failed `$.ordering` with the same correction text:
   `value must be bounded nonempty text`.
4. The compiler emitted no SharedTool output and Observe records one blocking
   Direct Work/Finding. ToolSemantics, Agent, candidate, Judge and Registry did
   not run.

## Attribution

The common `_text` validator maps three different failures to one condition:
non-string type, empty/whitespace text, or text longer than the caller's exact
limit (160 here). Safe Observe therefore cannot distinguish a source-shape
problem from an ordinary length correction, and the second Luna call does not
receive the disclosed numeric bound as actionable feedback.

The latest evidence does not justify another SharedTool schema change, a bound
increase, model switch, Agent conversion, retry increase or relaxed validator.
The current blocker is feedback/observability at the existing compiler
boundary.

## Smallest causal action

Keep `_text` acceptance byte-for-byte equivalent, but emit one safe exact
condition: value must be a string; value must be nonempty after stripping; or
value must use at most the caller's declared number of code points. Persist no
Provider text or actual length. This improves every existing Design correction
recipient without adding a feedback subsystem or changing graph identity,
contracts, routes, retries or downstream ABIs.

## Proof

Deterministically prove all three rejected classes and unchanged accepted
normalization. After independent review, rerun the same immutable-parent suffix
once. A pass may continue only to first ToolSemantics; a failure begins a new
diagnosis using the newly exact safe condition. Nothing here proves complete
Design, Candidate, Judge, Registry, E2E, Repair, Expand or Consumer/SFT/RL.

