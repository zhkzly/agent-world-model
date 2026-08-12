# Minimal repair plan R1 — retain terminal safe validation evidence

## Goal

Make an exhausted model-validation failure actionable without adding retries,
raw output retention or a new feedback/control system.

## Exact implementation

1. In the existing `GraphRunner.execute` terminal error path, keep explicit
   `exc.evidence` when present; otherwise use the existing
   `exc.correction` packet as the existing failure Artifact's `evidence` value.
   Eligibility alone still controls whether another invocation occurs.
2. Add focused runner coverage with distinct packet identity and precedence:
   - attempt 1 raises packet A and terminal attempt 2 raises distinct packet B
     with no explicit evidence; assert calls are exactly `[None, packet_A]`, no
     third call occurs, the terminal attempt is `failed`, and the failure
     Artifact in both WorkRecord assurance and Finding evidence closures stores
     packet B, never packet A;
   - parameterize terminal attempt 2 with distinct explicit safe evidence,
     including `{}`; assert that exact value is persisted instead of packet B.
     This requires an `is not None` choice and forbids truthiness fallback.
3. Run the existing deterministic quality gate, then one fresh exact Luna
   `world_architecture` proof and read Observe plus the referenced safe failure
   Artifact if the node rejects again.

## Explicit non-goals

No new field/schema, public Observe projection, retry/budget/model/route change,
Prompt/compiler/tool contract change, raw response retention, graph topology,
Skill, stale-run, Candidate, Repair, Expand or Consumer implementation.

## Acceptance

- Existing explicit failure evidence, including an empty JSON value, wins over
  a correction packet; without it, the exact terminal packet wins over the
  prior-attempt packet.
- Exhausted safe model feedback is durably attributable without another call.
- Existing checks remain green.
- The fresh node either commits a passing WorkRecord or yields an exact safe
  terminal path/condition for the next diagnosis; neither outcome is E2E proof.
