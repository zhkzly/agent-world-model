---
name: engineer-build-planning
description: Read frozen Agent World implementation inputs and produce one advisory implementation plan without writing candidate source. Use only for the BuildImplementationPlan node.
---

# Engineer Build Planning

You are preparing a later, separate CandidateBuild turn. Your output is useful
only as an implementation map; it has no authority over the frozen world,
contract, permissions, validation, repair routing, or release.

1. Read `inputs/world-spec.json`, `inputs/curriculum.json`,
   `inputs/implementation-contract.json`, and
   `inputs/task-materializer-output.schema.json` before proposing a plan.
2. Reconcile the WorldSpec transitions, visibility, permissions, errors,
   idempotency and task curriculum with the implementation contract. If two
   files appear to disagree, identify the exact frozen source rather than
   inventing a resolution.
3. Produce a compact orientation map for the next Engineer: smallest
   module/file layout; shared implementation patterns for state, tool
   transitions, permissions and errors; Task Materializer v3 mapping; runtime
   JSONL boundary; public self-check/public-test strategy; and validation
   order. Target roughly 8,000 characters and stay within the 12,000-character
   output contract.
4. Do not transcribe every Rule, JSON field, schema clause, or transition.
   Group repeated patterns, and name a concrete tool/rule/input only when it
   changes implementation behavior or prevents ambiguity. CandidateBuild will
   read the complete frozen inputs itself.
5. Name genuine implementation risks or unresolved details honestly. Do not
   turn uncertainty into invented requirements, fixed replay fixtures, expected
   answers, verifier logic, or release assertions.

Do not write `candidate/` or any source file. Do not run a build, test, Judge,
or package operation. Do not claim that a Candidate, a test result, an
evaluation, or a release exists. Return only the requested
`ImplementationPlanDraft` JSON.
