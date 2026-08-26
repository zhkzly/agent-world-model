# Canonical Agent Environment Foundry

## Product intent

Build a paper-grade, publishable system that turns an arbitrary natural-language
business Need into a real executable environment that another team can use
directly for agent tool-calling and, later, SFT/RL data collection and training.

Completion means semantic product completion. A demo, mock, template,
hard-coded dictionary world, green unit test, graph traversal or package-shaped
file is not completion.

## Product lifecycle

Environment generation:

```text
natural-language Need
-> research real workflows, interfaces, constraints and available libraries
-> state the required business capabilities and invariants
-> Codex SDK writes a real uv-managed project in a workspace
-> execute real tools and real persistent state transitions
-> independently validate behavior and failure semantics
-> publish an immutable EnvironmentRelease
```

Environment use is a separate downstream lifecycle:

```text
released EnvironmentRelease
-> synthesize and admit Graph-based and Programmatic Tasks
-> prove solvability with real execution and derive task truth
-> run an independent tool-calling Agent episode
-> verify state, observations and final answer as the Task requires
-> produce grounded Reward and trajectory
-> SFT / RL
```

Environment generation must not depend on a training framework. Training must
not gain authority to redefine environment state or release correctness.

## Frozen stage and context boundaries

- S1 consumes a Need and produces a qualified `EnvironmentRelease`: a real
  generated uv project, meaningful initial state, public documentation,
  `reset/tools/invoke/close`, tool schemas, uniform structured observations and
  an immutable release identity.
- S2 consumes only that released environment surface and produces a
  release-bound sealed `TaskPack`: Task, start, constructive solvability evidence,
  task truth and verifier/reward material.
- S3 consumes `EnvironmentRelease + TaskPack`, executes the acting Agent and
  emits a verified Episode and attributable Reward.
- S4 consumes verified Episodes for SFT/RL and cannot redefine earlier truth.

MCP, HTTP, OpenAI messages and call identifiers are adapters, not environment
semantics. Graph-based and Programmatic generation are S2 algorithms and cannot
require graph-, witness-, Task- or reward-specific fields from S1.

Remaining choices inside S2-S4—Task sampling policy, verifier construction,
reward mapping, trajectory representation and training configuration—must
respect these frozen boundaries.

## Non-negotiable constraints

1. Real execution: tools run real project code and mutate real database/file
   state. No dict/map response simulation, fixed environment, canned Task or
   repository candidate template as a normal success path.
2. Semantic evidence: tests discriminate correct and incorrect state
   transitions, not merely prove that code starts or returns schema-shaped data.
3. Diagnose before patching: distinguish code, prompt, context, model, Task,
   data, dependency, permission and infrastructure failures. Do not add a
   fallback, compatibility layer, normalization rule or hard-coded exception
   without causal evidence and an explicit product need.
4. Minimal infrastructure: give Codex SDK a real workspace and reuse mature
   libraries. Do not build custom sandboxes, protocols, schedulers or DSLs
   unless a demonstrated product boundary requires them.
5. Product alignment: every implementation and review explains how its evidence
   advances Need -> executable environment -> independent verification ->
   publication -> downstream consumption. Code-green/product-red is failure.

## Discussion standard

Use a concrete stateful environment such as booking to walk every proposal from
input through real tool calls, persistent state, verification, packaging and a
downstream episode. Also test a contrasting environment such as filesystem/Git.
Reject abstractions that cannot be expressed as executable pseudocode with named
owners, inputs, outputs, failure behavior and observable evidence.
