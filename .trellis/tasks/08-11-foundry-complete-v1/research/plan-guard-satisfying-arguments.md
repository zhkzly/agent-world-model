# Repair Plan: guard-satisfying argument generation for integration

Lineage: diagnosis-10-guard-satisfying-arguments.md. Continues the
direct-completion lineage after fe33df95 / 0ff3ae1d / 58a29e92 / 3fd31254 /
c0fe624d / 4ec3cd93 allows (all spent).

## Scope classification

Local. Producer: _run_recipe argument construction (runtime.py); consumer:
integration/judge success-path driving. No design, schema, artifact, package,
or Registry change.

## Changes

1. agent_world/runtime.py: helper _guard_arguments(tool, arguments) — after
   generating _value defaults, adjust each argument field per precondition
   predicates over argument bindings: eq -> set right; ne -> vary if equal;
   ge/gt -> raise value into range; le/lt -> lower value into range;
   exists/not_exists -> ensure presence/absence semantics already covered by
   category defaults. Deterministic; leaves satisfiable guards satisfiable.
   Apply it in _run_recipe before the invoke payloads (both the target tool
   and prefix actions).
2. Deterministic test: a tool with an adults >= 1 guard is driven with
   adults = 1 (not 0) through integrate().

## Compatibility

- Trace shape unchanged; private-case varied_arguments still override.

## Checks and proofs

- pytest full suite green.
- Offline bench: integrate() against the frozen regenerated design must pass
  all recipes.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim judge/package/registry pass; further terminals are new
  observations.
