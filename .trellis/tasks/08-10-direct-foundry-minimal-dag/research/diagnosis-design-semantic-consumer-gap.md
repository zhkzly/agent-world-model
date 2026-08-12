# Diagnosis — DesignGraph semantic outputs are lossy

## Expected product behavior

The canonical target is one natural-language need becoming an
evidence-grounded, executable Environment Design, then candidate code,
isolated Integration, an independent Judge, an immutable Registry package and
safe Observe. The Design must also be a stable semantic anchor for future
Expand; every model-owned business field therefore needs a framework compiler,
an immutable Artifact and a real downstream consumer.

## Observed static evidence

The fresh whole-diff check `direct-r2-independent-check.md` blocked live proof
despite `131 passed`:

- `shared_tool_semantics` accepts only `{"groups": list}` and forwards that
  untyped value into the next prompt; it is absent from Design, Builder input,
  Rule IR, package, Registry and Observe;
- WorldArchitecture retains only names plus untyped argument/result names;
- WorldRules becomes free strings;
- Curriculum and TaskRequirement collapse to one family/one fixed scenario;
- Modeling Gate and Runtime/Judge select only the first tool/task;
- these shapes differ from the binding node contracts and canonical Direct
  world-model flow.

The eight separate test-annotation errors have already been fixed without
changing semantics; `mypy agent_world tests` now passes. They are not part of
this diagnosis.

## Causal attribution

The cleanroom implementation preserved the node names but implemented several
of them as thin placeholders. It validated local JSON shape without verifying
that the compiled value survived every downstream handoff. This let static
fixtures pass while losing the state/tool/task meaning needed by Builder,
Judge, Registry and future Expand.

This is not a Luna instruction-following failure, a provider timeout, a Skill
isolation failure, or a reason to add retries. Luna was asked for lossy or
misleading output contracts; the framework then discarded valid model output.

## Product impact

A package produced from these contracts could be executable but semantically a
toy: it cannot durably state its world schema, cross-tool obligations, global
rules or parameterized task families. Such a package is not a trustworthy
Expand parent or training environment, and a real E2E release would not close
the canonical product claim.

## Repair boundary

Replace the lossy Design contracts and their consumers in place. Keep the two
existing graphs, node families, runner, Invocation backends, five-operation
Runtime, Candidate isolation, Judge/Registry ownership and Observe plane. Do
not add a graph engine, generic schema/rule platform, scheduler, permission
system, Repair, Expand or Consumer implementation.
