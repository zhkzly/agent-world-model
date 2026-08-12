# Diagnosis — Spark did not converge on WorldArchitecture contract

## Expected behavior

With usage evidence now persistable, the real Spark `world_architecture` turn
should return the closed authority-free object or satisfy one exact local
correction, after which compiler validation commits a passing WorkRecord.

## Observed chronology

1. Usage repair R1 passed 97 full tests and an independent check.
2. Fresh run `run_9b004e18777140cc8cdfded98a6933cc` invoked the same need,
   evidence and node through `gpt-5.3-codex-spark`.
3. Attempt 1 returned a parsed object but violated `$.name`: the name was not a
   kebab identifier. Framework issued exactly one safe correction packet.
4. Attempt 2 returned another parsed object but failed
   `world_architecture_tool_invalid`. The configured local correction budget was
   exhausted, so framework committed a failed WorkRecord and Finding.
5. Observe reports `status=rejected`, two canonical `assurance.operation`
   refs, exact request/evidence dependencies, no output and
   `release=not_published`.

## Attribution

- Provider/transport and usage persistence: passed; both real operations are
  durably evidenced with canonical token fields.
- Direct input/Skill surface: the frozen projection was used; Direct has no
  Skill, tools or workspace.
- Model/profile compatibility: causal. Spark did not satisfy this closed Direct
  semantic contract in two allowed attempts.
- Compiler/feedback: correctly rejected both proposals and spent exactly one
  local correction. The terminal record preserves the safe code but not a
  terminal path, so changing tool-shape Prompt text would be guesswork.
- Graph/provenance/Observe: passed; failure dependencies and evidence are
  complete and no false output/release exists.

## Rejected strategies

- Do not increase retries or local correction budget.
- Do not guess a new tool Prompt/schema from an unpersisted raw response.
- Do not weaken identifiers/tool contracts, add model-specific normalization,
  or route semantic failure automatically inside `DirectChatBackend`.
- Do not adopt either failed/incomplete run.

## Smallest next proof

The user explicitly authorized localhost `gpt-5.6-luna` when Spark does not
work, and a credential-safe control already proved that route reachable. Select
Luna as the checked-in Direct primary and retain Spark as its existing
retryable-transport fallback, without changing adapter logic. Then run the same
fresh node proof once and read Observe.
