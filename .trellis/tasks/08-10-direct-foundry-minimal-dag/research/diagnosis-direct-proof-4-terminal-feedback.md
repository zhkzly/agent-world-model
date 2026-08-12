# Diagnosis — terminal Direct validation loses its safe issue packet

## Expected behavior

When a model proposal still fails after its one authorized correction, the
framework must stop without retry while retaining enough safe evidence to
attribute the exact output-contract condition. The packet is diagnostic
evidence only; it must not become routing or release authority.

## Observed chronology

1. Spark run `run_9b004e18777140cc8cdfded98a6933cc` and Luna run
   `run_55dc9b1ca3c744b69b8d3e7cb0def188` used the same frozen node contract.
2. Both attempt 1 records contain the same safe packet for `$.name` and one
   correction was sent.
3. Both attempt 2 records terminate with `world_architecture_tool_invalid`, but
   their `correction` is `null` and the failure Artifact has `evidence=null`.
4. Both runs are honestly rejected with complete dependencies, two operation
   refs, one failed WorkRecord and no release.

## Attribution

- Route/model-only hypothesis: falsified by the identical Spark/Luna sequence.
- Prompt/compiler interface: likely boundary of the semantic mismatch, but the
  exact terminal tool path/condition is not durably available, so a Prompt or
  contract change would be guesswork.
- Framework feedback persistence: causal diagnostic gap. `DesignError` still
  carries a safe `CorrectionPacket`; `GraphRunner` stores it only when another
  invocation is eligible, then writes `exc.evidence` (currently `None`) into
  the terminal failure Artifact.
- Provenance/Observe/release: correctly fail closed. No false output exists.

## Rejected strategies

- Do not add a third attempt, rotate another model, inspect/persist raw response,
  guess the tool shape, or weaken the compiler.
- Do not add a new feedback schema or expose the packet in public Observe.
- Do not mutate either rejected run.

## Smallest next proof

At terminal failure only, use the existing safe `CorrectionPacket` as the
existing failure Artifact's evidence when no explicit evidence was supplied.
Add a regression that proves no extra invocation occurs and the packet is in
the WorkRecord assurance closure. Then one fresh Luna node run can either pass
or expose the exact terminal condition needed for an evidence-based decision.
