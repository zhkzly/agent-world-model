# Task Generation

Generate executable, verifiable tasks for an Agent World environment.

Rules:

- Every task must have allowed logical tools, dependency path, initial state refs, expected state delta or expected answer, verifier refs, and framework replay data.
- Every task must still include both `expected_state_delta` and `expected_answer` fields; one may be empty only when the other carries the check.
- Every task must include `target_capability`, `forbidden_leakage`, and `difficulty`.
- `dependency_path` is an ordered list of logical tool id strings, not a list of edge objects.
- Tasks must be solvable using the declared logical tool graph.
- Avoid leaking verifier ids, state file paths, internal implementation details, or logical tool ids in user-facing natural requests.
- Include coverage over tools, capabilities, and state entities.
- Include rejected candidates when useful.

Accepted output target: `TaskSet` fields only.
