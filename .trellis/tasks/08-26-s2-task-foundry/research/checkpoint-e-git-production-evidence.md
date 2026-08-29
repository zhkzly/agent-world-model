# Checkpoint E filesystem/Git production evidence

Date: 2026-08-30

The cross-environment compiler was run only against the cold immutable release:

```text
Release ID  3ee01aedf891592abc14d0039ce65127463eacb5785d7d1014ca9ad50fcfdfde
Core ID     5d185bd11503b7e0f3421329ba75ed66b7134a7029c6ad97a4f3e0512de6377d
Semantics   e92b4db513f585410c6fdfd072cd7c9408cd265c24aec72beccf9be469c6b8b6
Verifier    0720dcf7d203876cf85b80a5547012e09c45a9afb55f755559a0613bf7d316d9
Evidence    f632a71082379a2a47ef3891f5e59a4204e28e448ea615c2fdebe97fe36dbe7c
Receipt     3d604a5cf6d7f44b215ad66bbdc517193088664354befcacc2c9e6d4c76612e9
```

Production Qualification sealed 19 cases and two reader mutants. Directory
verification, audit replay and deterministic ZIP publication passed.

The unchanged compiler produced:

```text
Atom      12
ForEach    4
If         6
Total     22
Starts     git-clean, git-pending_change
```

The implementation changes that made this cross-layer path semantic rather
than domain-specific were each RED/GREEN and mutation-licensed:

- physical task-kind/state-transition agreement;
- strict structured-output AnswerField schemas;
- final answers on every Taskable capability;
- branch-neutral Condition answer contracts;
- abstention rejects only an inapplicable If Blueprint;
- post-witness AgentChoice replay rebinds dynamic report answers without
  changing public witness answers.

Checkpoint F is not claimed. A state Atom attempt reached post-witness challenge
execution, then the configured route returned an upstream 503. The next fresh
attempt returned `auth_unavailable` before witness execution. These are retained
as InfrastructureFailure, not converted into semantic success or a fallback.
