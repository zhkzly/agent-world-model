---
name: agent-world-real-execution-proof
description: "Plan and perform the right real execution proof before and after an Agent World project change. Use for code, runtime instruction/input, Runtime Skill, project-execution Agent view, feedback, profile, adapter, scheduler, verifier, CLI, replay/resume, or repair path; use before claiming a node, repair loop, integration, or E2E flow works. Select the narrowest test that can prove the claim, then chain only after affected single boundaries pass."
---

# Agent World Real Execution Proof

Testing is the experiment that can falsify the explanation behind a change.
Use agent-world-debugging to establish that explanation; use this Skill to
choose, run, and report the proof. Do not use convenience pytest success as a
substitute for a real changed boundary.

For deterministic code, feedback, validator, scheduler, projection, verifier,
CLI, replay, resume, or isolation claims, establish a single failing
true-boundary execution before editing. Reuse its credible input closure after
the change. If the only evidence is a durable production-like event that cannot
safely be reproduced, record why it is sufficient and state the exact
post-change observation that would falsify the proposed repair.

## Start with a falsifiable claim

Before choosing a command, state:

> Before this change, … happened at … . After this change, I expect … to be
> observably different. This proof establishes … and does not establish … .

Name the exact boundary, frozen-input provenance, effective model/profile when
relevant, and whether the claim is about deterministic mechanics, the
project-execution Agent view, runtime model behavior, correction behavior,
integration, or E2E.

## Match the proof to the changed surface

- **Code, feedback, validator, parser, scheduler, scene, or projection:** make
  a realistic frozen input and execute the actual local boundary. This is a
  real leaf/boundary exercise, not merely an interface unit test.
- **CLI / execution safety:** execute the actual CLI through uv with a safe
  input and demonstrate the intended InvocationBackend/control path, rather
  than a generic shell runner or host fallback.
- **Verifier / gate weakness:** use a candidate that should pass or fail and
  prove the real verifier or Judge decision, not only a schema/mock assertion.
- **Replay / resume / state / legacy path:** exercise the actual recovery or
  state transition and show that a fixed replay, fixture registry, retired awm
  command, or ABI v1 route is not the normal success path.
- **Runtime / Judge isolation:** show the intended isolated boundary actually
  ran and did not silently use host-local behavior.
- **Project-execution Agent view:** verify the current summary and local paths
  with a fresh project-Agent navigation exercise. Give it only the top-level
  snapshot and the live question; it must name precise first reads and a
  defensible next investigation without broad search. Record the paths it
  chooses and whether they answer their advertised questions. This does not
  require a runtime model node unless a separate runtime surface changed.
- **Runtime instruction/input, Runtime Skill, model/profile/route/response
  mode:** run one isolated node through the real InvocationBackend with its
  configured logical envelope, without adding a diagnostic input, output-token,
  or short-timeout ceiling; then read its scene.
- **Correction or repair loop:** exercise the normal Scheduler path with real
  repair authority. A diagnostic one-attempt runner proves only first
  generation/validation.
- **Immediate integration and E2E:** run the smallest predecessor/successor
  chain after the affected leaf passes; run the larger chain only after every
  affected single boundary and immediate integration passes.

agent-world-agent-view-stewardship sets the acceptance criteria for a project
view. This Skill owns the test selection and execution; do not bury node tests
inside the view-design Skill.

## Run one boundary at a time

1. Preserve or construct the smallest credible input closure, including the
   pre-change failing observation when the claim is deterministic. Do not
   hand-edit a proposed result into state just to reach a later node.
2. Execute the true local boundary before and after the change when it can test
   the mechanism.
3. If runtime behavior changed, make one real isolated model call with the
   resolved profile, not a mock or a convenient alternate profile.
4. If repair behavior changed, run the normal repair path rather than a
   diagnostic-only runner.
5. Audit and fix all homologous active runtime-instruction/input, Runtime
   Skill, profile, compiler, and feedback surfaces supported by the same cause
   before broadening the run.
6. Move to immediate integration and then E2E only after the directly changed
   point passes.

If a result is too vague to explain the next action, stop. Return to
agent-world-debugging, improve feedback/observability, prove that improvement,
and only then retry or change semantics.

The boundary exercise's output is itself a debugging surface. On failure, it
must state its node/boundary, frozen-input provenance, one poisoned condition,
expected versus actual stable diagnostic and terminal state, elapsed time, and
last completed phase. Do not promote a bare assertion, opaque exception, or
stall into a semantic repair hypothesis.

## Use regression tests honestly

pytest, lint, typing, and narrow projection checks help prevent regression and
are worth running in proportion to risk. They do not prove a live Agent call,
a repair loop, an integration, or E2E behavior. State their role accurately.

## Report scope, not just pass/fail

For each proof, record:

- exact behavior and input/profile provenance;
- expected and actual observation;
- safe scene or evidence path supporting the conclusion;
- what remains unproven, especially repair, downstream integration, and E2E.

At the first new failure, do not continue the chain or add blind retries. Read
the new scene and begin a new debugging attribution.
