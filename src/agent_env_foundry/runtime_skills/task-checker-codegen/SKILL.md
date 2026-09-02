---
name: task-checker-codegen
description: Author one pure task-specific checker from a frozen candidate and real proposal evidence.
---

# Task Checker Code Generation

1. Read `CANDIDATE_TASK_CONTRACT.json`, `PROPOSAL_EVIDENCE.json`, and
   `TASK_CHECKER_CONTRACT.md` completely. Never edit them.
2. Translate the protected `checker_brief` into explicit ordinary Python over
   before state, after state, public trace, and final answer.
3. Use proposal evidence to understand concrete state shape and one feasible
   execution, but do not compare future traces with that proposal.
4. Keep required effects, forbidden effects, answer and process axes separate;
   `passed` must be their conjunction.
5. Accept alternative valid tool sequences and irrelevant ordering differences.
6. Add a positive, no-op and wrong-answer test plus ordinary semantic unit
   tests appropriate to this task. Run the project commands,
   and repair all factual failures. Framework checks—not your final response—
   determine acceptance.

Do not access actor code/runtime, hidden files, network, LLMs, wall clock or
randomness. Do not create rewards, witnesses, Tasks, TaskPacks or receipts.
