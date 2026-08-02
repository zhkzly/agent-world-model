---
name: agent-world-agent-view-stewardship
description: "Curate the compact project-execution Agent view for this repository: current-task orientation, index/path navigation, and safe observe-scene pointers. Use only when a Code Agent repeatedly loses orientation or must broadly search because the top-level view is stale, missing, or too broad; do not use it to design runtime Agent prompts, context, tools, or permissions."
---

# Project-Execution Agent View Stewardship

This Skill designs navigation for the Agent changing this repository. It is not
a Runtime Agent profile, Prompt, Skill, permission system, or runtime feedback
surface. A path tells the project Agent where to read; it grants no authority.

## Establish a real view gap first

Do not change an index or hook merely because debugging is hard. State:

> The project Agent needed to decide … . Its top-level view showed … . It
> could not choose between … without broad search. The smallest missing
> orientation is … .

If one direct read resolves a one-off case, leave the view unchanged. Otherwise
read [references/view-design.md](references/view-design.md) to choose the
smallest replaceable path-map change.

## Keep the two layers small

Session start may give current task, workflow/status, a current scene pointer,
and a small path map. Per user turn gives only current workflow state and, if
needed, one current safe scene pointer. Do not turn hook output into history,
raw logs, prompts, Provider material, secrets, or evaluator-only data.

Use actual registered platform hooks. A new hook requires a demonstrated
orientation gap; it is a refresh trigger, not persistent memory.

## Verify navigation, not runtime behavior

Read [references/view-verification.md](references/view-verification.md) after
a view change. Hand execution choice to agent-world-real-execution-proof.
Return to agent-world-debugging for failure attribution and to
agent-world-llm-remediation only after a runtime Agent/LLM hypothesis remains
live.
