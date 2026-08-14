# Diagnosis Record 4: candidate_protocol_timeout on materialize (stdout buffering)

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55, pure resume after the
fe33df95 slice. Terminal: rejected / candidate_protocol_timeout.

## Safe Observe facts

- Design fully regenerated (positive guards, when-only tasks) and candidate
  re-built (build.environment_candidate:0032be9ba17a) under the new code.
- Integration fails at the FIRST candidate call: materialize.
- Offline trace (real prepare_candidate venv): CALL materialize ->
  candidate_protocol_timeout, stderr empty. The same materializer responds
  instantly when driven to EOF on a plain pipe.

## Root cause (deterministic)

The agent-written materializer.py prints its JSON response with print() and
never flushes. Under a pipe (text=True), stdout is block-buffered; the
response sits in the buffer while the framework's CandidateProcess.call()
select()s on stdout until _TIMEOUT. The earlier materializer passed by luck
(buffer flush timing). The runtime template flushes explicitly; the
materializer is agent-written and must not be trusted to flush.

## Five-lens status

Lens 4 (execution boundary, CandidateProcess one-shot protocol) supported.
The agent file is untrusted input by design; the framework must not depend on
its flush discipline.

## Fix direction (small, framework-owned)

- CandidateProcess.call_once(payload): write + flush + CLOSE stdin, then read
  one response (same parsing as call). One-shot semantics: the child reads
  the line, responds, sees EOF, exits, and its exit flushes the buffer.
- runtime.materialize() uses call_once for the materializer process.
- engineer-environment-codegen skill: require explicit stdout flush in
  materializer.py (defense in depth, future candidates).
- Deterministic test: a materializer stub that never flushes must still
  produce the framework-validated response via materialize().
