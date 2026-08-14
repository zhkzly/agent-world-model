# Repair Plan: keyed idempotency in the design-driven runtime

Lineage: diagnosis-8-runtime-idempotency.md. Continues the direct-completion
lineage after fe33df95 / 0ff3ae1d / 58a29e92 / 3fd31254 allows (all spent).

## Scope classification

Local. Producer: _DESIGN_RUNTIME_BODY (candidate.py); consumer: the rendered
runtime exercised by _run_recipe's double-invoke assertion. No design,
artifact-envelope, package, or Registry change.

## Changes

1. agent_world/candidate.py _DESIGN_RUNTIME_BODY: add a per-episode response
   cache keyed by idempotency_key — a repeated key returns the cached
   response without re-applying effects; reset (_init) clears the cache;
   invokes without a key bypass the cache.
2. agent_world/runtime_skills/engineer-environment-codegen/SKILL.md: document
   the idempotency contract (same idempotency_key -> identical response, no
   repeated side effects) for future materializer/runtime authors.
3. tests: rendered-runtime test — two invokes with the same key return
   identical results even though the transition is state-changing; a new key
   proceeds normally; reset clears the cache.

## Compatibility

- Protocol shape unchanged; the runtime body is framework-owned.
- The skill digest change re-invalidates candidate_build on pure resume
  (harmless: the framework overwrites runtime.py anyway).

## Checks and proofs

- pytest full suite green including the idempotency test.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim judge/package/registry pass; further terminals are new
  observations.
