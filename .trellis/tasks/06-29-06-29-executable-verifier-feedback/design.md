# Design

## Project Alignment

This change serves the full environment generation goal: request/source material should become an executable, verified, packaged environment. The implementation stage is a workflow inside the larger S0-S11 workflow. Codex or another code agent may write and repair files, but the framework owns contracts, execution checks, observations, retry budget, and release.

The design avoids a small booking-only fix. Booking, library, and project-board replay details may remain strategy-specific, but the new contract and observation shapes must be common framework artifacts.

## Data Flow

```text
S0-S9 accepted artifacts
  -> framework builds FrameworkReplayContract
  -> runner workspace input/framework-replay-contract.json
  -> agent writes generated/ and candidate_manifest.json
  -> framework candidate check executes generated files
  -> FrameworkCheckObservation
  -> IndependentVerificationReport
  -> failure packet for next bounded repair attempt
  -> final release only when generated check and independent verifier pass
```

## Contract Envelope

Add a shared framework replay contract builder. The top-level contract should be stable:

- `schema_version`
- `environment_id`
- `candidate_dir`
- `bundle_files`
- `manifest_contract`
- `runtime_contract`
- `verifier_contract`
- `trace_contract`
- `replay_cases`
- `check_command`

Domain-specific details live under `replay_cases[]`, not in separate ad hoc prose files. Each case can describe:

- `case_id` / `task_id`
- `kind`
- `expected_dependency_path`
- `tool_calls`
- `expected_state_or_answer`
- `negative_case`

The contract is input to the agent. It is not release evidence by itself.

## Observation Envelope

Add a JSON-compatible observation shape owned by the framework:

- `schema_version`
- `check_id`
- `status`
- `success`
- `environment_id`
- `candidate_dir_ref`
- `failure_class`
- `recovery_suggestion`
- `prerequisite_observations`
- `task_observations`
- `exception`
- `summary`

Task observations should carry:

- `task_id`
- `case_id`
- `phase` such as `instantiate_runtime`, `tool_call`, `call_verifier`, `assert_state`, `assert_trace`
- `tool` and `kwargs` when the failed phase is a tool call
- `expected`
- `actual`
- `positive_verifier_result`
- `negative_verifier_result`
- `trace_evidence`
- `state_or_answer_evidence`
- `exception` with traceback when execution throws

The observation may be embedded into `IndependentVerificationReport` and repair packets. It should avoid absolute workdir paths where a relative reference is enough.

## Candidate Check / Preflight

Expose a framework-owned check function that evaluates a candidate directory and returns the observation envelope. It should reuse the independent verifier strategies instead of duplicating business rules.

Implementation options:

- Python API: `check_generated_candidate(build_dir, environment_id, accepted_tasks=...)`
- CLI/module entrypoint for runner self-preflight: `uv run python -m agent_world.candidate_check --environment-id ... --candidate-dir generated --output-json`

The runner can call the check during implementation, but the final pipeline gate must call it again after the runner exits.

## Independent Verifier Changes

Current verifier already imports generated runtime/verifier/seed, checks prerequisites, executes positive/negative task cases, and checks trace/state/answer evidence. This task improves evidence quality:

- wrap each task replay in exception capture so one task failure records a task observation instead of collapsing all remaining tasks into generic prerequisite failure
- include full traceback for Python exceptions
- include expected/actual data for trace and state/answer mismatches
- convert prereq checks and task records into the shared observation shape

## Repair Packet Integration

Failure packet should include:

- prior summary fields already present
- `framework_check_observation`
- failed task observations
- failed prerequisite observations
- traceback previews with redaction
- candidate paths/hashes as relative refs

The repair instruction should tell the agent to treat this as a tool observation and repair the generated bundle, not change pipeline flow or manifest shape unless the observation says the failure is manifest/path/hash-related.

## Compatibility

- Keep existing generated bundle validators and independent verifier strategies.
- Preserve current `IndependentVerificationReport` required fields.
- Add fields rather than renaming existing ones where practical.
- Normal tests must not require live Codex, network, or credentials.
- Keep all Python validation under `uv`.

## Tradeoffs

Using a generic contract/observation envelope with strategy-specific replay cases is less "pure" than a complete universal verifier DSL, but it fits the current state of the project. It improves code-agent repair quality now without pretending arbitrary-domain verifier synthesis is solved.
