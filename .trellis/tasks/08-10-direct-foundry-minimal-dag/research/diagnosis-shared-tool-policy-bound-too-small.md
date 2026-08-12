# Diagnosis — SharedTool shared-policy bound is too small

- Date: 2026-08-12
- Diagnostic run: `run_d9fe033caff941c1a7bc385f019efaf3`
- Exact parents: Evidence `sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`;
  Architecture `sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`
- Boundary: `shared_tool_semantics[1-2-3-4-5-6]`

## Evidence and attribution

Two healthy primary Luna calls failed only `$.error_policy`; both exceeded the
disclosed 280-code-point bound, including the complete replacement after the
exact `value must use at most 280 code points` correction. SharedTool committed
no output, ToolSemantics did not run, Observe has one blocking Direct Work/
Finding and `release=not_published`.

The exact safe condition rules out type, emptiness, transport, parser, hidden
bound, Skill and route causes. One group-wide shared policy for six related
tools cannot be preserved at 280 for this input. The cap is a Source
compactness policy, not a `SharedToolContract`, Candidate, package, Registry or
release invariant.

Direct LLM still owns policy meaning. Framework owns only the declared bound,
validation, coordinate binding, Work/Artifact and release. No Agent conversion,
retry increase, truncation or validator relaxation is justified.

## Smallest repair and proof

Raise only SharedTool source `error_policy` from 280 to 500 code points.
Ordering remains 500; compensation remains 160. One shared string, framework
per-member binding, compiled tuple/digest, graph, route and two-call bound stay
unchanged. The rendered source shape changes and rotates semantic revision; no
ABI version changes or old Work adoption.

Five hundred matches the bounded semantic-text policy and adds at most 220 code
points per shared group. A real `>500` terminal starts a new diagnosis.

After checks, rerun the same exact parents, Luna
`shared_tool_semantics[1-2-3-4-5-6]`, then only
`tool_semantics[register_member]`, stop and Observe. Pass permits one fresh
public E2E but proves no Candidate, Judge, Registry, Repair, Expand or Consumer.

