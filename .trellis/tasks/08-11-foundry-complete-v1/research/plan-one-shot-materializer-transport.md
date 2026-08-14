# Repair Plan: one-shot candidate protocol (materializer stdout buffering)

Lineage: diagnosis-4-materializer-buffering.md; continues the direct-completion
lineage (cross-layer-review-fe33df95 allow is spent — its scope did not cover
the candidate one-shot transport).

## Scope classification

Local. Producer: CandidateProcess (runtime.py) one-shot transport; consumer:
materialize() (runtime.py), the candidate materializer process. No design,
artifact, package, or Registry change. No agent-skill semantics change (one
guidance line added to the codegen skill for future candidates).

## Changes

1. agent_world/runtime.py CandidateProcess.call_once(payload): identical
   response handling to call(), but closes stdin immediately after writing
   the request line. One-shot processes respond, see EOF, exit, and exit-time
   flush delivers the buffered response.
2. agent_world/runtime.py materialize(): use call_once for the materializer
   request (materializer runs one request per process; close_protocol=False
   stays).
3. agent_world/runtime_skills/engineer-environment-codegen/SKILL.md: add one
   guidance line — materializer.py MUST flush stdout after every response
   (print(..., flush=True) or sys.stdout.flush()) so stdout buffering never
   delays the protocol (defense in depth; the framework no longer depends on
   it).
4. tests/test_direct_runtime.py: add a deterministic test — a materializer
   stub that NEVER flushes must still be served by materialize() (proves the
   framework owns the one-shot flush semantics).

## Compatibility

- Runtime persistent protocol unchanged (it already flushes).
- prepare_candidate / venv / admitted closure untouched.
- No prompt ids change; no artifacts regenerate.

## Checks and proofs

- pytest: full suite green including the new non-flushing stub test.
- Offline bench (/tmp/e2e-trace.py) against the regenerated design + the real
  prepare_candidate venv: materialize must return the validated response,
  integrate must proceed to the composition checks.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  (no --from; design/candidate heads already match the current code) and
  observe the terminal.

## Non-claims

- We do not claim judge/package/registry pass; the next terminal is a new
  observation.
