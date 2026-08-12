# Research: cross-layer review dec00ffe

- Query: Fresh independent Direct R9-C3 review of the documented trusted-wheel
  ingestion correction.
- Scope: internal
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`, model `gpt-5.6-terra`

## Decision

Decision: allow

- Plan digest: `dec00ffe10140fb81258182347f658a0370dfdb5155f8344ed8fbc0b8751e372`.
- Parent digest: `d39632e88ff13a1b447e490beb379540fe22dcb839690cfdbf6138f114d1efe5`.
- Plan revision: Direct R9-C3, revision 1 of the trusted-wheel ingestion
  lineage.
- Scope classification: coordinated Direct installer boundary only; no graph,
  owner, package ABI, Repair, Expand or Consumer behavior change.
- Trigger: static pre-execution plan contradiction. No Observe scene or
  Diagnosis Record applies.

The reviewer independently recomputed the five-file digest and obtained the
declared value.

## Product Target And Impact Chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in a
real isolated boundary, publish an immutable Registry `EnvironmentPackage`,
and expose only safe facts through Observe.

```text
framework trusted wheel store
  -> lock hash/size verification
  -> empty run-local verified flat directory
  -> uv --offline --no-index --find-links
  -> fresh external venv / isolated candidate execution
  -> Integration -> Judge -> Package -> Registry -> Observe
```

The correction makes locked third-party wheel installation executable without
granting CandidateBuild or candidate code registry, build, index, dependency
selection or release authority.

## Owners And Compatibility

- Framework remains the sole lock admission and installer owner. It verifies
  selected wheel bytes, creates the local directory, supplies fixed argv and
  keeps uv's separate run-local cache opaque.
- CandidateBuild supplies only source and lock metadata. Candidate and ambient
  configuration cannot add an index, source, find-links path or fallback.
- Runtime, Judge, Registry, Repair, Expand and Consumer gain no dependency or
  release authority. Direct package closure and Registry cold-read contracts
  are unchanged; later children consume exact released-package facts only.
- Official uv CLI semantics support a local flat distribution directory through
  `--find-links` paired with `--no-index`; direct cache modification is unsafe.
  The plan therefore uses the documented input boundary rather than inventing
  uv cache internals.

The current implementation is intentionally pre-change: its old installer has
no trusted-store parameter and lacks these fixed arguments. This allow permits
replacement only within the written C3 boundary.

## Smallest Allowed Implementation And Proof

1. Implement framework-only lock/wheel verification, copy admitted wheels into
   one empty run-local flat directory and pass exactly
   `--no-index --find-links <verified-dir>` plus a distinct cache.
2. Preserve rejection before uv/candidate execution for build backends, sdists,
   indexes, Git/URL/path/editable/local sources, missing/mismatched wheels and
   source/lock mutation.
3. Deterministically prove exact argv/environment, ambient scrubbing,
   hash/size verification, hostile rejection and one valid locked-wheel install
   into a fresh external venv without installing or mutating candidate root.
4. Run the approved CandidateBuild/Integration boundary proof, then the fresh
   non-fixture Direct-to-Registry proof, reading Observe after each terminal.

## Non-Claims And Next Gate

This allow does not prove implementation, installation, candidate execution,
Direct E2E, Repair, Expand, Consumer/SFT/RL or complete-v1. It does not
authorize cache mutation, a downloader, index client, dependency configuration
platform, network/build fallback or changed trust boundary.

Next permitted gate: add this matching allow and the parent C3 allow to
implementation/check context, then dispatch the bounded implementation. Any
digest, installer-boundary or real-scene change expires this allow.
