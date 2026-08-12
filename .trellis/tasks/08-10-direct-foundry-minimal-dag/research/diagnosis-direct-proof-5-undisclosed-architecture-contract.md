# Diagnosis — WorldArchitecture input omits enforced identifier rules

## Expected behavior

The Direct `world_architecture` node should receive a concise but complete
description of the output contract that its framework compiler already
enforces. One local correction remains a bounded fallback, not the normal way
to reveal one hidden rule at a time.

## Observed chronology

1. The terminal-feedback repair passed independent deterministic review.
2. Fresh Luna run `run_66a0ba4ecc274c20a112e4ed8cf268be`
   executed the frozen `world_architecture` proof.
3. Attempt 1 violated `$.name` because the environment name was not a kebab
   identifier; the framework sent its one authorized correction.
4. Attempt 2 was rejected at `$.tools[0].name` because the tool name was not a
   snake identifier.
5. Observe reports one failed Designer/Direct-LLM WorkRecord, a blocking
   Finding, no output, `status=rejected`, and `release=not_published`. The
   referenced failure Artifact contains the exact terminal packet.

## Attribution

- The model-facing `output_shape` says only that environment and tool names are
  strings. It does not disclose the kebab/snake identifier rules or the
  existing bounded-array rules enforced immediately afterward by the
  framework compiler.
- The same hidden-contract sequence occurred with Spark and Luna, so another
  route change is not causal.
- The compiler, one-correction limit, provenance chain, failure closure and
  release block behaved correctly. Weakening them would hide rather than fix
  the producer/consumer mismatch.
- Downstream nodes consume the framework-compiled architecture. Its schema and
  meaning need not change; only the proposal instruction is incomplete.

## Rejected strategies

- Do not add retries, rotate models, normalize model output, or weaken the
  compiler.
- Do not add a schema/prompt framework or change another Direct node without
  evidence.
- Do not change graph topology, Artifacts, WorkRecords, Candidate, Repair,
  Expand, Consumer, Registry, or Observe.

## Smallest next proof

Disclose this node's existing closed constraints in its existing
`output_shape` value, add one focused regression that proves the exact
contract reaches the Direct backend and a valid proposal commits unchanged,
then repeat the same Luna node proof and read Observe.
