# Cross-Layer Review: 0ff3ae1d (one-shot materializer transport)

## Decision

**allow** — the plan is the smallest honest Local repair that fixes the
deterministic candidate_protocol_timeout on the FIRST candidate call without
touching the persistent runtime JSONL protocol, any design/artifact/package/
Registry meaning, or any Judge/release invariant. Every claim is independently
verified: the materializer never flushes, the timeout is the select-timeout in
call(), EOF-triggered exit flush recovers the buffered response, the persistent
runtime.py path is a separate process/entrypoint untouched by the change, and
the skill line is defense-in-depth only. The proposed semantics are already
reproduced offline against the real frozen materializer (integrate -> passed,
zero LLM calls).

## Identity

- Plan digest (sha256, re-verified): 0ff3ae1df371daa53af1b2f83217681429d3c0a04d2fa189d1fbb1d3104c8c0b (short 0ff3ae1d).
- Plan revision: R1 (no prior review under this digest; it continues the
  direct-completion lineage after fe33df95's allow was spent on a scope that did
  not cover the candidate one-shot transport).
- Revision count: 1 (skill permits at most 2 revisions per lineage).

## Scope classification

**Local.** Producer: CandidateProcess (runtime.py) one-shot transport;
consumer: materialize() (runtime.py), the candidate materializer process. No
design, artifact, package, or Registry change. No agent-skill semantics change
(one guidance line added to the codegen skill for future candidates only).

## Trigger

Real e2e run_386e4f07c70d4f61be9cafbf82edcc55 (need=用户预订宾馆,
config/agent-world.example.toml), pure resume after the fe33df95 slice.
Terminal: candidate_protocol_timeout. Observe scene (read-only CLI, this
review) confirms terminal candidate_protocol_timeout, release not_published,
a block_release finding candidate_protocol_timeout on
build.environment_candidate:0032be9ba17a4644. local_tool_semantics_mismatch /
candidate_dependency_metadata_missing / candidate_teardown_failed findings are
on OTHER candidate builds (b7d139db7142fd72 / 864bb43a22bcb3e4), not the
0032be9ba17a4644 build this diagnosis targets — they are prior-lineage and/or
co-located attempts, not this plan's object.

## Diagnosis / Observe evidence (independently verified)

- Materializer never flushes: candidate_source/materializer.py line 113 is
  print(json.dumps(materialize(json.loads(line)))) inside 'for line in
  sys.stdin'; grep finds ZERO flush / flush=True / stdout.flush in the file.
- call() timeout: runtime.py:153 select.select([self.process.stdout], [], [],
  _TIMEOUT) with _TIMEOUT=20 (runtime.py:28). Popen uses text=True
  (runtime.py:110) and stdout=PIPE, so the child's stdout TextIOWrapper is
  block-buffered (not a tty); the response sits in the buffer until timeout.
- EOF exit-flush recovery: the one-shot semantics (write request line, flush,
  CLOSE stdin, then select+readline) are ALREADY implemented and validated in
  /tmp/e2e-trace.py (call_once lines 46-64; rt.materialize swap line 106). This
  review RAN it: integrate returns {'status':'passed','code':'ok'} with the real
  frozen non-flushing materializer, zero LLM calls. The child sees EOF, main()
  loop ends, Python exits, and normal process exit flushes the block-buffered
  stdout — confirming the POSIX buffering claim deterministically.
- Persistent path unaffected: _run_recipe (runtime.py:682) launches runtime.py
  (NOT materializer.py) via CandidateProcess with default close_protocol=True
  and drives the multi-request handshake/reset/invoke/snapshot/close protocol
  through call(). The runtime templates already flush (candidate.py:338;
  candidate_templates/runtime.py:49). The plan's call_once is orthogonal: it
  introduces a NEW method; call() is unchanged.
- Skill line defense-in-depth: engineer-environment-codegen SKILL.md section 3
  (self-verify) never mentions stdout flush today; the added line is future
  guidance only, and the framework no longer depends on candidate flush
  discipline after change 2.

## Affected trust boundary

CandidateProcess one-shot transport (untrusted agent-written materializer
stdout) -> framework materialize() consumer. The untrusted-process -> framework
boundary is exactly where the plan owns the flush semantics instead of
depending on the agent file. No downstream Judge/package/Registry boundary is
changed.

## Repeated product target

Natural-language EnvironmentRequest -> evidence-grounded design -> real isolated
runtime -> independent Judge (all required hard claims) -> immutable Registry
EnvironmentPackage -> safe Observe facts.

## Impact chain (producer -> consumer)

materializer.py (untrusted, stdout block-buffered) -> CandidateProcess.call_once
(new: write+flush+close stdin, then one response) -> runtime.materialize()
(switches call->call_once, close_protocol=False stays) -> integrate (first/
alternate materialize, runtime.py:881/885), judge (runtime.py:950), private
verifier cases (runtime.py:1030) -> package/Registry (shape unchanged). All four
call sites route through the single materialize() function, so one internal swap
covers every consumer uniformly.

## Owners

- Framework (runtime.py): CandidateProcess.call_once + materialize() switch.
- Future-candidate guidance only: engineer-environment-codegen skill (one line).
- The runtime Codex agent is NOT an owner; the materializer agent is NOT asked
  to change anything for correctness (the line is defense-in-depth, not a fix).

## Compatibility facts (verified, not assumed)

- call() body and close() semantics unchanged; only a new sibling method is
  added and one consumer re-pointed to it.
- close_protocol=False is preserved in materialize(); with stdin closed, the
  child's main() loop terminates on EOF naturally: close()'s terminate branch
  still guards the sub-case where the child ignores EOF, so teardown cannot
  regress.
- difficulty_has_no_semantic_effect / materializer_echo_mismatch /
  materializer_*_invalid / evaluator_goal_binding_invalid validation in the
  unchanged materialize() tail is untouched (only the call() invocation line
  changes).
- No prompt ids, artifacts, manifest entries, or Registry projections change;
  resume --from remains compatible (design/candidate heads unchanged).
- The offline trace's materialize swap is byte-equivalent to the plan's edit and
  already passes integrate against the frozen non-flushing materializer.

## Unproved consumers

- Judge/package/Registry remain unproven for THIS candidate (the plan honestly
  does not claim them; the next terminal is a new observation).
- Real-LLM regeneration correctness is not claimed; the plan reuses the frozen
  design/candidate heads with no --from.

## Smallest allowed implementation and proof plan

1. runtime.py: add CandidateProcess.call_once(payload) — identical response
   handling to call(), but close stdin immediately after writing+flushing the
   request line (select+readline+json.parse+dict guard as in call()).
2. runtime.py materialize(): call call_once instead of call(); keep
   close_protocol=False and the unchanged post-validation tail.
3. runtime_skills/engineer-environment-codegen/SKILL.md: add one guidance line —
   materializer.py MUST flush stdout per response (print(..., flush=True) or
   sys.stdout.flush()), labeled defense-in-depth.
4. tests/test_direct_runtime.py: add a deterministic test — a materializer stub
   that NEVER flushes (plain print, no flush=True) must still be served by
   materialize() (proves the framework owns one-shot flush semantics).

## Deterministic checks

- pytest: full suite green, including the new non-flushing stub test (existing
  materializer tests all use flush=True stubs, so the new test closes a real
  coverage gap).
- Offline bench (/tmp/e2e-trace.py) against the regenerated design + real
  prepare_candidate venv: materialize returns the validated response and
  integrate proceeds to the composition checks (already reproduced — integrate
  passed with zero LLM calls).

## True-boundary proof (smallest real)

1. The offline single-node bench already proves the untrusted-process ->
   framework one-shot boundary with the real frozen materializer (integrate
   returned status passed, zero LLM calls).
2. Real run: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
   (no --from; design/candidate heads already match current code) -> observe
   the terminal. Product Alignment Checkpoint at the proof terminal.

## Explicit non-claims

- Judge/package/registry do NOT pass by this plan; the next terminal is a new
  observation and a new diagnosis if it fails.
- Regenerated model output correctness is not claimed.
- Expand/Consumer/auto-capture remain unimplemented.
- The skill line does not fix any existing candidate; it only constrains future
  materializers (the framework fix, not the skill line, is what unblocks the
  current run).

## Next permitted gate

Implementation dispatch after the allow record lands in implement.jsonl and
check.jsonl, then the smallest real proof via agent-world-real-execution-proof,
then Observe. This allow expires if the plan digest, affected trust boundary, or
latest relevant real scene changes. A new failed scene starts a new diagnosis
and does not inherit this review's hypothesis.
