# S1 Environment Foundry — technical design

## 1. Architecture in one sentence

A direct coordinator turns a Need into an evidence-backed Development Brief,
lets the Python Codex SDK author a complete stateful uv project, independently
checks its public calls against native state, and publishes the exact project as
an `EnvironmentRelease` implementing `reset/tools/invoke/close`.

S1 has four product stages—Research, Build, Qualify and Release. Role invocations
inside a stage are not graph nodes or services.

## 2. Cross-stage context contracts

The contracts, not a workflow graph, define the architecture.

### 2.1 Product stages

| Stage | Consumes | Produces | Must not produce |
| --- | --- | --- | --- |
| S1 Environment Foundry | natural-language Need and optional supplied evidence | qualified `EnvironmentRelease` | Task, verifier, reward, trajectory |
| S2 Task Foundry | exact `EnvironmentRelease` | sealed `TaskPack`: Task, start, solvability evidence, truth, verifier/reward material | environment implementation |
| S3 Episode Runtime | `EnvironmentRelease + TaskPack` | verified Episode and attributable Reward | new environment or Task truth |
| S4 Training | verified Episodes | SFT/RL datasets, runs and checkpoints | environment/Task redefinition |

S1 therefore has no reason to know whether S2 uses Graph-based, Programmatic or
another Task candidate algorithm. All S2 algorithms see the same released
environment surface.

### 2.2 S1 internal handoffs

```text
NeedRecord
  -> ResearchBundle {fetched evidence, Development Brief, review}
  -> CandidateProject {complete uv project, candidate identity}
  -> QualificationResult {requirement coverage, public/native evidence}
  -> EnvironmentRelease {runtime project, public contract, release identity}
```

| Handoff | Required content | Deliberately absent |
| --- | --- | --- |
| Research → Builder | original Need, accepted Brief, compact evidence index | table schema, tool schema, candidate code, Task |
| Builder → runner | exact generated project | hidden probes, expected native facts |
| runner → Builder | factual build/call failure and candidate identity | answer-key patch or fallback code |
| candidate → Qualifier | Need/Brief, public API/docs, candidate source, assigned instance directory | Builder chat, Builder tests as authority |
| Qualifier → Release | passing requirement-to-probe result and native evidence | Task/reward claims |
| S1 → S2 | exact release, reset/start contract, ToolSpecs, invoke behavior, public docs, trusted instance access | S1-authored Task, graph or verifier |

## 3. Clean-room implementation shape

The product starts as a new uv/src-layout project:

```text
src/agent_env_foundry/
  api.py             # Need and terminal outcome API
  research.py        # Search/Fetch/Extract and Development Brief
  agents.py          # thin Python Codex SDK invocation adapter
  builder.py         # empty workspace, candidate identity and factual repair
  environment.py     # ToolSpec, Environment protocol and release loader
  qualification.py   # independent probes and native inspection runner
  release.py         # exact artifact assembly, cold use and publication
  runtime_skills/
    research/SKILL.md
    environment_codegen/SKILL.md
tests/
```

This is a responsibility map. A file exists only when its current owner and
consumer require it. There is no graph runtime, workflow engine, custom sandbox,
custom RPC stack, universal state module, Registry service or compatibility
package.

## 4. End-to-end control flow

```python
def generate(request: NeedRequest) -> GenerationOutcome:
    need = freeze_original_request(request)

    research = run_research(need)
    if research.unsupported:
        return Unsupported(research.reason)

    brief_review = review_development_brief(
        need=need,
        fetched_sources=research.sources,
        brief=research.brief,
    )
    if brief_review.requires_research_revision:
        research = revise_research(need, research, brief_review)
    if not brief_review.can_accept:
        return NotReleased("research_fidelity")

    workspace = create_empty_uv_package_workspace()
    builder = start_codex_builder(
        cwd=workspace,
        need=need,
        brief=research.brief,
        evidence_index=research.index,
        environment_contract=CANONICAL_ENVIRONMENT_CONTRACT,
    )

    while generation_budget_remains():
        candidate = builder.author_or_repair()

        execution = build_and_smoke_candidate(candidate)
        if execution.failed:
            builder.send_factual_feedback(execution)
            continue

        qualification = independently_qualify(
            candidate=candidate,
            need=need,
            brief=research.brief,
        )
        if qualification.probe_defect:
            qualification = reauthor_invalid_probe(candidate, need, research.brief)
        if qualification.candidate_defect:
            builder.send_factual_feedback(qualification.public_facts)
            continue
        if not qualification.complete:
            return NotReleased("incomplete_semantic_qualification")

        release = assemble_release(candidate, research.brief, qualification)
        cold = cold_use_release(release)
        if cold.candidate_defect:
            builder.send_factual_feedback(cold.facts)
            continue
        if not cold.passed:
            return NotReleased(cold.reason)

        return publish_exact_release(release, qualification, cold)

    return NotReleased("generation_budget_exhausted")
```

Configured budgets provide termination only. They do not weaken semantic
requirements or authorize a reduced release.

## 5. Research

### 5.1 What Research must learn

The Research Agent investigates only information needed to describe the world
Codex must implement:

- actors, entities and permissions;
- normal public interfaces and workflows;
- successful state transitions and their preconditions;
- business refusals and prohibited side effects;
- time, concurrency and persistence behavior when material;
- realistic initial records/assets and relationships;
- mature libraries and native formats suitable for implementation;
- known failure cases and disputed variants.

Search discovers sources. Fetch retains exact response bytes, final URL, media
type and digest. Extract creates addressable passages from fetched material.
Search snippets and model recollection do not become evidence.

### 5.2 Development Brief

The Research Agent returns a structured draft; host code gives stable
requirement identifiers and renders a readable Brief containing:

- original Need scope;
- selected coherent synthetic-world interpretation;
- atomic Need-clause mapping;
- required capabilities and observable state relations;
- meaningful initial-world requirements;
- successful and refused behavior;
- persistence/time/concurrency invariants where applicable;
- evidence references, assumptions, alternatives and exclusions;
- one falsifiable consequence for each core requirement.

The Brief intentionally omits concrete tools, function names, JSON schemas,
database tables and module layout. Those are Builder design decisions. It also
omits Task, verifier, reward and training concepts.

A fresh Brief reviewer checks evidence binding, omissions, contradictions and
unjustified narrowing. It cannot eliminate ambiguity in an under-specified Need;
the selected interpretation and residual uncertainty remain public.

## 6. Builder and repair

The host performs only domain-free setup:

```text
uv init --package <fresh-workspace>
write NEED.md
write BRIEF.md
write compact evidence index
write ENVIRONMENT_CONTRACT.md
```

It writes no source skeleton, tool stub, schema, database model, seed fixture or
positive environment implementation.

The Python Codex SDK starts one workspace-write thread with the fresh workspace
as `cwd`. The environment-codegen Skill teaches method, not a domain. Codex must
produce:

- complete source and `pyproject.toml`;
- real dependencies and `uv.lock`;
- standard environment factory/entry point;
- `reset`, `tools`, `invoke` and `close`;
- package-owned meaningful default data/assets;
- domain-appropriate native storage;
- input/output schemas and public documentation;
- diagnostic tests.

The host runs real lock, install, build, import and API smoke commands. The same
Builder thread receives complete factual failures for the current candidate. A
byte change creates a new candidate identity and invalidates affected evidence.
There is no framework fallback, compatibility adapter or hand-written success
candidate.

## 7. Canonical Environment contract

### 7.1 Types

```python
JSONScalar = None | bool | int | float | str
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]


class ToolSpec(TypedDict):
    name: str
    description: str
    input_schema: JSONObject
    output_schema: JSONObject


class ToolError(TypedDict):
    code: str
    message: str
    details: NotRequired[JSONValue]


class ToolObservation(TypedDict):
    ok: bool
    data: JSONValue | None
    error: ToolError | None


class Environment(Protocol):
    def reset(self, start: JSONObject | None = None) -> JSONValue: ...
    def tools(self) -> tuple[ToolSpec, ...]: ...
    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation: ...
    def close(self) -> None: ...
```

The generated project exposes one standard Python factory through release
metadata. The host/consumer library performs loading:

```python
env = load_environment(
    release_path="environment-release.tar",
    instance_directory="episodes/episode-001",
)
```

Loading and instance-directory ownership are caller/runtime responsibilities,
not acting-Agent tools. A deployment layer may wrap the same object as a service
without changing this contract.

Loading an empty assigned directory creates a handle but does not invent domain
state before `reset`. Loading the same release against an existing instance
directory reattaches to its committed state without resetting it. `close()`
releases processes/files but leaves directory deletion to the caller. These
loader semantics let Qualification and S2 test persistence without adding a
public `reopen` method.

All schemas use JSON Schema Draft 2020-12, are bundled with the release and may
resolve local fragment references only. Input and non-null start schemas have
object roots; output schemas may describe any JSON value. `None` selects the
package default outside the start schema.

### 7.2 Reset

`reset(start)` atomically constructs a new episode state inside the assigned
instance directory and returns the public initial observation.

- `start=None` always produces a meaningful ready-to-use default world.
- A package may publish an object-root JSON schema for additional start
  configuration.
- The release also publishes the schema of the reset observation.
- The loader validates every returned initial observation against the named
  digest-bound `reset_observation_schema`.
- Same release plus same start reproduces the Brief-declared business relations,
  not necessarily identical physical bytes or generated identifiers.
- A failed reset does not claim a valid initial observation.
- Multiple environment instances use distinct directories; reset never affects
  another instance.

Public values needed before the first tool call—such as current simulated time,
acting identity or visible catalog summary—belong in the reset observation or
must be discoverable through a public tool. Protected native state does not.

### 7.3 Tools and invocation

`tools()` returns the complete acting surface. Tool names and schemas are
package-specific; the Foundry knows no domain vocabulary.

Before dispatch, the runtime validates the requested name and arguments against
the advertised input schema. Invalid actions do not execute domain code or
mutate state.

`invoke()` then executes real project code and returns the uniform observation:

```json
{"ok": true, "data": {"reservation_id": "R-17"}, "error": null}
{"ok": false, "data": null, "error": {"code": "sold_out", "message": "No capacity", "details": {}}}
```

Successful `data` validates against the selected ToolSpec's `output_schema`.
Business refusals use a stable tool-specific code/details and perform no
prohibited mutation. This single `ok` distinction is enough for callers; S1
does not define a larger business-error taxonomy. A crash, timeout, invalid
output or corrupted runtime raises an environment failure and cannot be stored
as an observation.

The only valid variants are:

```text
ok=true  => error=null and data is output-schema valid
ok=false => data=null and error={code,message,details?}
```

Unknown tools and schema-invalid arguments return the second form with reserved
`contract.unknown_tool` or `contract.invalid_arguments` codes before domain
dispatch. `contract.*` is never business-refusal evidence or a PublicValuePool
source. Invalid reset input raises `EnvironmentContractError`; process failure,
timeout or invalid output raises `EnvironmentRuntimeError` and produces no
ToolObservation.

The structured result is the binding surface. A later invocation may consume a
JSON value from an earlier result directly:

```python
initial = env.reset()
available = env.invoke("search_availability", {"date": "2026-09-01"})
reservation = env.invoke(
    "reserve",
    {
        "resource_id": available["data"]["items"][0]["resource_id"],
        "date": "2026-09-01",
    },
)
```

Free-form prose is never parsed to recover required operands. Large text,
images or files may be returned through tool-specific structured public
references described by the output schema.

### 7.4 Adapter boundary

The canonical contract contains no model/provider messages. A caller adapter
may:

1. translate `ToolSpec` into an OpenAI, MCP or other model declaration;
2. generate its own correlation/tool-call identifier;
3. call `env.invoke(name, arguments)`;
4. render the structured result into the provider's observation message;
5. record the action/result in an Episode later owned by S3.

No adapter may add capabilities, protected values or different semantics.

## 8. Native state and independent Qualification

### 8.1 State boundary

All authoritative episode state lives beneath the caller-assigned instance
directory unless the accepted Need explicitly requires a qualified external
dependency. Canonical training-grade releases must remain resettable and
independently testable.

The package may choose SQLite, files/Git or another independently readable
format. The framework contains no backend enum or universal State JSON. The
generated source and public documentation explain the implementation; the
Qualifier verifies rather than trusts them.

### 8.2 Qualifier authority

The Qualifier is independently authored and does not see Builder chat, repair
history or Builder tests. For each core requirement it first freezes a
Brief-derived expected business relation and acceptance predicate. Only then
may it inspect candidate source to locate/decode arbitrary native formats. The
qualification evidence records that order and source-use purpose. Candidate
business functions are never imported or executed as the oracle.

For every core requirement it records a small reconciliation row:

```text
requirement -> public setup/calls -> expected relation -> independent native observation -> verdict
```

There is no generic truth DSL. Environment-specific probe code performs the
translation:

- booking: call search/reserve/cancel, then use independent read-only SQLite
  queries to check reservations and capacity;
- filesystem/Git: call read/edit/check/commit, then inspect bytes, modes, index,
  refs and objects with filesystem APIs and Git plumbing;
- another format: use a mature independent reader or separately authored parser.

If native semantics cannot be read independently, the world is not qualified.

### 8.3 Required physical checks

Qualification covers:

- reset creates meaningful initial data and returns correct public context;
- two or more public calls form a real value-dependent chain;
- public results correspond to native before/after state;
- business refusal performs no prohibited native mutation;
- a second instance remains unchanged;
- repeating reset reconstructs the declared initial relations;
- when non-default start fields exist, one valid non-default start is repeated
  on a separate fresh instance;
- closing and cold-loading released bytes preserves promised behavior;
- every core requirement has a probe that rejects a reachable wrong or near-miss
  behavior.

Physical counterexamples are preferred. Source mutation may strengthen a probe
when needed, but is a test technique rather than a product node, public
contract, receipt field or mandatory mutation framework.

## 9. Failure ownership and repair

| First observed deviation | Owner | Next action |
| --- | --- | --- |
| unsupported or misinterpreted domain evidence | Research | revise Brief/evidence; start a new Builder lineage |
| dependency, build, import or Environment API defect | Builder | repair same workspace/thread; new candidate identity |
| public result disagrees with Brief/native state | Builder | receive requirement-scoped factual observation |
| Qualifier expected relation contradicts Need/Brief | Qualifier | revise probe with candidate bytes unchanged |
| package cannot cold load from its own declared material | Builder or release code, based on first cause | repair owning artifact; rerun affected checks |
| provider/network/host resource failure | infrastructure | retry identical inputs and candidate bytes |

Feedback contains the decisive input, expected relation and actual public/native
observation. It does not reveal hidden test source or prescribe a hard-coded
patch. Exhaustion ends `NotReleased`.

## 10. EnvironmentRelease

### 10.1 Public artifact

```text
payload-manifest.json          complete public payload path/mode/content digests
release.json                   identity preimage and loading metadata
project/                       exact generated uv source project
dist/                          built generated package
docs/DEVELOPMENT_BRIEF.md      disclosed world interpretation and limitations
docs/ENVIRONMENT.md            direct usage and tool behavior
qualification.json             host-authored summary bound to payload digest
licenses/
```

Initial data/assets have one logical owner: generated-project package data.
They must be included in the built distribution and accessed through normal
package-resource APIs. There is no second top-level asset tree. A StartRecipe
may use a documented package asset identifier, never an archive path.

Identity is a small non-circular digest DAG using SHA-256 and RFC 8785 canonical
JSON:

```text
payload-manifest.json
  = sorted records for every public member under project/, dist/, docs/ and
    licenses/: relative path, regular-file type, normalized mode, content digest

payload_digest
  = SHA-256(canonical payload-manifest.json bytes)

qualification_digest
  = SHA-256(canonical qualification.json bytes)
  where qualification.json contains payload_digest, verdict, requirement
  coverage and content-digested evidence references

release.json
  = canonical loading metadata + payload_digest + qualification_digest

EnvironmentReleaseID
  = SHA-256(canonical release.json bytes)
```

Symlinks and unlisted public members are rejected. The release ID is computed
from `release.json`; it is not stored inside its own preimage. Any project,
distribution, docs, schema, license, qualification or loading-metadata change
therefore changes a bound digest and the release identity.

`release.json` contains only loading and identity facts with current consumers:

```text
format/canonicalization/hash version
payload and qualification digests
Python/platform requirements
environment factory entry point
start schema and reset-observation schema locations
public documentation location
```

It contains no MCP transport, lifecycle commands, backend taxonomy, Task,
verifier, reward, graph, model message or training field.

Exact Research source bodies, hidden probes, raw expected native values, failed
candidates and repair conversations may be retained in ordinary protected audit
storage. They are not part of the environment runtime or a required Registry
subsystem.

### 10.2 Cold use

The release gate extracts exact bytes into an unrelated directory, prepares the
declared locked Python environment and invokes only the third-party path:

```python
env = load_environment(release, fresh_instance_directory)
initial = env.reset()
specs = env.tools()
first = env.invoke(specs[selected].name, arguments)
second = env.invoke(next_tool, arguments_using(first))
env.close()
```

The independent qualifier repeats native, reset and isolation checks against
those released bytes. Publication assigns the exact artifact an immutable
identity. A local artifact directory, object store or later Registry service may
store it; storage topology does not redefine `EnvironmentRelease`.

## 11. S2 handoff

S2 receives the exact S1 output without an adapter that invents semantic fields:

```text
EnvironmentRelease
├── load/reset/close behavior
├── public reset/start schemas and initial observation
├── tools() ToolSpecs
├── invoke() uniform ToolObservations
├── public Brief/environment documentation
├── isolated episode instance directory
└── qualification summary and limitations
```

Graph-based Task generation may propose tool transitions from ToolSpecs and
public exploration. Programmatic Task generation may write a reference program
using `reset`, `tools` and `invoke`. Both obtain actual facts by executing the
same environment. Neither requires S1 to contain a Task graph, witness, oracle
program, final answer, verifier or reward.

S2's trusted components may inspect the isolated instance directory to author
task-specific truth extraction. They never mutate it except through `reset` and
public tools. S1 does not standardize the task-specific truth representation.

Before S1 release, a consumer-shaped seam check proves only that an independent
caller can load, reset, discover, invoke and inspect the environment. It does not
generate a provisional Task or implement any S2 algorithm.

## 12. Trust and visibility

```text
Research:       Need + web/user evidence; no candidate or downstream Task
Builder:        Need + Brief + evidence index + Environment contract
Runner:         exact candidate public execution
Qualifier:      Need + Brief + candidate/public surface + native instance;
                no Builder conversation/tests as authority
Acting Agent:   Task/start context supplied later by S2/S3 + ToolSpecs + public observations
S2 verifier:    exact release + TaskPack + trusted task-specific native inspection
Publisher:      exact candidate + qualification/cold result
```

The acting Agent never receives native expected values, hidden qualification
probes or later task verifiers. Model diversity may be measured in paper
experiments but cannot replace independent physical evidence.
