# Verify a Project-Agent View

The intended proof is a navigation exercise, not a Runtime Agent invocation.
Check the smallest applicable claims:

- Every advertised path exists, is current, and answers the question beside it.
- A fresh project-execution Agent that has not explored the area can read the
  top-level view, name its first precise reads, and avoid broad search.
- Attempt transitions replace stale summaries rather than grow injected context
  over time.
- In one real project debugging exercise, the Agent can state a defensible next
  investigation or repair target from the view plus selected reads.

Smoke-test the registered hook event and inspect its emitted text. Run a real
runtime node only when a separately changed Prompt/input, Runtime Skill,
profile, runtime context, or repair path makes a runtime claim.
