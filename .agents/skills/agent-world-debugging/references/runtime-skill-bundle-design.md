# Runtime Skill Bundle Design

Use this only after the five-lens attribution has made a runtime Codex Agent's
Skill a live repair surface. It is not permission to turn every recurring
failure into more instructions.

## Identify the recipient first

Ask which execution context must learn the method:

- A Direct LLM gets model + rendered Prompt/input + authorized correction
  feedback. It never receives a Runtime Skill, bundled reference, script,
  workspace method, Hook, or tool instruction.
- A runtime Codex Agent gets one node-specific Skill bundle plus its Prompt,
  authorized feedback, workspace, and granted tools.
- The project-execution Agent changing this repository uses `.agents/skills/`;
  those Skills guide investigation and development, not generated environment
  behavior.

If the intended recipient is unclear, do not edit a Skill yet.

## Make one progressively disclosed bundle

One runtime node owns one method bundle:

- `SKILL.md` contains the trigger, authority boundary, core workflow, stop
  conditions, and links to details.
- One-level `references/` contains protocols, domain detail, examples, and
  phase-specific checklists that are not needed on every turn.
- `scripts/` contains only repeated deterministic mechanics whose stable
  output is more reliable and smaller than re-deriving them in prose.
- `assets/` contains templates or files the Agent reuses in its output, not
  more instructions.

Do not mount several always-active Skills merely to split one node's chapters.
Do not copy reference text into the node Prompt. Keep paths relative to the
bundle and make the navigation say exactly when each reference or script is
needed.

## Decide whether a script is justified

Before adding a script or deterministic check, ask:

1. What repeatable mechanical harm does it catch?
2. Is the rule already owned by the real framework boundary?
3. Would better Prompt text, Skill method, feedback, or Agent self-check solve
   the problem without forbidding valid strategies?
4. Does the script mirror the authoritative contract, or invent a stricter
   one from one failed sample?
5. Can its output identify an exact path, expected condition, and actual value
   for the Code Agent?

Reuse the project's real observer, validator, package manager, and test
commands instead of creating a second implementation. A script may check
project mechanics such as required files, lock consistency, forbidden private
paths, or declaration closure. It must not decide business semantics, claim
Integration/Judge success, choose a license, weaken tests, or manufacture
Artifacts.

## Bind and prove the complete bundle

Profile materialization and semantic implementation revision must hash the
entire bundle closure, including references, scripts, assets, and executable
bits. A changed reference that leaves a committed Agent result current is a
control-plane defect.

Validate in this order:

1. Run the official Skill package validator.
2. Run a true subprocess test for each bundled script with both passing and
   poisoned constructed inputs.
3. Run deterministic regressions for profile discovery, full-bundle hashing,
   Prompt/Skill separation, and feedback routing.
4. Run one real isolated Codex Agent node with the actual mounted bundle and
   granted tools.
5. Inspect the Agent's own tests/preflight and framework terminal separately.
6. Only after that node passes, run its immediate Integration boundary and
   then the wider chain.

pytest and package validation prove structure and mechanics only. They do not
prove the runtime Agent read the Skill, used its tools, completed its internal
engineering loop, or produced an Integratable Candidate.

## Evolve from evidence without accumulating prose

When a new bad case reveals a reusable method:

- add the smallest general method at the layer that owns it;
- audit homologous active Skills, Prompts, feedback, scripts, and validators;
- replace obsolete guidance instead of appending chronological lessons;
- keep `SKILL.md` compact and move detail into an existing or new reference;
- remove a rule when real evidence shows it forbids valid behavior.

Record the bad case and proof in task/spec evidence, but write the Skill as a
current operating method, not a history log.
