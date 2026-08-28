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

The Host journal records `open` before handle calls, followed by `reset`,
`tools`, `invoke`, and `close`. A closed wrapper is permanently unusable and
one instance name may have only one active wrapper, so a fresh factory
reattachment cannot be confused with a stale handle.

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

run_semantics_author(
    prepared: PreparedSemanticsAuthorWorkspace,
    *,
    config: BuilderConfig | None = None,
) -> SemanticsBuild
```

## 3. Contracts

- Codex owns tool sequences, native-reader queries, business assertions and
  semantic near-miss code.
- Framework owns workspaces, IDs, digests, manifests, controlled copies,
  subprocess execution, journals, evidence enrichment, structural topology,
  error ownership and verdict. Topology proves that a physical check was
  attempted; independent native evidence proves its business meaning.
- Evidence assertions contain exactly `assertion_id`, `passed`, `actual` and
  `expected`. Model-authored coverage labels have no authority.
- Evidence invoke sequences are unique and strictly increasing. Baseline and
  negative calls compare in ordered `(instance, open epoch, reset epoch, tool,
  arguments)` scope; repeated calls are never collapsed into a last-value map.
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
- Production order is `Builder -> expected freeze -> actor Qualification -> Semantics
  Author inputs`. The Author workspace reuses the existing Host journal and the same
  `_stage_view` allowlist; it does not define a second loader or evidence authority.
- The workspace contains exactly the frozen expected semantics, public surface,
  TaskSemantics contract, candidate-view manifest and read-only candidate view. Public
  surface facts omit run IDs and Host digests; the manifest already binds view files.
- Framework creates the fixed `generated_task_semantics.release:make_semantics` uv
  project and owns source scanning, lock/frozen sync, import separation, build, tests,
  catalog alignment and project digest. Codex owns only native decoding, semantic
  records/evaluators, tests and dependency declarations.
- Query capabilities require structured answer fields plus rendering wording. StartCases
  must cover every distinct reset input already demonstrated by Host public facts; case IDs
  alone are not world diversity, and identical seed/limit calls must be byte-equivalent.
- Codex runs in a fresh deny-all/full-access thread. Full access is not trust: every
  immutable input is rechecked after each turn, and model prose is discarded.

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
| Codex imports actor/Host or runtime-references candidate-view | Semantics Author | reject source before lock/build |
| lock/sync/build/tests fail | Semantics Author or Infrastructure from exact command | return all available command facts to same thread |
| generated catalog differs from frozen capability/composition/condition IDs | Semantics Author | reject catalog; model prose cannot override |

## 5. Good / Base / Bad Cases

- Good: `negative_setup.py` changes an existing source/data member; the copied
  release still loads; the same public call returns a different observation;
  the same assertion ID and expected fact change from true to false.
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
- Good: Codex writes one standalone uv project; seven Host gates pass and only project
  digest/thread ID/check evidence survives.
- Bad: Framework writes a domain decoder/evaluator, or Codex writes a pass verdict,
  manifest, digest, Task, reward or witness.

## 6. Tests Required

- Model-authored `probe_manifest.json` is rejected; Host manifest binds exact
  source bytes and is checked before/after execution.
- Evidence rows cannot copy digests or calls and must reference real Host invoke
  sequence numbers.
- Twenty-four simultaneous assertion failures appear in one feedback packet.
- Negative assertion matches the baseline assertion ID and expected fact, while
  actual behavior differs.
- `close -> invoke` on a stale wrapper is a Qualifier defect. Only
  `close -> fresh open(same instance) -> invoke` can attribute a reattachment
  failure to the Candidate.
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
- Semantics Author tests kill full-access, model-self-authorization, actor/Host import,
  catalog-alignment, query-answer, StartCase-coverage, fixed-factory, Skill-ownership and
  API fail-closed mutants.
- A real cross-domain project must pass all seven Framework checks; fake Codex only
  proves orchestration.

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
