# Diagnosis — real Direct usage evidence rejected by Artifact safety

## Expected behavior

The frozen `world_architecture` proof should receive a structured response from
the selected Direct model, persist secret-safe operation evidence, compile the
proposal, and commit one WorkRecord. Usage evidence is telemetry only and must
not contain the Prompt or gain semantic authority.

## Observed chronology

1. Route repair R1 passed an independent check with 92 tests and all static
   gates green.
2. The exact prior need, synthetic evidence and node entry were run through
   localhost `gpt-5.3-codex-spark`.
3. The real provider returned a parsed JSON result in about five seconds.
4. Before compilation, `GraphRunner` tried to persist `assurance.operation`.
   `ArtifactStore` rejected the standard Direct usage key `prompt_tokens` as an
   `artifact_forbidden_field` because the generic key filter protects Prompt
   content.
5. The narrow proof harness caught only `DesignError`, so process termination
   left `run_0fe1d0215d644837a43cfe7fc9994abe` with `status=running`, zero
   WorkRecords and `release=not_published`. Observe was read before diagnosis.

## Attribution

- Route/provider/model: reached and returned parsed JSON; not the first deviation.
- Prompt/input/Skill: Direct input was the frozen approved projection; no Skill,
  tools or workspace existed.
- Compiler: not reached.
- Framework contract: causal. `OperationEvidence` currently accepts provider
  aliases `prompt_tokens/completion_tokens`, while generic Artifact safety
  rejects the former key before commit.
- Graph/provenance: no WorkRecord was committed, so C8 did not produce a false
  success; its port bindings are unrelated.
- Proof harness: causal only to the stale `running` run fact, not to the
  underlying evidence-persistence failure. The public composition root already
  catches this `ValueError` family.

An offline control reproduced the boundary exactly: provider-named usage was
rejected, while equivalent `input_tokens/output_tokens/total_tokens` committed.

## Rejected strategies

- Do not weaken the generic Prompt/secret filter or special-case arbitrary
  `prompt_tokens` fields in ArtifactStore.
- Do not drop usage telemetry, modify the Prompt/output contract, retry the
  model, change routes, or add a graph error framework.
- Do not claim the returned model JSON passed the compiler; persistence stopped
  first.

## Smallest next proof

Normalize Direct provider usage to the canonical input/output names already
used by Codex Agent evidence and remove the rejected aliases from
`OperationEvidence`. Add a focused persistence regression, retain the stale run
unchanged as an observed interrupted diagnostic scope, then use a fresh run for
the exact frozen node and read Observe.
