# Checkpoint C production Qualification runner evidence

`agent_env_foundry.qualification_runner.run_v2_qualification` now owns the
pre-publication physical matrix. It consumes one frozen Core and uses only the
shared actor/semantics/verifier runtimes, public Responses Agent, native reader
comparison and existing evidence sealer.

Final real SQLite run:

```text
Core ID       7ea84d9cc9ab4112aa77dc9477867e947fde4dee3292eb073b7762f23bda3c2b
cases         18
mutants       2 executable result-axis mutants
capabilities  CAP-001, CAP-002, CAP-003
StartCases    fresh, with-existing-dispute
```

The returned `QualificationReport` fed the existing Publisher directly. The
final directory, ZIP, cold audit and relocated preparation all resolved to:

```text
Release ID 69af4d4c20313d03f5de61489081c05493d5c7dceab206288c2a54920c3a67db
```

The run used the repository API rather than the former `/tmp` domain case
orchestration. Framework source contains no ocean/SQLite/domain field branch.
Lock, Ruff, format, strict Mypy, 326 Pytests, diff check and the runner mutation
licence passed.

This closes the production API portion of Checkpoint C for the SQLite vertical.
The unchanged filesystem/Git repeat and direct S1 coordinator remain open.
