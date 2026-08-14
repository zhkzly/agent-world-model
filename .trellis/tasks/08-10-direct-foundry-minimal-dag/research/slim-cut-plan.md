# Research: Slim Cut Plan for agent_world/ (11,416 → <10,000)

- **Query**: Produce a dependency-ordered CUT PLAN to slim agent_world/ source from 11,416 lines to under 10,000 (cut >=1,416), preserving the minimal E2E path: EnvironmentRequest -> research -> design -> candidate_build -> integration -> verifier_intent -> judge -> package -> registry.
- **Scope**: internal (read-only audit)
- **Date**: 2026-08-13

## Current File Sizes (wc -l)

| File | Lines | Role |
|---|---|---|
| candidate.py | 3132 | Candidate graph: build, integration, judge, package, registry |
| design.py | 2678 | Design graph: research, architecture, tools, rules, curriculum, tasks |
| contracts.py | 1199 | Frozen dataclass contracts and type helpers |
| graph.py | 1030 | Fixed graph spec, node transaction runner, resume infra |
| runtime.py | 916 | Candidate process ABI, integration/judge execution |
| observe.py | 537 | Read-only CLI projection of persisted runs |
| supply_chain.py | 523 | Offline wheel admission, SBOM, lock validation |
| artifacts.py | 498 | Content-addressed immutable artifact store |
| invocation.py | 459 | Direct chat + Codex agent LLM boundaries |
| foundry.py | 224 | Composition root (generate, resume, check-config) |
| config.py | 147 | TOML config loading |
| cli.py | 66 | argparse entry point |
| __init__.py | 7 | version |
| **Total** | **11416** | |

---

## Prioritized Cut Table

| Priority | Target (file:lines or file:function) | Category | Lines Saved | Coupling (callers/importers) | Test Impact | Risk | Recommended Action |
|---|---|---|---|---|---|---|---|
| 1 | `supply_chain.py` (entire file, 523 lines) | OVER-BUILT / NON-ESSENTIAL (user-flagged "permission management") | ~488 | candidate.py imports: `prepare_candidate` (3 sites: `_integration:1050`, `_judge_node:1360`, implicit via `_candidate_build`), `admitted_lock_closure_value` (2 sites), `compile_sbom` (`_package:1593`), `compile_sbom_from_metadata` (`_cold_read_package:2555`), `SupplyChainError` (3 catch sites). FoundrySettings has `trusted_wheel_store` field. | test_supply_chain.py (358 lines) would be deleted entirely. | MED | SIMPLIFY to ~35-line stub: trust candidate is stdlib-only. `prepare_candidate()` becomes a contextmanager yielding `PreparedCandidate(python=Path(sys.executable), admitted_lock_closure=AdmittedLockClosure(entries=()))`. `compile_sbom()` / `compile_sbom_from_metadata()` return minimal SBOM with empty dependencies. `admitted_lock_closure_value()` returns `{"entries": []}`. Keep `SupplyChainError` as exception type for catch compatibility. |
| 2 | `observe.py` (entire file, 537 lines) | NON-ESSENTIAL FEATURE | 537 | cli.py:12 imports `ObserveError, observe_run`. observe.py:12 imports `_cold_read_package` from candidate.py and `candidate_graph, design_graph` from graph.py. NOT on the generate->registry path. | test_artifacts_observe.py (212 lines): 4 artifact tests (keep) + 5 observe tests (delete). Must split file. | LOW | DELETE entirely. Remove import and `observe` subcommand from cli.py. Split test_artifacts_observe.py: keep artifact tests, delete observe tests. |
| 3 | `candidate.py:2571-2958` `_verify_package_metadata` (388 lines) | OVER-BUILT (defense-in-depth re-validation of every metadata file inside the zip) | ~358 | Called from `_cold_read_package:2561`. Only invoked during registry node's cold-read. | test_direct_release.py lines 897, 1000, 1049, 1058, 1154, 1214 call `_cold_read_package` which calls this internally. Tests would need updated if verification behavior changes. | MED-HIGH | SIMPLIFY to ~30 lines: check `schema_version` strings only (world-spec@1, rule-ir@1, curriculum@1, etc.), skip all cross-digest re-derivation. The package was just built by `_package_metadata` which already computed these correctly; re-deriving and comparing every digest is defense-in-depth. |
| 4 | `candidate.py:2960-3082` `_cold_verify` (123 lines) | OVER-BUILT (re-derives expected metadata and compares to cold-read package) | ~108 | Called from `_registry:1728`. | test_direct_release.py tests the registry cold-read path. | MED-HIGH | SIMPLIFY to ~15 lines: verify integration status is "passed" and artifact_refs/digests match, skip full metadata re-derivation. Or DELETE entirely and trust `_cold_read_package` + `_verify_package_metadata`. |
| 5 | `foundry.py:96-165` `_generate_resume` (70 lines) | NON-ESSENTIAL FEATURE (--resume/--from) | 70 | Called from `generate():55-57`. Uses `compute_upstream` from graph.py. | test_resume.py (465 lines) tests resume. Would need deletion or simplification. | LOW | DELETE. Remove `resume_run_id`/`restart_from` params from `generate()` and public `generate()` function. Keep `_generate_fresh` only. |
| 6 | `graph.py:124-152` `_ancestors` + `compute_upstream` (29 lines) | NON-ESSENTIAL FEATURE (used only by --from) | 29 | `compute_upstream` imported by foundry.py:26 and test_resume.py:54. | test_resume.py tests compute_upstream (3 tests). | LOW | DELETE. Remove from foundry.py imports. |
| 7 | `cli.py:27-35,52-55` remove `--resume`, `--from` args + observe subcommand | NON-ESSENTIAL FEATURE | ~15 | Only in cli.py. | No direct test. | LOW | SIMPLIFY: remove observe subcommand (lines 33-35), remove --resume and --from argparse args (lines 27-31), remove resume kwargs from generate() call (lines 49-51). |
| 8 | `candidate.py:2431-2489` `_manifest_shape` (59 lines) | OVER-BUILT (re-validates manifest structure that was just built) | ~34 | Called from `_cold_read_package:2509`. | test_direct_release.py indirect. | MED | SIMPLIFY to ~25 lines: check required top-level keys exist, skip per-field type re-validation. |
| 9 | `candidate.py:1983-2053` `_compile_telemetry` (71 lines) | OVER-BUILT (elaborate operation aggregation/counting) | ~36 | Called from `_package:1596` and `_cold_verify:3033`. | test_direct_release.py indirect. | LOW | SIMPLIFY to ~35 lines: list operations from work records, skip category_counts and model_counts aggregation (they are metadata not needed for functional correctness). |
| 10 | `foundry.py:19-28,52-53,205-211` resume imports + params cleanup | DEAD CODE after step 5 | ~5 | foundry.py imports. | None. | LOW | DELETE unused imports (`CANDIDATE_EDGES`, `CANDIDATE_NODES`, `DESIGN_EDGES`, `DESIGN_NODES`, `compute_upstream`), remove resume params from public `generate()`. |
| **Total** | | | **~1680** | | | | |

### Running total after each priority

| After Priority | Cumulative Lines Saved | Remaining Total |
|---|---|---|
| 1 (supply_chain) | 488 | 10928 |
| 2 (observe) | 1025 | 10391 |
| 3 (_verify_package_metadata) | 1383 | 10033 |
| 4 (_cold_verify) | 1491 | 9925 |
| 5 (_generate_resume) | 1561 | 9855 |
| 6 (compute_upstream) | 1590 | 9826 |
| 7 (cli.py) | 1605 | 9811 |
| 8 (_manifest_shape) | 1639 | 9777 |
| 9 (_compile_telemetry) | 1675 | 9741 |
| 10 (foundry imports) | 1680 | 9736 |

**Final projected total: ~9,736 lines** (under 10,000 with ~264 line buffer)

### Minimum viable cut set (reaches >=1,416)

Priorities 1-4 alone yield **1,491 lines** saved, reaching the target with 75 lines of margin. This set has:
- 2 LOW-risk cuts (observe, foundry imports)
- 1 MED-risk cut (supply_chain)
- 2 MED-HIGH-risk cuts (_verify_package_metadata, _cold_verify)

If the implementer wants to avoid MED-HIGH risk entirely, use priorities 1-3 + 5-10:
488 + 537 + 358 + 70 + 29 + 15 + 34 + 36 + 5 = **1,572 lines** (1 MED-HIGH risk only).

---

## Dependency-Ordered Execution Sequence

Each step leaves the tree compiling. Steps are ordered so no step depends on a later one.

### Step 1: Delete observe.py + split cli.py (LOW risk, 552 lines saved)

**Why first**: observe.py has no inbound dependencies except cli.py. Safe to remove without touching any other module.

1. Delete `agent_world/observe.py` (537 lines)
2. Edit `cli.py`: remove `from agent_world.observe import ObserveError, observe_run` (line 12), remove `observe` subcommand parser (lines 33-35) and its handler (lines 52-55), remove `ObserveError` from except clause (line 58)
3. Split `tests/test_artifacts_observe.py`: keep the 4 artifact tests (lines 28-61), delete the 5 observe tests (lines 62-212). Rename to `tests/test_artifacts.py`.
4. Delete `tests/test_supply_chain.py` if doing step 2 next, otherwise defer.

**Compiles after**: Yes. No module imports observe except cli.py.

### Step 2: Simplify supply_chain.py to stdlib-trust stub (MED risk, 488 additional lines)

**Why second**: Depends only on candidate.py call sites. Must happen before candidate.py verification cuts (step 4) since _cold_read_package calls `compile_sbom_from_metadata`.

1. Replace `agent_world/supply_chain.py` (523 lines) with a ~35-line stub:
   - Keep: `SupplyChainError`, `AdmittedLockClosure`, `AdmittedLockEntry`, `PreparedCandidate`, `LockedWheel` (dataclass shells)
   - Keep: `admitted_lock_closure_value()` returning `{"entries": []}`
   - Keep: `compile_sbom(root)` returning `{"schema_version": "sbom@1", "root": {"name": "candidate", "version": "0", "license_state": "unknown"}, "dependencies": [], "admitted_lock_closure": {"entries": []}}`
   - Keep: `compile_sbom_from_metadata(pyproject, lock)` calling `compile_sbom` with a temp dir or returning the same constant
   - Keep: `prepare_candidate(root, trusted_wheel_store=None)` as a contextmanager yielding `PreparedCandidate(python=Path(sys.executable), admitted_lock_closure=AdmittedLockClosure(entries=()))`
   - Delete: `_read_candidate_metadata`, `_project_dependencies`, `_lock_packages`, `_dependency_names`, `_package_dependency_names`, `_package_wheels`, `_normalized_name`, `_digest`, `_digest_tree`, `_admit_wheels`, `_requirements`, `_minimal_environment`, `offline_uv_argv`, `_installed_distributions` (all the wheel/lock/uv machinery)
2. Remove `trusted_wheel_store` from `FoundrySettings` in config.py (lines 45, 110-117) and its TOML parsing. Or keep as `None` always.
3. Update `tests/test_supply_chain.py`: delete entirely (358 lines) or replace with a minimal test of the stub API.
4. candidate.py: the existing call sites at lines 1050, 1061, 1360-1361, 1593, 2555 will continue to work unchanged because the stub preserves the same function signatures.

**Compiles after**: Yes. The stub preserves all imported names used by candidate.py.

### Step 3: Remove resume/restart-from infra (LOW risk, 114 additional lines)

**Why third**: Independent of supply_chain and observe changes. Only touches foundry.py, graph.py, and cli.py.

1. Delete `foundry.py:96-165` (`_generate_resume` method, 70 lines)
2. Delete `foundry.py:55-57` (resume branch in `generate()`)
3. Simplify `foundry.py:48-57` `generate()` to just `return self._generate_fresh(need)`
4. Delete `foundry.py:19-28` imports: remove `CANDIDATE_EDGES`, `CANDIDATE_NODES`, `DESIGN_EDGES`, `DESIGN_NODES`, `compute_upstream` (keep `ResumeContext` — still used by `_generate_fresh`)
5. Delete `graph.py:124-152` (`_ancestors` and `compute_upstream`, 29 lines)
6. Simplify `cli.py`: remove `--resume` and `--from` args (lines 27-31), remove `resume_run_id`/`restart_from` kwargs from `generate()` call
7. Delete or simplify `tests/test_resume.py` (465 lines). Keep `from_value` round-trip tests (lines 234-265), delete resume-specific tests.
8. Public `generate()` in foundry.py: remove `resume_run_id`/`restart_from` params (lines 205-211).

**Compiles after**: Yes. `_generate_fresh` creates its own `ResumeContext()` and never calls `compute_upstream`.

### Step 4: Simplify candidate.py package verification (MED-HIGH risk, ~500 additional lines)

**Why fourth**: Depends on supply_chain simplification (step 2) since `_cold_read_package` calls `compile_sbom_from_metadata`.

1. Replace `_verify_package_metadata` (388 lines, 2571-2958) with ~30-line version:
   - Check `isinstance` and `schema_version` for each metadata file (world-spec@1, rule-ir@1, curriculum@1, materializer-protocol@1, assurance@1, telemetry-release-summary@1, fidelity@1)
   - Skip ALL cross-digest re-derivation (lines 2616-2957): shared_tool_digest verification, world_rule_digest verification, difficulty_digest verification, recipe_digest verification, reward/termination digest verification, verification_digest verification, assurance coverage verification, envpkg cross-check, telemetry field validation
   - Keep the `envpkg.toml` basic key check (just verify keys exist, not values)
2. Replace `_cold_verify` (123 lines, 2960-3082) with ~15-line version:
   - Check `integration.get("status") == "passed"`
   - Check `package_manifest["artifact_refs"]` keys match expected ref names
   - Skip full metadata re-derivation and comparison (the most expensive part, lines 3001-3072)
3. Simplify `_manifest_shape` (59 lines, 2431-2489) to ~25 lines: verify required top-level keys exist, skip per-field deep type checks.
4. Simplify `_compile_telemetry` (71 lines, 1983-2053) to ~35 lines: collect operations from work records, skip category_counts/model_counts aggregation.
5. Update `tests/test_direct_release.py`: tests that rely on full cold-read verification will need adjustment. The `_cold_read_package` function itself stays, just its internal `_verify_package_metadata` call becomes lighter.

**Compiles after**: Yes. All function signatures remain the same; only the validation depth changes.

---

## Files NOT Recommended for Cutting

### design.py (2678 lines) — ALL CORE
Every function in design.py is on the generate->registry path:
- Research nodes (906-1211): acquire/synthesize evidence
- Architecture/tools/rules/curriculum/tasks nodes (1211-2414): the 7 design LLM nodes
- Compiler functions (415-721): name-based rule IR compilation — explicitly protected by task constraints
- Projection helpers (`_binding_fields_for_llm`, `_rules_for_llm`, `_tools_rules_for_llm`): LLM-facing projections — explicitly protected

### contracts.py (1199 lines) — ALL CORE
Every dataclass is part of the frozen type contract. The `from_value`/`json_value`/`digest_value` helpers are load-bearing for serialization. No removable code found.

### runtime.py (916 lines) — ALL CORE
The candidate process execution engine. `_run_recipe`, `integrate`, `judge`, `materialize` are the actual E2E execution path. The `_safe` function (27 lines) has authority-field checking — could be simplified in theory but it's a safety boundary, not over-built.

### artifacts.py (498 lines) — ALL CORE
Content-addressed storage with secret-safety checks. Already minimal. The `_assert_safe` / `_SECRET_PATTERNS` checks are safety-critical, not over-built.

### invocation.py (459 lines) — ALL CORE
The LLM boundary. `_bundle_digest` (16 lines) verifies skill integrity — complex but load-bearing for the agent invocation guarantee.

### config.py (147 lines) — ALL CORE
Minimal TOML loader. Only possible cut: `trusted_wheel_store` field (handled in step 2).

### graph.py core (after resume removal) — ALL CORE
`NodeSpec`, `EdgeSpec`, `GraphRunner.execute`, `NodeResult`, `NodeExecutionError`, graph definitions — all load-bearing for the node transaction model. Only resume helpers are removable.

---

## Risk Assessment

### LOW risk (651 lines total): observe.py + resume infra + cli.py + foundry imports
These remove features that are genuinely not needed for minimal E2E:
- observe CLI subcommand (not called during generate)
- --resume/--from (testing convenience, not core E2E)
- Zero chance of breaking the generate->registry path.

### MED risk (488 lines): supply_chain.py simplification
Changes runtime behavior: integration and judge will use `sys.executable` instead of an isolated venv.
- If the candidate is truly stdlib-only: zero functional impact.
- If the candidate has third-party deps: they would need to be available in the system Python. This is acceptable for minimal scope per user mandate ("minimal functionality, no over-design").
- SBOM becomes a constant `{"entries": []}` — downstream metadata that references SBOM will still work but with empty dependency closure.

### MED-HIGH risk (536 lines): candidate.py verification simplification
Removes defense-in-depth re-verification of package contents.
- The package node builds the zip from verified artifacts.
- The registry node currently re-derives and compares ALL metadata from scratch.
- Simplifying means trusting the in-flight package more.
- If there's a bug in the package builder, the simplified registry won't catch it.
- For a minimal foundry where the same process builds and registers: acceptable risk.
- For a production registry serving untrusted packages: NOT acceptable.

### Highest-risk single cut: `_verify_package_metadata` simplification (358 lines)
This function currently catches bugs in the package builder by re-deriving every digest. Simplifying it means the registry trusts the package builder's output. The package builder was recently rewritten (name-based projections) and its tests pass, but real E2E coverage of the full package path is limited (per memory notes, no run has reached release_assurance yet). **Flag: verify with at least one full E2E generate->registry run after this cut.**

---

## Test File Impact Summary

| Test File | Lines | Action | Reason |
|---|---|---|---|
| test_supply_chain.py | 358 | DELETE | Tests the wheel admission machinery being removed |
| test_resume.py | 465 | SIMPLIFY | Keep `from_value` round-trip tests (4 tests), delete resume/compute_upstream tests (8 tests) |
| test_artifacts_observe.py | 212 | SPLIT | Keep 4 artifact tests as test_artifacts.py, delete 5 observe tests |
| test_direct_release.py | ~1200 | UPDATE | Tests calling `_cold_read_package` will still work; tests asserting specific verification error codes from `_verify_package_metadata` may need code updates |
| test_direct_runtime.py | ~500 | NO CHANGE | Tests runtime.py which is not cut |
| test_design_semantics.py | ~400 | NO CHANGE | Tests design.py which is not cut |
| test_graph_contracts.py | ~600 | NO CHANGE | Tests graph.py core (not resume infra) |
| test_legacy_firewall.py | ~60 | NO CHANGE | Static path checks |
| test_agent_route_config.py | ~100 | NO CHANGE | Tests config.py |

---

## Caveats

1. **supply_chain stub is the riskiest behavioral change**: switching from isolated venv to `sys.executable` changes what Python the candidate process uses. If the candidate code imports anything outside stdlib, it must be installed in the system Python. This is fine for the minimal stdlib-only scope but would break if deps are later added.

2. **Verification simplification hides package builder bugs**: The current `_verify_package_metadata` + `_cold_verify` act as a second pair of eyes on the package builder's output. Removing them means bugs in `_package_metadata` or `_package_bytes` won't be caught until the package is used by a consumer. Recommend keeping at least basic schema_version checks.

3. **No E2E validation possible yet**: Per memory, no generate run has reached registry publication. The cut plan is based on code reading, not runtime validation. The implementer should run at least one full E2E after cuts to verify.

4. **Line counts are approximate**: The "lines saved" figures assume clean replacement. Actual savings depend on how the simplified functions are written. The buffer (1680 identified vs 1416 needed) provides margin.

5. **_cold_read_package stays**: It is called from `_registry:1727` and from test_direct_release.py. It's the entry point for the cold-read verification. Even simplified, it stays as the function that opens the zip and extracts metadata. Only its internal `_verify_package_metadata` call becomes lighter.
