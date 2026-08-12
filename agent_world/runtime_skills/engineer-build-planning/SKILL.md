---
name: engineer-build-planning
description: Advise a bounded implementation plan for a frozen environment design.
---

Read only `design.json` and the identical `implementation-contract.json` supplied
to CandidateBuild. Consume every public world, shared-tool, local-tool, world-rule,
curriculum family, executable-task, Materializer, and five-operation Runtime contract;
never assume a singleton family or tool. Return exactly:

```json
{"steps":[{"goal":"...","suggested_paths":["runtime.py"],"contract_sections":["runtime"],"self_check":"..."}],"risks":["..."]}
```

Use 1–12 steps and 0–8 risks. Suggested paths must be safe relative paths and
each contract section must be named in the supplied contract. This is advisory:
do not write candidate source or claim validation, hashes, admission, Judge, or
release facts.
