# S2 TaskAssessment and CorpusManifest

## Scope

This layer starts only after TaskPack admission. It measures an acting policy
and selects a corpus; it never changes Task meaning, checker truth, admission
evidence, EnvironmentRelease qualification, or scalar training reward.

## TaskAssessment

Each assessment binds:

```text
TaskPack ID
EnvironmentRelease ID
Goal kind
model + route + public Agent prompt policy
ordered fresh trial results
```

Every trial opens a fresh materialization and runs the exact admitted public
instruction through the ordinary public tool loop. Checker failure and
`NoPublicWitness` are recorded as model-relative failures. Environment,
infrastructure, binding, condition or checker drift remains a typed upstream
error and must not be counted as model difficulty.

Admission witnesses are not assessment trials. Assessment reports empirical
reliability, provider turns, tokens, latency, failure codes and a structured
difficulty summary. These values do not enter TaskPack identity.

## CorpusManifest

Corpus selection consumes exact `(TaskPack ID, TaskAssessment ID)` pairs. It:

- applies an explicit purpose and reliability policy;
- removes duplicate structures within one release;
- balances release/Goal buckets deterministically under a seed;
- binds all candidates in selection evidence;
- may select a subset without rejecting the omitted TaskPacks.

Corpus size, Goal distribution and reliability threshold are experiment policy,
not EnvironmentRelease or TaskPack admission gates. A manifest may not point to
an unadmitted TaskPack or to an assessment belonging to another TaskPack.

## Forbidden

- reusing admission witnesses as independent assessment;
- retrying failed trials until only successes remain;
- weakening a checker based on assessment yield;
- copying assessment or corpus identity into TaskPack identity;
- domain-specific selection branches;
- treating a corpus target count as proof of Task validity.
