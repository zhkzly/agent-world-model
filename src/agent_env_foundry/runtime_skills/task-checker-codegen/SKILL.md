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
   `passed` must be their conjunction. A collateral near miss must keep the
   required effect true while forbidden-effects becomes false: do not place
   "no extra change", exact total-count, or "must be final" constraints inside
   required/process when those constraints belong to forbidden-effects.
5. Accept alternative valid tool sequences and irrelevant ordering differences.
6. Do not turn one proposal serialization into a hidden answer rule. If the
   public schema permits multiple representations and the instruction/checker
   brief does not distinguish them, accept them and test at least one
   schema-valid alternative positive representation.
7. Add positive and discriminating negative tests, run the project commands,
   and repair all factual failures. Framework checks—not your final response—
   determine acceptance.

Do not access actor code/runtime, hidden files, network, LLMs, wall clock or
randomness. Do not create rewards, witnesses, Tasks, TaskPacks or receipts.
