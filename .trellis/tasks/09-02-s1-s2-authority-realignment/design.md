# S1/S2 Authority Realignment — Technical Design

## 1. Design decision

Adopt a clean-break `EnvironmentRelease/3` and remove release-local
TaskSemantics, CapabilitySpecs, qualification goals, positive/noop Task cases
and the peer Native Auditor from S1 publication authority.

S1 publishes an executable world. S2 proposes and admits Tasks against that
world. A Task has one sealed semantic authority: its immutable TaskContract and
checker project. Independent Agents may challenge that authority and force a
new candidate version, but cannot create a second peer truth program or mutate
an admitted contract.

This design changes stable product intent as explicitly authorized by the user.
It supports no old release reader, conversion path, feature flag or dual
runtime.

## 2. Why the current design fails

The current authority chain is:

```text
Need / Research
-> LLM Expected TaskSemantics prose
-> LLM TaskSemantics program
-> independent LLM Native Auditor program
-> LLM public Qualification episode
-> compare peer booleans
-> all-capability Environment publication
```

The first unsupported edge is Expected Semantics prose -> executable truth.
Phrases such as "unrelated state remains unchanged" do not define exact state
projections, accepted outcomes, branch-specific answers or noop predicates.
Peer readers can therefore disagree without either violating their visible
input. Agreement is also only shared interpretation, not external truth.

The stopped campaign confirms the issue across domains: actor construction and
public-surface freeze repeatedly passed, while release yield stayed zero and
logical Qualification dominated terminal failures.

## 3. Authority map

| Artifact or decision | Sole owner |
| --- | --- |
| Need text and Development Brief | User + S1 Research result |
| Actor code and environment-specific state snapshot | S1 Builder project |
| Environment build/conformance/publication verdict | deterministic S1 Framework |
| Candidate Task proposal | S2 proposal Agent; proposal only |
| Task semantic truth | one sealed S2 TaskContract/checker project |
| Real before/after facts | exact EnvironmentRelease state snapshot runtime |
| Task admission | deterministic S2 Framework over physical evidence |
| Difficulty/assessment/corpus policy | downstream S2 records, identity-separated |
| Episode reward | S3 checker execution; never S1 |

## 4. EnvironmentRelease/3

### 4.1 Actor project interface

One standalone actor uv project owns two mechanically separated entrypoints in
the same frozen project identity:

```python
make_environment(instance_directory) -> Environment
read_state(instance_directory) -> JSONValue
```

`Environment` retains the existing public interface:

```text
reset(start)
tools()
invoke(tool_name, arguments)
close()
```

`read_state` is protected and task-neutral:

- it reads the real persistent instance after close/reopen;
- it returns a canonical, environment-specific state projection described by
  `docs/schemas/state.json`;
- it is deterministic for unchanged bytes;
- Framework proves that calling it does not mutate the instance;
- it is never exposed to a public acting policy;
- it contains state facts, not capabilities, Tasks, rewards or success
  predicates.

Using one actor project avoids recreating a second semantic author. The world is
defined by the executable actor and its persistent bytes; protected state
readback makes that world observable to later Task checkers.

### 4.2 Release payload

The v3 payload contains only:

```text
release.json
payload-manifest.json
actor/
conformance/receipt.json
conformance/evidence/
docs/schemas/start.json
docs/schemas/reset.json
docs/schemas/state.json
dist/
licenses/
```

The descriptor binds:

```text
format/canonicalization/hash
payload manifest + digest
actor project + digest + public factory + protected state reader
start/reset/state schemas
conformance receipt + digest
```

It contains no semantics project, expected-task-semantics, capability catalog,
qualified StartCases, task goals, verifier project or task-case evidence.

### 4.3 S1 conformance

S1 conformance is environment-level and domain-neutral. It verifies:

1. exact actor source/lock/build/test identity;
2. source/capability scanning and prohibited imports/artifacts;
3. public ToolSpec and reset/start/state schemas;
4. real factory startup in a clean locked runtime;
5. reset result and every observed invocation against sealed schemas;
6. deterministic reset and state snapshot under the release's declared replay
   profile;
7. close/reopen persistence;
8. instance isolation and protected readback no-mutation;
9. package layout, modes, hashes, ZIP relocation and cold preparation.

Environment-specific project tests remain necessary conformance evidence but
cannot write the Host receipt. A fresh read-only code/behavior review may reject
the candidate, but its prose is not the receipt and it cannot define Tasks.

S1 does not claim that every imagined downstream Task is valid. It claims that
the released executable world and its declared interfaces satisfy the frozen
Development Brief and physical conformance evidence.

### 4.4 Independent Need-semantic qualification

The claim in the preceding paragraph requires a separate post-build semantic
review. Builder-authored tests and diagnostic expectations are inputs to
physical execution, never semantic authority.

```text
frozen BuilderProjection requirements
+ public ToolSpecs
+ Host-executed diagnostic reset/step evidence
+ protected before/after state
-> fresh evidence reviewer
-> one cited finding per Requirement
-> Framework-derived pass/fail
```

The reviewer sees no Builder source, test assertions, expected_ok/state_effect
declarations, Task/checker/witness data, release verdict or prior conversation.
It may cite only Host-assigned evidence references. Tool descriptions and
`ok=true` are not proof; missing evidence and unverifiable relations fail.

Its output contains only `requirement_id`, `verdict`, `evidence_refs` and
`reason`. Framework owns exact-ID coverage, reference validity, digests and the
aggregate verdict. One same-session correction is allowed only for malformed
output. Semantic failures are returned together to the still-open Builder
session; the reviewer never edits code or relaxes requirements.

The historical 20 EnvironmentRelease/3 artifacts remain immutable as the
physical-conformance-only comparison cohort. Newly qualified releases use new
identities and a new experiment root; no old artifact is rewritten.

## 5. Prepared release/session boundary

`prepare_release` materializes one actor runtime, not actor + semantics.

```text
OpenPreparedRelease
  identity: format/release/actor/state-schema digests
  open_session(instance_root)
    public: ActorProxy(reset/tools/invoke/close)
    protected: StateSnapshotProxy(read after close/reopen)
```

The public proxy is the only object an acting policy can reach. The protected
snapshot proxy is held by the Host/checker path. Session/cold-read events keep
the two access paths physically and structurally distinct.

## 6. S2 Direct proposal path

S2 no longer enumerates release-sealed CapabilitySpecs. Its one required Direct
path is:

```text
Need + Development Brief + public ToolSpecs + fresh reset
-> proposal Agent explores one fresh public instance
-> successful/refusal trace + protected before/after snapshots
-> CandidateTaskContract
-> isolated checker author writes one task-specific checker project
-> Framework freezes TaskContract + checker + instruction
-> checker challenges on proposal evidence and physical negatives
-> two fresh public-only witness episodes
-> close/reopen + checker execution
-> TaskPack / TaskAssessment / CorpusManifest
```

The proposal Agent may plan a Need-relevant goal and execute it or derive a
candidate from a successful exploration. This is one Direct mechanism, not a
required Graph/Programmatic product taxonomy.

## 7. Single Task semantic authority

### 7.1 TaskContract

One TaskContract binds:

- exact release and Development-Brief identities;
- reset materialization identity (protected; not an acting hint);
- public instruction and public descriptor;
- final-answer JSON schema;
- checker project/factory/digest;
- evidence obligations and admitted challenge categories;
- contract version and provenance.

The checker is task-specific Python code with a small fixed interface over:

```text
before_state
after_state
public trace
final_answer
```

It returns typed axes such as satisfied, answer, required effects, forbidden
effects and process evidence. The checker may accept multiple valid paths and
outcomes; it never compares the acting trajectory with a reference trajectory.

This avoids a universal verifier DSL while preserving executable, reviewable
truth. The checker author is the sole code author for that Task's semantic
predicate. A challenger can only reject it; a correction creates a new
candidate contract and digest before witnesses run.

### 7.2 Truth and anti-self-verification

- The proposal trace proves candidate existence, not admission.
- Checker and instruction freeze before fresh witnesses.
- Real state snapshots come from the release runtime, not checker-authored
  facts.
- Framework supplies no expected answer to public witnesses.
- Admission requires fresh replay and at least the applicable no-op,
  wrong-answer, wrong-target, partial or collateral challenge.
- If a trustworthy negative cannot be constructed, the contract declares the
  missing obligation and admission abstains rather than fabricating evidence.
- A failed Task candidate never invalidates or mutates the Release.

## 8. Reuse, rewrite and deletion

### Retain

- Research Agent and Search/Read evidence flow;
- actor Builder and runtime Skill, after adding protected state readback;
- ToolSpec/ToolObservation and public Agent loop;
- project identity, uv locks, source scanner and subprocess transport;
- artifact/package manifest, ZIP/mode/hash and cold relocation utilities;
- TaskPack/assessment/corpus identity separation where independent of old
  release semantics;
- S3 public trajectory and close/reopen concepts after later adaptation.

### Rewrite

- `generation.py` S1 stage order and terminal ownership;
- `release.py` descriptor/publication/verification as v3 only;
- `preparation.py` as actor + protected snapshot, without semantics runtime;
- `task_foundry.py` candidate/compiler/checker path;
- S2 challenge/evidence functions that call release-local `evaluate_atom`;
- fixtures and authority tests around current v2 releases.

### Delete from production authority

- `semantics_authoring.py`, `semantics_inputs.py`, `semantics_wire.py`;
- `semantics_author.py` and task-semantics runtime Skill/contract;
- `verifier_author.py`, verifier inputs and verifier runtime Skill/contract;
- S1 task-case `qualification_runner.py`, `qualification_v2.py` and
  task-specific qualification contracts after v3 replacements land;
- release-sealed CapabilitySpec/Condition/StartCase/task-goal fields;
- `TrustedProxy` and semantics child runtime;
- old v2 readers, conversion helpers and compatibility tests.

Generic semantic datatypes in `semantics.py` survive only if the new per-Task
checker contract actually consumes them; otherwise they are deleted rather
than retained by name.

## 9. Cutover and branch strategy

After final planning approval, create branch/worktree
`s1-s2-authority-realignment` from `ef9aad8`. Campaign artifacts remain outside
the repository and all stopped campaign identities stay immutable.

New implementation can be developed behind internal module names, but there is
only one public release/preparation API at each checkpoint. The v3 cutover
commit atomically replaces v2; no flag selects old/new behavior.

## 10. Safety and review gates

At each checkpoint, review against:

- stable product intent and this PRD;
- S1/S2 authority matrix;
- old production reference count;
- net production LOC and largest-file growth;
- real physical evidence, not fixture-only green;
- no domain literals, compatibility readers or new workflow framework;
- no Task/checker/reward bytes in S1 Release;
- no protected state in public policy input;
- no peer reader or witness result defining Task truth.
