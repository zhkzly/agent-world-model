---
name: agent-world-real-execution-proof
description: "Select and run the smallest real execution proof for an Agent World change or claim. Use after a causal hypothesis exists and before claiming a node, repair, Integration, or E2E works; choose a true boundary, observe live calls, and chain only after the affected point passes."
---

# Agent World Real Execution Proof

Use this Skill after agent-world-debugging has produced a causal hypothesis,
or before claiming a changed Agent World boundary works. Convenience pytest
success is not proof of a live Agent, repair, Integration, or E2E path.

## State the falsifiable claim

Before selecting a command, record:

> Before this change, … happened at … for … . After the change, … must be
> observably different. This establishes … and does not establish … .

Name the boundary, frozen-input provenance, and effective model/profile when
relevant. Preserve the smallest credible closure; do not hand-edit a proposal
into state merely to reach a later node.

For a cleanroom Direct, Observe, or product claim, first prove that the chosen
public route and launched process do not load or call forbidden legacy control
authority. A hybrid trace is a cutover failure, not a true proof boundary; stop
there and do not attribute it to a model, Prompt, Skill, or Candidate.

## Select the actual boundary

Read [references/proof-selection.md](references/proof-selection.md) for the
changed surface. It distinguishes deterministic boundaries, Direct LLM,
tool-enabled Codex Agent, repair, project Agent view, Integration, and E2E.
A Direct probe never proves a Codex Agent path.

For a repair that changed code, Prompt, Runtime Skill, profile, configuration,
contract, or retry policy, run only the proof named by the current
cross-layer-critic `allow` record. A new terminal scene ends that proof and
returns to agent-world-debugging; it is not permission for an unplanned second
repair attempt.

## Observe real calls without inventing a short death clock

At dispatch, record coordinate, attempt, profile/model, and first progress.
At about five minutes without a terminal or meaningful progress, perform the
read-only liveness procedure in
[references/live-observation-and-chaining.md](references/live-observation-and-chaining.md).
Do not hard-kill normal Generate solely for elapsed time; do not treat a PID as
progress; do not let no-progress execution silently sit for hours.

## Chain honestly

Run one true boundary at a time. At the first new failure, stop, read the new
scene, and return to agent-world-debugging; do not carry the prior repair
hypothesis downstream. After a direct point passes, run immediate Integration,
then broaden only when every affected point passes.

Use pytest, lint, typing, and narrow constructed checks as regression guards in
addition to—not instead of—the selected true proof. Report exact behavior and
safe evidence path, plus what repair, downstream Integration, and E2E remain
unproven.
