# Verifier Planning

Plan deterministic verifiers for generated tasks.

Rules:

- Every task must have a matching verifier.
- Verifiers must define inputs, checks, success criteria, failure criteria, positive examples, negative examples, assertions, timeout, isolation requirement, and diagnostics.
- Every assertion must include `assertion_id`, `target`, `operator`, `expected`, `tolerance`, and `source_ref`.
- Every verifier must include dependency-path trace validation through `surface_trace_path`, `expected_dependency_path`, and `trace_call_group`.
- Verifiers should validate traces and state/answer evidence.
- Do not rely on hidden implementation details or LLM judgment as release authority.
- Include negative replay rejection criteria.

Accepted output target: `VerifierPlan` fields only.
