# Direct C5 whole-diff check — block

Date: 2026-08-11
Reviewer: independent `trellis-check`, Codex `gpt-5.6-terra`
Decision: `block`

The reviewer independently reproduced the Direct plan digest
`37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`
and parent digest
`3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`.
It changed no files and ran no provider.

Blocking findings:

1. `GraphRunner.execute` does not enforce exact input ports or declared Edge
   producer routing; a hostile `candidate_build` call committed with its
   required `build_plan` input absent.
2. CandidateBuild's frozen files omit the exact Materializer and Runtime JSONL
   request/response schemas consumed by Integration, so a fresh Agent needs
   ambient implementation knowledge.
3. VerifierIntent is free-text and Judge repeats the disclosed public step;
   the current VerifierBundle is not an independently executable sealed
   challenge.
4. `NodeSpec.local_corrections` is declarative only; the promised single
   bounded output-contract correction is never dispatched.
5. The code-generation Skill requires stdlib-only metadata while C5 admits a
   finite verified registry-wheel closure.
6. Package writes an empty hard-coded SBOM and minimal `envpkg.toml`; Registry
   does not recompile and cross-bind the portable package closure.
7. Candidate processes inherit the ambient environment, and hidden candidate
   files are silently omitted rather than rejected.

Additional main-session cross-layer finding: the pre-publish telemetry summary
is hard-coded instead of derived from committed invocation/research operation
evidence, although the active plan explicitly forbids that claim.

Verification evidence at the blocked boundary:

- full tests: `56 passed`;
- focused hostile/tamper tests: `35 passed`;
- Ruff format/check, mypy, compileall, diff check and legacy firewall: passed;
- real Direct LLM, Agent, Candidate and E2E proofs: not run.

Deterministic green is not Direct completion. Implementation may resume only
after a minimal revised closure plan receives a fresh independent cross-layer
`allow`.
