# Diagnosis Record 11: materializer initial_config category mismatch

Date: 2026-08-14 (session)
Real event: offline bench against the latest frozen design. Integration
fails candidate_property_mismatch: tool search_rate_options result field
rate_options expected category list, got str. The agent-written
materializer's semantic_value hard-coded rate_options -> "conditional_rate"
(string) while the schema declares list.

## Root cause

Agent-written materializer value generation can violate schema categories;
integration catches it late (post-build, post-venv). The candidate_build node
already carries local_corrections=1 — the designed mechanism for feeding a
precise correction back to the codegen agent — but nothing exercises the
materializer during build.

## Fix direction

compile_candidate pre-flight: after rendering the workspace, run
materialize() + _validate_materialization per assurance recipe offline; on
failure raise a NodeExecutionError with an actionable correction packet
(category mismatches per field) — the graph's local correction loop
re-dispatches the codegen agent once with that feedback.
