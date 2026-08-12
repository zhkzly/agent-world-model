# Foundry Product-Alignment Checkpoints

Use this guide at the entry and exit of every key graph node family, child-task
boundary, real execution proof, release decision, and legacy-disposition
decision.

The canonical source remains
[`docs/agent-world-environment-generation.zh.md`](../../../docs/agent-world-environment-generation.zh.md).
This guide does not redefine that product contract; it prevents local progress
from being mistaken for the product outcome.

## Non-negotiable north star

The Foundry compiles a natural-language environment need into a real executable,
independently verified, Registry-released `EnvironmentPackage`. Code owns the
workflow, Artifact DAG, gates, repair budget, routing, and release decision;
Agents perform bounded research, design, generation, challenge, and repair
proposal only.

`GraphExecutor` progress, a committed slice, passing unit tests, an import
cleanup, or a deleted legacy file is never product completion by itself.

## Required record

Append one record to the active task's
`research/product-alignment-checkpoints.md`; do not overwrite earlier records.
The record must contain:

1. **Checkpoint and boundary** — node family/child/decision and whether this is
   an entry or exit record.
2. **North-star link** — how this work advances
   `EnvironmentRequest -> Evidence/WorldSpec/Task+Verifier+Implementation ->
   real runtime -> independent Judge -> Registry EnvironmentPackage`.
3. **Trust owner and Artifact effect** — which of FoundryController,
   EnvironmentDesigner, EnvironmentBuilder, EnvironmentJudge, or
   EnvironmentRegistry owns the boundary; which immutable Artifacts/Gates are
   created, validated, invalidated, or intentionally untouched.
4. **No-hybrid assertion** — the relevant new normal path does not import/call
   legacy control authority. If it is not yet true, the checkpoint is blocked
   and must not claim a Direct/Expand proof.
5. **Evidence** — concrete tests, import/call graph report, Observe scene, or
   real execution facts; label deterministic checks separately from real E2E.
6. **Non-claims and remaining risk** — state exactly what this checkpoint does
   not prove, especially any missing runtime/Judge/Registry/Expand evidence.
7. **Bad-case effect** — name which known bad case is prevented, detected,
   repaired, honestly stopped, or still unresolved; link the task's bad-case
   matrix when one exists.
8. **Next permitted gate** — the smallest next action that follows from the
   evidence.

## Completion rule

Do not mark the boundary complete until its exit record exists and its
no-hybrid assertion and evidence support the claimed scope. For a failed real
run, read the Observe scene before writing a repair plan.

## Wrong versus correct

**Wrong:** “The graph node committed and its unit test passed, so Direct works.”

**Correct:** “The node committed its declared `WorldSpec` Artifact under the
cleanroom graph. This proves only the modeling boundary. The record links its
acceptance digest and imports, notes that Builder/Judge/Registry remain
unproven, and names the next gate.”

**Wrong:** “We can run a hybrid Direct path once, then remove old imports.”

**Correct:** “Before any Direct E2E claim, the cleanroom's transitive public
path has zero forbidden legacy control authority. A real run then proves the
product closure, not a compatibility path.”
