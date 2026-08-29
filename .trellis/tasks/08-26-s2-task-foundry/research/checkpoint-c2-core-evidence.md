# Checkpoint C2 Core and three-runtime evidence

## Real author lineage

```text
actor digest       65ad8443b5a24ec908703d85404d61c8ab73c1aa6e9e4656788a187c139650ac
expected digest    8dddc9abc05329f8fb7e91763fff0e83ebaf14eb56a03a8bebf1556d48903819
surface digest     a7bcf88d4aa16685d646fda90b4da37a0fa5bec0a62ea7127972b8f27d440e9d
semantics digest   82b7997ee4a6da2263da3452ad7e190834b4c613a9beeb228dc1727940230c18
verifier digest    a9784a74ec963d962a5b11c8b891d270863c8792faa1ba9a06e11fbeeddeeb0e
Core ID            7539278ae9c6f7ef03c62aa4c74d645315d8409b9caa8e106477cf7141fedf29
```

The fresh TaskSemantics Author workspace is
`/tmp/foundry-s2-c2-semantics-s1ah_3zw/semantics`; thread
`01a04c3c-60e0-7861-b851-9ccf665441a1` passed source, lock, sync,
import-separation, build, three generated tests and frozen catalog/StartCase
checks.

The current Core materialization is under
`/tmp/foundry-s2-c2-core-cdziw3hj`. It uses three distinct interpreters and the
exact matrix:

```text
actor     denies semantics, verifier, Host
semantics denies actor, verifier, Host
verifier  denies actor, semantics, Host
```

## Causal bindings

- Both typed Author attestations recheck immutable 0444 Expected/Public/contract
  files and 0555 manifested actor views.
- Both exact Expected/Public payloads equal the Core inputs byte-for-byte.
- Both actor-view file tuples bind the same actor project digest.
- Attestation roots equal the corresponding generated project roots.
- Core derivation recomputes all three path/mode/content project identities.
- No Release ID, evidence, receipt or verdict enters the Core preimage.

## Fail-closed boundaries

- Wrong factories/modules/roles or weakened import denial reject.
- Equal or nested project roots reject.
- Cache/source equality and either containment direction reject before mkdir.
- Changed source rejects before Core or by the role-owned materializer after Core.
- Alternative in-memory Expected/Public data cannot bind unchanged Author projects.

Two independent reviewers returned `ALLOW`. This is not physical Qualification:
no public case runner, cross-reader axis comparison, negatives, evidence,
receipt, Publication, cold replay, released environment or S2 Task exists yet.
