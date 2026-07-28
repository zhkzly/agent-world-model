---
name: agent-world-agent-view-stewardship
description: "Curate the project-execution Agent view for this repository: current-task orientation, index.md-style navigation, observe-scene summaries, and absolute or repo-relative paths for on-demand reads. Use when a Code Agent working on the project repeatedly loses orientation or must broadly search for relevant files. Keep the top-level view compact, current, and non-accumulative; this Skill does not design runtime role-Agent prompts, context, or permissions."
---

# Project-Execution Agent View Stewardship

Use this Skill for the Agent that is executing, debugging, or changing this
repository. Its view is the project-facing orientation assembled from items
such as the active task, a compact observe scene, a project index, and injected
hook context.

This is **not** a Runtime Agent profile, a role Prompt, a Runtime Skill, or a
runtime permission design. Diagnose those separately through
agent-world-llm-remediation only after agent-world-debugging leaves a runtime
Agent/LLM hypothesis live. A real model node alone is not enough. Do not
confuse the project Agent's navigation problem with the runtime model's input
problem.

The project Agent already works in this repository. Resolve the current project
root at invocation time; an absolute path under it and a repository-relative
path are both valid navigation. A path tells the Agent where to read; it does
not grant a new permission.

## Keep evidence and the project view separate

- **Code evidence** is durable: logs, traces, state, artifacts, source, test
  results, and event records. It may accumulate.
- **Project-execution Agent view** is a short, replaceable orientation for the
  current task. It should answer: what is happening, what is known or unknown,
  and which local files can answer the next question.

Keep a small stable index for project topology. Replace attempt-specific scenes
as the investigation moves. Do not append every discovery to an index or hook
payload: history belongs in evidence, while the view carries only the current
decision and useful local paths.

## Establish a real project-view gap first

Do not change an index, scene, or hook merely because an investigation is hard.
Write the evidence in plain language:

> The project Agent needed to decide … . Its top-level project view showed … .
> It could not choose between … and … without broad, unguided repository
> searching. The smallest missing orientation is … .

Then ask:

1. Is the gap recurring, or will one direct read settle this exceptional case?
2. Is the missing thing a current-task status, a relationship, a chronology, or
   a route to a specific file?
3. Is the existing index stale, too broad, or simply missing one useful path?
4. Could a short path map let the Agent reason, rather than inlining a
   conclusion for it?
5. What will be removed or replaced at the next attempt instead of retained?

Leave the view unchanged if there is no demonstrated navigation or orientation
gap.

## Make the top level a path map, not a repository dump

Use progressive disclosure. A useful top-level project view normally contains
only:

~~~text
Project root: <resolved absolute repository root>
Active task: .trellis/tasks/<task-id>/
Current question: why did this boundary reject the candidate?
Known: the model returned; validation rejected two entries.
Unknown: whether the active runtime instruction/input or Runtime Skill
expresses the per-entry rule.

Read on demand:
- .agent-world-live/<attempt>/scene.md — attempt chronology and failure story
- agent_world/designer/... — the active leaf and validator boundary
- agent_world/agent_assets/... — the Runtime Skill loaded by this role
- .trellis/tasks/<task-id>/ — decision record and intended proof
~~~

Each path must say which question it can answer. Prefer a local absolute or
repository-relative path when the current project Agent can resolve it. A
project index may contain a small path map; it should not copy raw logs, whole
prompts, or every prior attempt.

Use URLs only when an external source is actually needed for the project task.
They are not the default substitute for a local path map, and a URL must say
what question it answers.

## Deliver the view in two bounded layers

- **Session start:** inject one replaceable orientation: resolved project root,
  active task directory, workflow/status, current scene pointer when one
  exists, and a small index/path map. This is the top-level view.
- **Per user turn:** inject only the workflow state and, when there is a live
  failed attempt, one short scene pointer. Do not re-inject the session map,
  raw logs, or prior conclusions on every turn.

Use the platform's actual registered hooks, not an orphaned script on disk.
Before wiring a new hook, prove that the project Agent has a real orientation
gap; after wiring it, smoke-test the registered event and inspect its emitted
text. A hook is a refresh trigger, not a persistent memory store.

## Choose the lightest project-view change

Pick the smallest change supported by the gap:

1. Rewrite or trim the current top-level summary so its question, knowns, and
   unknowns are current.
2. Add a brief attempt delta that replaces obsolete status rather than
   accumulating history.
3. Add one absolute or repository-relative path plus the question it answers.
4. Add or correct one stable index entry when the same path relationship is
   repeatedly needed across tasks.
5. Adjust a project hook only when it keeps the active-task summary or path map
   fresh. Use session start for the map and per-turn injection only for a
   current pointer; make each payload replaceable and bounded.
6. Inline a small safe fact or excerpt only when following the path would make
   the live decision ambiguous or disproportionately slow.

Never place secrets, raw provider payloads, or evaluator-only material in the
top-level text merely to make navigation convenient. That is a content-safety
decision, not a reason to mistake paths for authorization.

## Verify a project view without confusing it with runtime testing

This Skill defines what a useful project view should prove; hand execution of
the check to agent-world-real-execution-proof.

Check the smallest applicable claims:

- Referenced paths exist, are current, and answer the question claimed beside
  them.
- A fresh project-execution Agent — one that has not already explored the
  relevant repository area — can read the top level, name its first precise
  reads, and avoid broad repository searching.
- Attempt transitions replace stale summaries instead of growing the injected
  context indefinitely.
- In one real project debugging exercise, the Agent can state a defensible next
  investigation or repair target from the view plus its selected reads.

Do not run a Runtime Agent node merely because an index or hook path map
changed. Run a real runtime-node proof only if a separately changed Prompt,
Runtime Skill, profile, runtime role context, or repair path makes a claim
about runtime behavior.

## Hand back to the correct owner

Return to agent-world-debugging for failure attribution. Use
agent-world-llm-remediation only for an actual runtime Agent/LLM hypothesis.
Use agent-world-real-execution-proof to select and run the appropriate project
view check, node proof, repair proof, integration, or E2E proof.
