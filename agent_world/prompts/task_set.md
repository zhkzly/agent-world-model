You generate TaskSet fields from NeedSpec, EnvironmentSpec, LogicalToolGraph, and KnowledgePack.
Return only JSON fields required for TaskSet. Each task must include verifier_refs, dependency_path, allowed_logical_tool_ids, and framework_replay with explicit tool calls.
Do not include artifact metadata.

Nested contract:

- tasks[] items must include task_id, natural_request, target_capability, initial_state_refs, expected_state_delta, expected_answer, allowed_logical_tool_ids, forbidden_leakage, dependency_path, difficulty, and verifier_refs.
- Include expected_answer even when expected_state_delta is the main check; use an empty string only when the answer is not applicable.
- dependency_path must be a list of logical tool id strings in execution order, not edge objects.
- Each adjacent pair in dependency_path must be either the same tool id or a declared directed edge in LogicalToolGraph.edges. If two tools are both independently available from an earlier tool, create separate tasks or route through declared edges; do not invent implicit edges.
- natural_request must not mention database, backend, verifier, logical_tool, tool_id, or actual tool ids.
- coverage must include tool_ids, capabilities, and state_entities.
