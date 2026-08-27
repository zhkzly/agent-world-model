# S1 Environment Foundry — implementation plan

## Planning exit before product code

- [ ] `prd.md`, `design.md` and this plan contain the same S1 input/output and
  `reset/tools/invoke/close` contract.
- [ ] S2 PRD/design consume only `EnvironmentRelease` and contain no reverse
  requirement for MCP, lifecycle commands, graph fields or S1-authored Task data.
- [ ] Independent SOL, Terra and Claude/GLM reviews trace the full
  S1 → S2 → S3 → S4 relationship and all material findings are resolved in the
  canonical documents.
- [ ] Fresh Alignment Patrol returns `ALLOW` for the persisted plan change.
- [ ] `implement.jsonl` and `check.jsonl` validate with current context entries.
- [ ] The user reviews this final document set and explicitly authorizes S1
  implementation in a later turn.
- [ ] `task.py start` activates S1 only after that authorization.
- [ ] Before the first product-code edit, create the short frozen execution
  contract/checklist and RED/mutation evidence required by `task-protocol`.

Planning approval never authorizes S2 implementation. After a real S1 release,
S2 design is revalidated against the actual EnvironmentRelease before S2 gets an
implementation plan.

## Implementation invariants

- The positive path always uses real Research, a real Python Codex SDK Builder,
  a complete generated uv project and real native state.
- No hand-written successful environment, repository template, domain fixture,
  dict response map or fake provider may produce `Released`.
- Mechanical fakes may test serialization and failure handling only.
- Every slice has observable RED evidence and a mutation/physical-negative
  licence for the claim it introduces.
- Partial slice green is a checkpoint, never product completion.
- No old branch/commit product code, prompts, tests, fixtures, Skills or plans
  are implementation inputs.
- New fields, helpers, modules and Skills require a named current producer and
  consumer. Speculative extensibility is removed.

## Slice 1 — canonical Environment contract and release loader

Implement the transport-neutral shared boundary first:

- JSON value validation and canonical schema handling;
- JSON Schema Draft 2020-12 with object-root start/input schemas,
  self-contained local-fragment references and no remote resolution;
- `ToolSpec {name, description, input_schema, output_schema}`;
- uniform `ToolObservation {ok, data, error}` with schema-valid success data;
- the `Environment` protocol with `reset`, `tools`, `invoke`, `close`;
- named digest-bound `start_schema` and `reset_observation_schema`, with loader
  validation of non-null starts and every reset result;
- standard generated-package factory/entry-point loading;
- caller-owned instance directories;
- reserved `contract.*` ToolObservations for invoke validation,
  `EnvironmentContractError` for invalid reset input and runtime-failure
  propagation with no fictional observation;
- minimal `release.json` parsing and payload-digest verification.

This slice does not implement MCP, HTTP, a private RPC wire, provider messages,
call IDs, Tasks, native-state schemas or a Registry service.

RED/negative evidence:

- missing/duplicate tool names or invalid schemas are rejected;
- reset accepts a value or emits an observation outside its published schema;
- unknown tool or invalid arguments cannot reach domain execution;
- contradictory observation variants (`ok=true` with error or `ok=false` with
  data) are rejected;
- `contract.*` validation feedback is treated as invalid action, never business
  refusal, state evidence or a PublicValuePool source;
- successful observation data not matching the selected tool's output schema is
  a runtime defect;
- an adapter correlation ID cannot alter environment semantics;
- loading cannot escape the assigned release or instance directory;
- `release.json` containing Task/reward/transport/lifecycle fields is rejected by
  the plan-level contract test, not normalized.

Checkpoint evidence is contract behavior only. No hand-written positive domain
package may be described as an S1 release.

## Slice 2 — real Research and Development Brief

Implement:

- the complete raw Need plus deterministic coverage anchors that remain
  addressing aids rather than semantic authority;
- a thin official Responses adapter using real function calls and the minimum
  continuation state required by the configured route;
- exactly two Agent-visible tools: discovery-only `search_sources` and
  Agent-selected, focused `read_sources`;
- a physical comparison of the current retrieval implementation with Wigolo's
  Python SDK/local REST `search` and `fetch`; adopt Wigolo only if challenge
  failures stay typed, cited content is restart-readable and the repository has
  a net deletion. The product path does not require MCP;
- one run-local Research Agenda covering world relations, success transitions,
  refusals/prohibited mutation, material dynamics, initial-world relations,
  authority and coherent scope choices;
- real selected-source snapshots and bounded passages sufficient to close
  Agenda questions; snippets, blocked pages and no-match reads cannot become
  evidence;
- one method-only Research Skill;
- semantic-closure stopping conditions rather than success-by-call-count;
- one compiled Development Brief plus a dedicated Builder projection containing
  only FrozenNeed, SelectedWorld, Requirements, InitialWorldRelations and compact
  cited evidence;
- a fresh independent Evidence Reviewer that emits only typed clause,
  requirement and scope findings, residual limitations and high-burden
  unsupported findings; Host code owns deterministic routing;
- actionable blocking findings returned to the same producer history followed
  by a new fresh Reviewer;
- a real-model paired-case calibration report before the Reviewer becomes a
  hard Builder gate.

Delete or keep outside the product admission path:

- full provider request/response trace and `provider_responses` retention;
- acquisition counters as semantic evidence;
- separate tool/Draft/semantic/reviewer correction-budget product states;
- duplicate full and reviewer evidence indexes, body-mirror graphs and fields
  without a Builder, Reviewer or audit consumer;
- tests that protect only event names, field absence or arbitrary file modes.

The Research/Builder output contains no Research-authored concrete tool schema,
database schema, exact seed identifier, Task, verifier, reward or transport.

RED/negative evidence:

- search snippet or model prior is cited as evidence;
- blocked/challenge or irrelevant content is counted as supporting evidence;
- citation cannot be reopened to the retained source snapshot and exact passage;
- a model is required to author/transcribe host digest values;
- one original Need span disappears from the compiled Brief;
- a Need or fixed Environment-contract requirement is rejected only because it
  lacks a web citation;
- an invoice-issuance deadline is accepted as evidence for a payment-due claim;
- a disclosed coherent jurisdiction/workflow selection is classified as an
  unjustified narrowing;
- an undisclosed narrowing is classified as an acceptable selection;
- a residual limitation blocks acceptance, or a blocking finding is hidden as
  a residual limitation;
- a required capability is relabeled as a limitation without support;
- contradictory load-bearing sources are silently merged;
- Research emits tool/table/Task schemas that belong downstream;
- raw Research/reviewer/audit records enter Builder context;
- an unsupported Need proceeds into Builder;
- a correctable reviewer finding is terminalized without returning to Research
  and obtaining a new fresh review;
- an LLM reviewer directly emits `NOT_RELEASED` or otherwise owns a system
  terminal verdict;
- a fake client, manually authored positive Brief or acquisition counter is used
  as ResearchReady evidence.

Physical checkpoint:

- a clear unfamiliar Need produces an inspectable Agenda, Agent-authored queries,
  selected-source focused reads, explicit closed/open gaps and an independently
  accepted compiled Brief with retained cited evidence;
- the local Luna route must physically emit a schema-valid function call,
  consume the host's matching function output through explicit item history,
  and continue the same Agent loop; a fixed framework search sequence cannot
  substitute for this proof.
- the real reviewer route is calibrated against paired semantic cases: direct
  Need and contract authority without web evidence, issuance-versus-payment
  predicate mismatch, disclosed versus undisclosed scope narrowing, sufficient
  evidence despite inaccessible sources, and PASS-equivalent findings with
  residual limitations. Report false accepts/rejects across repeated fixed
  trials; one best trace is not calibration.
- Slice 2 is not accepted as a free-standing product milestone until the real
  Slice 3 Builder consumes its dedicated projection without requiring an
  authority/schema expansion.

## Slice 3 — real Codex Builder and executable candidate

Implement:

- a fresh `uv init --package` workspace with no domain source;
- Builder context containing only the dedicated FrozenNeed/SelectedWorld/
  Requirements/InitialWorldRelations/cited-evidence projection and canonical
  Environment contract;
- the sole environment-codegen Skill;
- one resumable Builder thread and byte-derived candidate identities;
- real `uv lock`, install, build, import and API execution;
- complete factual repair feedback to the same Builder thread;
- execution through the Slice 1 release loader/runtime surface.

The first accepted Builder run is also the consumer validation for Slice 2: if
the Builder needs Research drafts, reviewer records, missing business relations
or another semantic schema, the defect returns to the Research contract rather
than being patched into Builder context.

The generated project must supply:

- a standard environment factory;
- meaningful package-owned default data/assets;
- structured reset/start schemas and initial observation;
- ToolSpecs and real `invoke` implementations;
- native persistent state beneath its assigned instance directory;
- public documentation and diagnostic tests.

RED/negative evidence:

- domain code or seed data exists before the Builder turn;
- a template/dict/canned-result candidate passes candidate execution;
- `reset(None)` yields an empty unusable world;
- tool output is prose-only when a later tool needs one of its values;
- an invocation bypasses or violates the uniform `ok/data/error` record;
- result reports success without corresponding native mutation;
- business refusal mutates prohibited state;
- state exists only in process memory;
- reset or one instance changes another instance;
- a changed source byte retains the previous candidate identity;
- repair feedback leaks hidden qualification code/expected values;
- repeated unchanged failure has no bounded terminal result.

Physical checkpoint:

- the real accepted `BuilderProjection` causes the real Codex SDK thread to
  author a complete uv project from the empty workspace and the
  third-party-shaped loader performs `reset -> tools -> invoke -> invoke -> close`.

## Slice 4 — independent native semantic Qualification

Implement:

- an independent Qualifier invocation receiving the same `BuilderProjection`,
  candidate source, public API/docs and controlled access to candidate instance
  directories;
- Brief-derived expected relations frozen before candidate-source access, with
  source inspection limited and logged for native representation decoding;
- requirement-derived ordinary Python probes in a separate workspace;
- independent native readers chosen by the Qualifier, not a framework backend
  enum or candidate truth endpoint;
- a small requirement → probe → public/native evidence reconciliation table;
- reset, multi-call value chaining, refusal/no-mutation, instance isolation and
  cold-use probes;
- factual attribution between candidate defect, invalid probe and infrastructure
  failure;
- optional physical near-misses or source mutants as test-sensitivity techniques,
  without a Mutator product node.

RED/negative evidence:

- Qualifier imports candidate business functions to compute expected truth;
- Builder tests or Builder chat become qualification authority;
- decorative SQLite/Git state beside an in-memory result map passes;
- cached response, no-op write, wrong entity, collateral mutation, missing Git
  commit or reset residue passes;
- a published non-default start path is never exercised on two fresh instances;
- a probe passes both correct and reachable incorrect behavior;
- a core Brief requirement has no discriminating evidence but is released;
- opaque state with no independent reader is qualified.

Physical checkpoint:

- a real generated environment passes requirement-derived public/native probes;
  independently introduced near-miss behavior fails for the intended semantic
  reason.

## Slice 5 — EnvironmentRelease and cold publication

Implement:

- exact release assembly containing generated project, lockfile, distribution,
  package data, public Brief/environment docs and licenses;
- one logical package-data owner, with cold verification that required data is
  present in the built distribution and no duplicate top-level asset tree;
- canonical payload manifest, qualification digest and non-circular
  EnvironmentReleaseID using SHA-256 and RFC 8785 canonical JSON;
- minimal `release.json` with payload identity, loading entry point,
  Python/platform requirements and named start-schema,
  reset-observation-schema and public-document locations; Tool input/output
  schemas remain exclusively in the runtime `ToolSpec[]` returned by `tools()`;
- host-authored `qualification.json` bound to exact payload and requirement
  evidence digests;
- optional ordinary protected audit storage for source/probe/native evidence;
- cold extraction to an unrelated directory, preparation from declared locked
  dependencies and full direct-use/native checks;
- immutable artifact publication by exact identity using the simplest available
  artifact store.

Do not implement custom Registry staging, `current/latest`, revocation service,
Observe subsystem, mandatory offline wheelhouse, SBOM platform, MCP server or
transport adapter in this slice. Such features require a separate current
consumer and decision.

RED/negative evidence:

- payload byte, path or loading metadata changes without identity change;
- public docs/schema/license/distribution changes without identity change;
- symlink, unlisted member, duplicate logical asset or mismatched source/wheel
  package data is accepted;
- cold use requires the Builder workspace, ambient virtualenv, conversation or
  generator-private file;
- qualification summary refers to different candidate bytes;
- public payload contains hidden probes/native expected values;
- an unqualified artifact receives a release identity;
- release can load but cannot complete the two-call stateful path after reset.
- reset observation differs from its digest-bound published schema during cold use.

## Slice 6 — full product proofs and S2 seam

Run the complete production path with real providers and no manual candidate
source edits:

1. Booking-like Need: meaningful users/resources/availability/current state;
   search/reserve/cancel/refuse; independent SQLite relations.
2. Filesystem/Git Need: meaningful real repository; read/edit/check/commit and
   restrictions; independent file/Git relations.
3. Freeze generic framework code, prompts and the two runtime Skills.
4. Independently select held-out Needs spanning different state and interaction
   shapes, then run the same path without a domain branch or prompt specialization.
5. For each exact release, run an S2-shaped consumer using only:

   ```text
   EnvironmentRelease
   -> reset(start)
   -> tools()
   -> invoke(...).data
   -> invoke(... using prior data)
   -> trusted read-only native inspection
   -> close()
   ```

The S2 seam test generates no Task, Graph, Programmatic program, truth extractor,
verifier or reward. Its sole claim is that S1 supplied the complete environment
context later S2 algorithms consume.

Release acceptance requires the real generation path, independent native
Qualification, exact cold artifact and same-interface held-out evidence. One
successful domain does not establish arbitrary-domain generality.

## Slice 7 — paper and reproduction handoff

Produce a compact experiment index and human runbook containing:

- Need and evidence identities;
- accepted world interpretation and limitations;
- model/SDK/runtime/toolchain configuration;
- candidate lineage and factual repair attribution;
- exact EnvironmentRelease identity;
- requirement-linked Qualification and negative evidence;
- cold-use and S2 seam results;
- held-out evaluation scope and residual Research/Qualifier risks.

Run the published instructions from a fresh root using released inputs. The
runbook reports evidence and limitations; it cannot convert a failed release
gate into success.

## Validation shape

Exact command names are finalized when the new project scaffold exists. The
required classes are:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run pytest -q -m physical
uv run pytest -q -m live
uv run foundry generate --need-file <need.md>
uv run foundry verify-release --release <release-path-or-id>
```

After each slice, use independent implementation/check workers with the current
task bundle. Before implementation starts and after Slice 7, run complete
cross-stage reviews from at least one Codex SOL, one Codex Terra and one
Claude/GLM reviewer. Reviewers trace Need → EnvironmentRelease → TaskPack →
Episode/Reward → SFT/RL and reject both missing handoffs and S2-to-S1 leakage.

## Rollback and failure behavior

- Before publication, discard candidate/release staging while preserving only
  evidence needed for diagnosis.
- A changed candidate reruns affected Qualification and receives a new release
  identity.
- Infrastructure retry keeps candidate bytes fixed.
- A discovered released defect never causes in-place semantic repair; publish a
  new qualified identity and mark the defective artifact unavailable through the
  chosen artifact store's ordinary mechanism.
- `Unsupported` and `NotReleased` are fail-closed outcomes, never permission to
  substitute a mock environment.
