# Canonical Agent Environment Foundry

## Product intent

Build a paper-grade, publishable system that turns an arbitrary natural-language
business need into a real executable environment that another team can use
directly for agent tool-calling and, later, SFT/RL data collection and training.

Completion means semantic product completion. A demo, MVP, mock, template,
hard-coded dictionary world, green unit test, graph traversal, or package-shaped
file is not completion.

## Product lifecycle

Environment generation:

```text
natural-language need
-> research real workflows, interfaces, constraints, and available libraries
-> state the required business capabilities and invariants
-> Codex SDK writes a real uv-managed project in a workspace
-> execute real tools and real persistent state transitions
-> independently validate behavior and failure semantics
-> publish an immutable EnvironmentPackage
```

Environment use is a separate downstream lifecycle:

```text
released EnvironmentPackage
-> synthesize and admit Graph-based and Programmatic Tasks
-> prove solvability with real execution and derive task truth
-> run an independent tool-calling Agent episode
-> verify state, observations, and final answer as the task requires
-> produce grounded reward and trajectory
-> SFT / RL
```

Environment generation must not depend on a training framework. Training must
not gain authority to redefine environment state or release correctness.

## Non-negotiable constraints

1. Real execution: tools run real project code and mutate real database/file
   state. No dict/map response simulation, fixed environment, canned task, or
   repository candidate template as a normal success path.
2. Semantic evidence: tests must discriminate correct and incorrect state
   transitions, not merely prove that code starts or returns schema-shaped data.
3. Diagnose before patching: distinguish code, prompt, context, model, task,
   data, dependency, permission, and infrastructure failures. Do not add a
   fallback, compatibility layer, normalization rule, or hard-coded exception
   without causal evidence and an explicit product need.
4. Minimal infrastructure: give Codex SDK a real workspace and reuse mature
   libraries. Do not build custom sandboxes, protocols, schedulers, or DSLs
   unless a demonstrated product boundary requires them.
5. Product alignment: every implementation and review must explain how its
   evidence advances need -> executable environment -> independent verification
   -> publication -> downstream consumption. Code-green/product-red is failure.

## Current design questions

No answer below is frozen yet.

1. Which business-use information must exist before environment generation,
   and which training Tasks should be synthesized only after release?
2. What is the smallest public environment interface a Consumer needs, and how
   can a trusted verifier inspect state without exposing private truth to the
   acting Agent?
3. How should oracle execution, verifier code, final answers, deterministic
   state checks, and a bounded LLM Judge divide responsibility for different
   task types?
4. Exactly what must Research collect so Codex can implement an unfamiliar
   business environment correctly rather than invent a toy API?
5. What is the smallest end-to-end execution topology that preserves repair and
   publication without recreating the previous node/contract sprawl?

## Discussion standard

Use a concrete stateful environment such as booking to walk every proposal from
input through real tool calls, persistent state, verification, packaging, and a
downstream episode. Reject abstractions that cannot be expressed as executable
pseudocode with named owners, inputs, outputs, failure behavior, and observable
evidence.
