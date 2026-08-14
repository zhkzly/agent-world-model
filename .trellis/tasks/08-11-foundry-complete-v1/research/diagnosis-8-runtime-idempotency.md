# Diagnosis Record 8: candidate_idempotency_failed (runtime lacks keyed idempotency)

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55, resume after the guard gate.
Terminal: rejected / candidate_idempotency_failed.

## Progress

Materialization validation, precondition guards, and the reference-composition
check ALL passed for the regenerated design: the run reached the
double-invoke idempotency assertion inside _run_recipe.

## Root cause

The framework invokes each action twice with the same idempotency_key and
requires identical responses (no repeated side effects). The framework-
rendered design-driven runtime evaluates when-conditions against live state
and has NO keyed response cache: after the first invoke mutates state, the
second invoke fires different rules and returns a different result. Earlier
blind-transition runtimes masked this (unconditional sets are idempotent).

## Fix direction (framework-owned)

- _DESIGN_RUNTIME_BODY: cache responses by idempotency_key; a repeated key
  returns the cached response without re-applying effects; reset clears the
  cache.
- engineer-environment-codegen skill: state the idempotency contract for
  materializer/runtime authors.
- Deterministic test: rendered runtime returns identical results for the
  same key across two invokes (with state-changing transitions).
