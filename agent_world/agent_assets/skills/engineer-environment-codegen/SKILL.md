---
name: engineer-environment-codegen
description: Implement, test, or repair one executable Agent World Candidate from frozen Builder inputs in its direct host workspace. Use only for CandidateBuild, including an initial build, continuation, fresh draft recovery, or authorized correction.
---

# Engineer Environment Codegen

## Work in the supplied workspace

Use only relative workspace paths:

- `inputs/...` contains immutable framework inputs.
- `candidate/...` is the only project you may create or edit.
Use the normal host `uv` and Python available through `PATH`. The framework has
already set this directory as the SDK `cwd` with full access; it does not mount
virtual paths or provide copied tool facades. Keep implementation work in
`candidate/` and read frozen facts from `inputs/`; do not depend on a parent
checkout, a profile directory, or a prior thread's private draft.

Candidate runtime tests start child Python with `sys.executable`; the public
runtime itself knows only the declared `AGENT_WORLD_STATE_DIR` interface.

## First pass: establish a running spine

Before broad exploration:

1. Run `pwd` and list only the current workspace. Never inspect `..`, a host
   checkout, profile directories, or an earlier thread.
2. Run the mounted `candidate_contract_map.py` once. It makes the cross-file,
   frozen acceptance surface compact before you choose a source layout; it
   does not validate Candidate code or replace Integration.
3. Inspect only the authoritative input fields needed to choose the initial
   source layout, one state slice, and one tool slice. Do not dump complete
   JSON documents, enumerate every tool first, or repeat an inspection that
   already answered the decision.
4. Read the phase-specific references below, create the Candidate skeleton,
   and run the closest executable check before starting the next slice.

The first pass must create real Candidate source early. Do not postpone all
writing until after exhaustive input or reference reading. Frozen JSON is
authoritative, but an advisory plan is not a reason to scan every input before
building and checking a coherent vertical slice.

When `inputs/implementation-plan.md` is present, read it first only as a compact
orientation index: use it to choose the first source slice and the relevant
frozen sections. It cannot establish semantics. Before implementing each slice,
read the exact corresponding frozen JSON fields; do not consume every input
before writing the first Candidate skeleton.

Read these frozen inputs narrowly as the current decision needs them:

- `inputs/implementation-plan.md`, when present, as advisory orientation only
- `inputs/world-spec.json`
- `inputs/curriculum.json`
- `inputs/implementation-contract.json`
- `inputs/task-materializer-output.schema.json`

Read every relevant field before claiming the corresponding behavior is
complete. Frozen JSON wins over the advisory plan.

## Load detail progressively

This is one CandidateBuild method, not three additional Skills. Load each
bundled detail only when its phase begins:

1. Before implementing Runtime or Task Materializer, read
   [references/runtime-and-materializer.md](references/runtime-and-materializer.md).
2. Before writing `pyproject.toml`, `LICENSE`, or `uv.lock`, read
   [references/python-project-delivery.md](references/python-project-delivery.md).
3. Before returning `CandidateCompletion`, read
   [references/completion-contract.md](references/completion-contract.md).

Do not load the completion reference during the initial build. Do not copy
reference text into the node Prompt. These are read-only parts of this Skill.

## Build and debug as a Code Agent

Implement the real declared behavior; do not use fixed replay,
environment-specific branches, fixture registries, mocks, stubs, generated
release checks, or framework-name blacklists.

Use a tight internal engineering loop:

1. Implement one coherent slice.
2. Run its closest executable check or public test.
3. Read the actual failure, locate the producing Candidate source,
   configuration, test, or metadata boundary, and make the smallest coherent
   correction.
4. Rerun that same check before moving on.

Do not make a test green by deleting, weakening, or bypassing frozen behavior.
Before completion, run every final public test, Runtime and materializer entry
check, uv metadata/lock check, and the bundled deterministic Candidate-tree
preflight. Public tests are standalone Python programs: do not assume `pytest`
or another development tool exists merely because it was available while you
were writing. A check that passed before the last relevant edit is stale.

Public tests alone are not sufficient. In this same workspace, also run the
declared public self-check module, a Runtime handshake/error-path and
tool-specific invoke-observation probe, and representative Task Materializer
calls for every task type against the frozen output schema. Use the Candidate's
physical relative import root (for example `candidate/src` for a `src/` layout,
otherwise `candidate`); never encode or try to discover a later Judge mount,
host path, or deployment layout. See
[references/runtime-and-materializer.md](references/runtime-and-materializer.md)
for the component-specific acceptance method and the Candidate-owned complete
materializer campaign. The map's campaign is a required local check, not a
future-Judge guess.

Before completion, prove one cross-component path for every materialized task
type and allowed actor: reset the real Runtime with that task's initial config,
then invoke every task-required tool using legitimate sample arguments derived
from the frozen task/domain data. Check the initial state against the tool
preconditions you rely on before blaming Candidate code. If an allowed state
domain cannot contain a required precondition literal, or no legitimate
materialized state can reach a required tool, the frozen inputs are mutually
inconsistent: return an honest blocked completion with the smallest input
paths, rather than inventing a Candidate-only lifecycle or weakening a test.

Run the acceptance map and project-mechanics preflight from the mounted Skill
bundle with the normal host Python:

```text
SKILL_DIR="$CODEX_HOME/skills/engineer-environment-codegen"
python "$SKILL_DIR/scripts/candidate_contract_map.py" --workspace .
python "$SKILL_DIR/scripts/check_materializer_campaign.py" \
  --workspace . --import-root <actual-candidate-import-root> \
  --entrypoint <actual-module:materialize>
python "$SKILL_DIR/scripts/check_runtime_handshake_contract.py" \
  --workspace . --import-root <actual-candidate-import-root> \
  --runtime-argv <the completed runtime.argv command>
python "$SKILL_DIR/scripts/check_public_tests.py" \
  --workspace . --test <each-final-public-test-path>
python "$SKILL_DIR/scripts/check_candidate_tree.py" --workspace .
```

Do not copy these scripts into `candidate/`. The map exposes only frozen
input facts; the materializer campaign checks Candidate-local callable
mechanics; the handshake check starts the Candidate command and compares its
public tool projection canonically with the frozen WorldSpec; the tree
preflight checks deterministic project mechanics; the public-test preflight
uses a clean frozen offline environment and direct Python execution, matching
the public-test boundary. None decides business semantics or replaces
Integration or Judge.


Inspect the final inventory for accidental Builder-only paths and derived
debris. Return `completed` only when the final tree, tests, preflight, and full
completion declaration agree. If capabilities are genuinely absent or frozen
inputs are mutually impossible, return an honest blocked result with one safe
current reason.

These checks are the Code Agent's own development loop. Framework Candidate
validation, Integration, Judge, and release remain independent.

## Continuation and authorized correction

The node Prompt tells you whether this is an initial build, same-session
continuation, fresh draft recovery, or authorized correction.

- A workspace draft is not an Artifact or trusted answer. Inspect it against
  frozen `inputs/`, keep only valid work, and never recover an old thread unless
  the current Prompt explicitly says this is a same-session continuation.
- For an authorized correction, read its disclosure before editing. Repair the
  producing boundary: locate the candidate boundary that can produce each
  stated failure, preserve unrelated working behavior and public tests, rerun
  the disclosed boundary and affected checks, then return a full replacement
  `CandidateCompletion`, never a patch.
- When feedback conflicts with frozen inputs or cannot be satisfied without
  breaking another frozen rule, do not disguise the contradiction with a test
  workaround. Return an honest blocked completion rather than a test-only
  workaround, with the smallest safe explanation.

Return only the requested `CandidateCompletion` JSON. Do not create Candidate,
Judge, package, SBOM, validation, or release Artifacts; framework code derives
them after inspecting the physical project. Before returning a blocked result,
load the completion reference: the Provider's strict transport envelope needs
all top-level fields even though only `schema_version`, `status`, and
`blocking_reason` carry blocked semantics.
