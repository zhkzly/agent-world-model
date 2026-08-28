# Qualification Codegen and Debugging Contract

## 1. Scope / Trigger

Use this contract when an independently generated S1 Qualifier is rejected or
when a public/native assertion appears to implicate the Candidate. The stable
goal is to distinguish Candidate behavior from Qualifier-code, Framework and
Infrastructure defects without adding a domain branch or weakening release
requirements.

For EnvironmentRelease v2, also use it before Semantics Authoring: a fresh typed
turn freezes expected TaskSemantics from accepted Need/Requirement relations
before any Candidate/native/source view is staged.

## 2. Signatures

Codex authors exactly three semantic programs:

```text
public_probe.py:    run(session, mode)
negative_setup.py:  python negative_setup.py RELEASE_ROOT INSTANCE_ROOT DECLARATIONS_PATH
native_probe.py:    python native_probe.py RUNTIME_ROOT EVIDENCE_JSONL NEGATIVE_JSONL
```

Framework-owned artifacts and calls:

```text
probe_manifest.json                         # Host-created only
HostJournal(run_id, ordered events, digest) # Host-created only
feedback = REJECTED + ALL_FINDINGS + REPAIR + RESUBMIT
```

```python
freeze_expected_task_semantics(
    projection: BuilderProjection,
    document: Mapping[str, Any],
) -> ExpectedTaskSemantics

generate_expected_task_semantics(
    projection: BuilderProjection,
    *,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
) -> ExpectedTaskSemantics
```

## 3. Contracts

- Codex owns tool sequences, native-reader queries, business assertions,
  assertion-to-obligation coverage and semantic near-miss code.
- Framework owns workspaces, IDs, digests, manifests, controlled copies,
  subprocess execution, journals, evidence enrichment, coverage aggregation,
  error ownership and verdict.
- Models never transcribe SHA-256 values, manifest records, relation/predicate
  bindings or complete journal calls. Evidence selects Host invoke events by
  sequence number; Host injects the canonical call bytes.
- Feedback reports all currently observable failures, not the first one. Every
  finding includes its location/Requirement, actual value, expected value and
  an executable repair condition. Every repair reruns the complete gate.
- Positive ToolObservation has `error=null`; refusal has `data=null`. Readers
  use `(observation.get("error") or {})`, not chained `.get` on a nullable value.
- Positive instances live directly under `runtime/baseline-instances`; negative
  instances live under `runtime/negative-runs/<run>/instances`. Native readers
  select an explicit instance name and never use an ambiguous first `rglob` hit.
- A physical near miss changes a pre-existing file in the controlled release
  copy and changes at least one observation for a matching tool-name/arguments
  call. Added marker files and declaration-driven Boolean flips are invalid.
- Stateful checks use the correct temporal instance: preserve lifecycle state
  for reload/history checks; use separate reset/refusal/isolation instances when
  later actions would erase the earlier evidence.
- Loader dependencies prepare from the local uv cache with `--offline`; cache
  absence is Infrastructure, never a request for Codex to change semantics.
- Expected-semantics input contains only frozen Need, selected world, Requirements,
  initial-world relations and the Host contract. Cited source revisions, Candidate
  bytes/native fields, Tasks, traces, answers and verdicts are absent.
- Every Requirement is dispositioned exactly once. Capabilities reference only
  Taskable Requirements and licensed workflows; composition and conditions carry
  explicit Requirement/workflow/capability anchors.
- Model output never carries a Host digest. Host sorts set-like records, RFC 8785
  canonicalizes the accepted document and computes its SHA-256 digest.
- Semantic validation reports all currently observable findings in one replacement
  turn. Strict JSON-schema rejection remains fail-closed.

## 4. Validation & Error Matrix

| First deviation | Owner | Required action |
| --- | --- | --- |
| Original baseline loader/runtime exits canonically | Candidate | factual Builder feedback |
| Controlled mutated copy violates the base contract | Qualifier | repair near-miss code |
| Assertion fails before its extraction logic is validated | Qualifier first | return decisive Host events and rerun |
| Qualifier keeps the same assertion after actionable feedback | unresolved Candidate/Qualifier boundary | fail closed; inspect evidence, never patch Candidate blindly |
| Model writes manifest/digest/journal copies | Qualifier contract | reject; Host recreates nothing silently |
| Only new marker bytes change | Qualifier | reject `negative_physical_noop` |
| Matching public observations remain identical | Qualifier | reject `negative_public_behavior_unchanged` |
| Provider capacity/network or missing offline cache | Infrastructure | retry identical bytes or end `NotReleased` |
| Expected Requirement omitted or added | expected semantics | reject exact coverage mismatch |
| Capability cites non-Taskable/unknown Requirement or workflow | expected semantics | reject with field path |
| Composition/condition cites unknown or unlicensed anchors | expected semantics | reject all observable findings together |
| Local TCP denied before provider request | Infrastructure | rerun identical command with permitted localhost access |

## 5. Good / Base / Bad Cases

- Good: `negative_setup.py` changes an existing source/data member; the copied
  release still loads; the same public call returns a different observation;
  the same assertion ID/expected/coverage changes from true to false.
- Base: baseline calls and native state satisfy all frozen relations, and Host
  binds the model-selected call sequences into evidence.
- Bad: native code writes `passed=false` because a marker/declaration names the
  Requirement, or checks final global count zero after earlier valid mutations.
- Bad: a reset test destroys lifecycle history in the same instance and the
  verifier then interprets the final post-reset database as pre-reset evidence.
- Bad: a substring scanner treats a controlled source path as a Candidate
  import. Import separation is checked from Python AST imports.
- Good: a fresh typed turn sees four accepted S1 relations, returns four
  dispositions and three capabilities, and Host freezes the canonical digest.
- Bad: forward `cited_evidence`, Candidate source, native field names or a Host
  digest into the expectation turn.

## 6. Tests Required

- Model-authored `probe_manifest.json` is rejected; Host manifest binds exact
  source bytes and is checked before/after execution.
- Evidence rows cannot copy digests or calls and must reference real Host invoke
  sequence numbers.
- Twenty-four simultaneous assertion failures appear in one feedback packet.
- Negative assertion matches the baseline assertion ID, expected fact and
  coverage, while actual behavior differs.
- Added-marker-only and unchanged-public-behavior negatives are rejected.
- Baseline exit 20 attributes Candidate; controlled-copy exit 20 attributes
  Qualifier.
- Source path strings are allowed in negative setup, while actual Candidate
  imports are rejected by AST inspection.
- Full real run proves 24/24 positive, 24/24 negative, stable Candidate digest
  and a content-derived evidence digest.
- Expected semantics tests use non-empty composition and condition records; kill
  coverage, Taskable completeness, unknown-reference, ordering, leakage,
  all-findings and provider-schema mutants.
- Run at least one real strict-JSON provider turn from accepted S1 relations; a
  fake client proves transport shape only.

## 7. Wrong vs Correct

Wrong:

```text
invalid manifest
retry the same request
```

Correct:

```text
REJECTED: negative_assertion_mismatch
ALL_FINDINGS: every affected requirement with actual/expected Host evidence
REPAIR: edit all three current programs, preserve passed invariants, fix all findings
RESUBMIT: end the turn after writing complete code; Framework reruns every gate
```

Wrong:

```text
Candidate source + native fields -> model decides which Requirements are taskable
```

Correct:

```text
accepted Need/Requirements -> fresh typed expectation -> Host freeze
-> only then stage public surface and read-only Candidate view for Semantics Author
```
