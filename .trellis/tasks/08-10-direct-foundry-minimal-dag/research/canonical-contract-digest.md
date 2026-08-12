# Canonical contract digest for the explicit work-graph task

This is a task-local reading digest, not a replacement for
`docs/agent-world-environment-generation.zh.md`. It records only the clauses
needed to review this cleanroom refactor after the planner read the full source
document.

## Product target

The system turns a natural-language `EnvironmentRequest` into an
evidence-grounded executable environment, independently verifies it in an
isolated boundary, publishes an immutable Registry `EnvironmentPackage`, and
exposes safe facts through Observe. Graph progress or passing tests alone are
not product completion.

The product ultimately grows a diverse library of such packages. Direct is the
required seed path; Evolve is an optional, independently-budgeted path that
uses released semantic anchors plus real technical-document/tool-ecosystem
evidence to create new candidates. One environment is an outcome, not the
product's fixed universe.

## Authority and execution taxonomy

The five framework owners are Controller, Designer, Builder, Judge and
Registry. The reusable Agent roles are Researcher, Environment Engineer and
Challenger. Framework owns artifacts, gates, routing, budget and release;
candidate code is untrusted and out-of-process. A model/Agent never owns a
Judge verdict, release decision, hash/manifest fact or work transition.

- Direct semantic design is a prompt-only Direct LLM; no Skill, tools or
  workspace.
- Researcher, advisory Engineer, Challenger and CandidateBuild are explicit
  Codex Agent works with one mounted runtime Skill and explicit workspace.
- Search/fetch/extract, compilation, integration, Judge, packaging, Registry
  and Observe are framework operations; candidate processes are not Agents.

## Direct / Evolve / Observe

Direct is mandatory and must not wait for Evolve. Evolve is not a Direct node,
not a source-code patch, and not merely a query-retrieval fallback. It is an
outer Campaign that freezes released parents and source evidence, lets Policy
select a bounded semantic mutation, and requires Designer to reconstruct full
WorldSpec, tasks, verifier and implementation contract. The genotype is
`ToolSurface`, `ToolSemantics`, `TransitionConstraint`, `TaskScope`, or a
composite. Every child reuses the same Design -> Build -> Judge -> Registry
trust path and earns a new independent outcome.

Technical docs must first become real Search/Fetch/Extract provenance and
evidence-backed clues. A released parent contributes stable semantic/package
facts and lineage, never inherited release validity. With multiple parents,
Policy and Designer still receive only safe semantic/contract projections.
After one complete child Design is committed, Builder alone may expose the
exact verified parents' candidate source closures read-only to CandidateBuild,
which writes one fresh self-contained child workspace. Policy can prioritize,
but cannot merge code, write a candidate or publish it. Observe is read-only
and never selects/retries/release-publishes work.

Evolve begins with a framework-owned CampaignRequest and immutable
CampaignSnapshot, not an Agent. The first Agent-assisted work is Source
synthesis: a mounted Researcher receives a bounded parent projection and
framework-acquired technical-document evidence, then proposes clues. Policy,
admission, Operator, Judge and Registry are framework work. Designer remains a
Direct LLM work; the candidate core retains its explicit Agent Build/advisory
works. `MutationIntent` is a bounded proposed change; the framework computes
the authoritative SemanticDelta after compiling the full new Design.

## Current task boundary

`docs/direct-rewrite-execution-map.zh.md` limits the current cleanroom slice to
Direct + minimal Observe + package lineage seam. It excludes a current
Campaign/Policy/Pool/expand CLI **and a generic Graph engine**. Accordingly,
this task uses an explicit work map and two fixed compositions rather than
`GraphDefinition`/`GraphExecutor`: Direct preparation ends at compiled Design;
the candidate core starts there and is reused by future Evolve. The baseline
already writes `origin=direct` and `parent_package_refs=[]`; the present task
preserves that seam and can add only a focused regression/independent
manifest-shape check if audit shows the re-read is too implicit. The immediately
following child task implements one real documentation-grounded Campaign E2E
rather than a dormant Expand scaffold.

The current Direct candidate contract is nevertheless canonical and
parameterized: a separate untrusted Task Materializer implements
`materialize(seed, task_type, actor, difficulty)`; Runtime implements the exact
`handshake/reset/invoke/snapshot/close` lifecycle with actor-bound reset and
idempotency keys; framework owns evaluator goal projection, reward and
termination. A four-operation Runtime without Task Materializer is not a
training-compatible environment foundation.

Training is a separate downstream child. It may depend on a framework Consumer
and exact Registry packages, while Foundry cannot depend on SFT/RL adapters,
models, optimizers or trainer configuration. Optional aggregate training
feedback may prioritize Expand but is neither evidence nor a release gate.

## Non-negotiable guards

No old control/scheduler/graph/campaign runtime imports, mock/template/replay
success path, secret/sealed leakage, candidate in-process import, Agent
self-verdict, or second release path. An Integration failure blocks release.
The current task makes no Expand E2E, resume/repair, parallel scheduler,
Consumer or training claim.
