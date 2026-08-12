# Plan lineage — release/public handoff

- Lineage: `release-public-handoff`
- Revision: R1
- Opened: 2026-08-11
- Predecessor: complete-v1 R2 digest
  `42ac2771e619d88dd034de6267a936a13f657910e3237b750f7af606f09741da`
- Trigger: predecessor review returned `needs_human` at its two-revision limit.
- Human decision: confirmed all three coordinated policies on 2026-08-11.

## Confirmed product policies

1. Campaign/Suite snapshots remain byte-immutable, while each attempted parent
   use or new Episode obtains a framework-owned result from the exact current
   Registry record. Quarantine or supersession blocks use without rewriting
   history.
2. Candidate infrastructure error is represented separately from hard-gate and
   release status, carries exact evidence and is not candidate quality.
3. Public Episode admission contains selection fields only. Framework obtains
   `initial_config` from MaterializerResult and keeps the reset handoff private
   from training callers, SFT, RL input, logs and Observe.

## Bounded revision scope

Only parent, Expand and Consumer planning contracts/tests may change. Direct
and Repair R2 inputs remain byte-identical. This lineage adds no runtime Critic,
second Registry/Judge, graph, scheduler, policy platform or compatibility path.

## Product Alignment Checkpoint — lineage entry

The canonical goal remains natural-language need -> evidence-grounded complete
Design -> executable isolated candidate -> independent Judge -> immutable
Registry `EnvironmentPackage` -> safe Observe, with Expand producing diverse
new packages and Consumer proving downstream SFT/RL usability. This revision
affects the Registry-to-Campaign/Consumer trust boundary and the private
Materializer-to-Runtime boundary. Evidence currently consists only of the
canonical document, the predecessor independent review and the human product
decision. No graph, implementation, real Direct release, Expand candidate,
Episode or end-to-end product completion is proven or claimed.

## Product Alignment Checkpoint — P0 calibration exit

The canonical goal is unchanged. The affected boundary was development-time
orientation only: cross-layer Critic scope, the derived execution map and
subagent dispatch context. Evidence is the exact-digest parent `allow` in
`cross-layer-review-b34be669.md`, five passing Trellis task validations and the
bounded `PASS` in `p0-calibration-check-b34be669.md`. The calibration did not
add or change a runtime node, graph, Judge, Registry, product contract or
product source file.

The first ordinary check dispatch explicitly selected
`gpt-5.3-codex-spark` but failed before review because its backend rejected the
inherited `reasoning.effort=max`; the channel error is the recorded capability
failure required for escalation. The fresh replacement explicitly selected
`gpt-5.6-terra` and performed the passing check. This is not evidence that any
runtime model route, Direct generation, repair, Expand, Consumer, SFT/RL or
end-to-end product behavior works. Graph/test/planning progress is not being
claimed as product completion.
