"""JSON control plane for the production Agent World Foundry."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from agent_world.app import (
    ApplicationConfigurationError,
    build_application,
    open_campaigns,
    open_consumption,
    open_direct_runs,
    open_observability,
    open_registry,
    open_telemetry,
)
from agent_world.config import ConfigError, FoundryConfig, load_foundry_config
from agent_world.consumer import LocalConsumerError
from agent_world.contracts import (
    ArtifactRef,
    CapabilityAggregateSignal,
    CurriculumSamplingPolicy,
    PermissionScope,
    RolloutAction,
    SuiteSelectionRequest,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control import (
    DirectJobAlreadyRunningError,
    DirectJobResumeRequiredError,
    DirectJobStoreError,
    DirectRequestConflictError,
)
from agent_world.control.semantic_prefix import (
    SemanticPrefixError,
    SemanticPrefixRunner,
)
from agent_world.control.test_node import (
    DiagnosticDescendantNodeRunner,
    DiagnosticFinalNodeRunner,
    DiagnosticPlanDerivedDesignNodeRunner,
    DiagnosticSuccessorNodeRunner,
    DiagnosticTaskCurriculumJoinRunner,
    DiagnosticTaskRequirementNodeRunner,
    DiagnosticWorldPlanNodeRunner,
    TestNodeError,
    TestNodeRunner,
)
from agent_world.doctor import run_doctor
from agent_world.invocation.audit import INVOCATION_AUDIT_LANE_IDS, run_invocation_audit
from agent_world.observability import ObservabilityError
from agent_world.registry import RegistryError

EXIT_OK = 0
EXIT_OPERATION_FAILED = 1
EXIT_NOT_RELEASED = 2
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-world",
        description=(
            "Generate, independently verify, and publish real executable Agent environments."
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "explicit TOML config (default: AGENT_WORLD_CONFIG or "
            "~/.config/agent-world/config.toml)"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="preflight real production dependencies")
    doctor.add_argument(
        "--live-agent",
        action="store_true",
        help="spend one real Codex SDK structured-output turn",
    )
    doctor.add_argument(
        "--live-research",
        action="store_true",
        help="spend one real search/fetch/extract probe",
    )
    doctor.add_argument(
        "--production",
        action="store_true",
        help="run both live probes; only this can report production_ready=true",
    )

    invocation_audit = commands.add_parser(
        "invocation-audit",
        help=(
            "exercise each distinct real Direct/Codex invocation mechanism without semantic output"
        ),
    )
    invocation_audit.add_argument(
        "--lane",
        action="append",
        choices=INVOCATION_AUDIT_LANE_IDS,
        help="run one named invocation lane (repeatable; default runs every lane sequentially)",
    )
    invocation_audit.add_argument(
        "--structured-output-transport",
        choices=("provider_schema", "json_envelope", "json_object"),
        help=(
            "diagnostic-only override for resolved structured profiles; workspace Agent lanes "
            "retain their native provider-schema transport"
        ),
    )

    test_node = commands.add_parser(
        "test-node",
        help="copy one captured scope and genuinely rerun exactly one frozen WorkGraph node",
    )
    test_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_node.add_argument(
        "target_coordinate",
        help=(
            "exact coordinate key/JSON, component|stage|artifact_slot|group_id|shard_id, "
            "or the component.stage.artifact_slot label shown by observe"
        ),
    )
    test_node.add_argument(
        "--source-state-root",
        metavar="PATH",
        help="captured state root to copy; defaults to the configured state root",
    )
    test_node.add_argument(
        "--proposal-llm-tokens",
        metavar="TOKENS",
        type=int,
        help=(
            "freeze one new diagnostic graph with this larger finite Agent proposal "
            "output-token budget before rerunning the captured target"
        ),
    )
    test_node.add_argument(
        "--proposal-wall-seconds",
        metavar="SECONDS",
        type=float,
        help=(
            "freeze the same new diagnostic graph with this larger finite Agent wall "
            "budget, including coupled Builder time leases when applicable"
        ),
    )
    test_node.add_argument(
        "--refresh-current-implementation",
        action="store_true",
        help=(
            "freeze one new diagnostic definition that records the selected node's current "
            "Prompt/Runtime-Skill/leaf/compiler revision while retaining its frozen input "
            "closure and proposal budget"
        ),
    )
    test_node.add_argument(
        "--diagnostic-structured-output-transport",
        choices=("provider_schema", "json_envelope", "json_object"),
        help=(
            "freeze one profile-only diagnostic definition and run the copied node under this "
            "different structured-output transport; cannot combine with another diagnostic change"
        ),
    )
    test_node.add_argument(
        "--diagnostic-model",
        metavar="MODEL",
        help=(
            "freeze one model-only diagnostic profile definition; requires "
            "--diagnostic-source-model and cannot combine with another diagnostic change"
        ),
    )
    test_node.add_argument(
        "--diagnostic-source-model",
        metavar="MODEL",
        help="explicit source model for one --diagnostic-model experiment",
    )
    test_successor_node = commands.add_parser(
        "test-successor-node",
        help=(
            "derive one fresh semantic successor from a marked test-node Architecture "
            "commit and genuinely dispatch only that new node"
        ),
    )
    test_successor_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_successor_node.add_argument(
        "target_coordinate",
        help=(
            "exact new shared-tool or ToolSemantics coordinate; accepts exact key/JSON, "
            "pipe label, or the label shown by observe"
        ),
    )
    test_successor_node.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help="one marked .agent-world-live/test-node-* copy produced by test-node",
    )

    test_descendant_node = commands.add_parser(
        "test-descendant-node",
        help=(
            "dispatch one already-frozen unheaded descendant below a marked diagnostic "
            "commit using the real Scheduler"
        ),
    )
    test_descendant_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_descendant_node.add_argument(
        "target_coordinate",
        help=(
            "exact unheaded frozen successor coordinate; accepts exact key/JSON, pipe label, "
            "or the component.stage.artifact_slot label shown by observe"
        ),
    )
    test_descendant_node.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help="one marked .agent-world-live/test-node-* copy with a committed direct parent",
    )
    test_descendant_node.add_argument(
        "--manifest-revision",
        metavar="SHA256",
        help=(
            "select one exact frozen WorkGraph manifest revision when the coordinate appears "
            "in more than one retained diagnostic topology"
        ),
    )
    test_descendant_node.add_argument(
        "--proposal-llm-tokens",
        metavar="TOKENS",
        type=int,
        help=(
            "create one new diagnostic graph with this larger finite Agent proposal "
            "output-token budget; the frozen source manifest is never edited"
        ),
    )
    test_descendant_node.add_argument(
        "--proposal-wall-seconds",
        metavar="SECONDS",
        type=float,
        help=(
            "create the same new diagnostic graph with this larger finite Agent wall "
            "budget, including coupled Builder time leases when applicable"
        ),
    )
    test_descendant_node.add_argument(
        "--infrastructure-retry",
        action="store_true",
        help=(
            "after a same-route liveness check, authorize exactly one fresh physical attempt "
            "for the exact failed retryable diagnostic definition; no prompt, input, Skill, "
            "or proposal-envelope change is allowed"
        ),
    )
    test_descendant_node.add_argument(
        "--execute-authorized-repair",
        action="store_true",
        help=(
            "execute exactly one already-authorized semantic RepairAction through the normal "
            "Scheduler; retains its frozen definition, feedback, Prompt, Runtime Skill, "
            "profile, and envelope"
        ),
    )
    test_descendant_node.add_argument(
        "--authorize-semantic-repair",
        action="store_true",
        help=(
            "record exactly one feedback-bound semantic RepairAction for an actionable failed "
            "diagnostic node; makes no model call and must be followed by the separate "
            "--execute-authorized-repair command"
        ),
    )
    test_descendant_node.add_argument(
        "--diagnostic-terminal-feedback",
        action="store_true",
        help=(
            "make one feedback-only diagnostic definition with the same frozen Agent input, "
            "Prompt, Skill, and envelope; write any redacted terminal excerpt locally"
        ),
    )
    test_descendant_node.add_argument(
        "--refresh-current-implementation",
        action="store_true",
        help=(
            "freeze one new diagnostic definition that records the selected descendant's "
            "current Prompt/Runtime-Skill/leaf/compiler revision while retaining its frozen "
            "input closure and proposal budget"
        ),
    )
    test_descendant_node.add_argument(
        "--diagnostic-structured-output-transport",
        choices=("provider_schema", "json_envelope", "json_object"),
        help=(
            "freeze one profile-only diagnostic definition and run the descendant under this "
            "different structured-output transport; cannot combine with another diagnostic change"
        ),
    )
    test_descendant_node.add_argument(
        "--diagnostic-model",
        metavar="MODEL",
        help=(
            "freeze one model-only diagnostic profile definition; requires "
            "--diagnostic-source-model and cannot combine with another diagnostic change"
        ),
    )
    test_descendant_node.add_argument(
        "--diagnostic-source-model",
        metavar="MODEL",
        help="explicit source model for one --diagnostic-model experiment",
    )

    test_world_plan_node = commands.add_parser(
        "test-world-plan-node",
        help=(
            "migrate one marked legacy WorldRules diagnostic closure to the compact "
            "CurriculumPlan topology and genuinely dispatch only that new plan node"
        ),
    )
    test_world_plan_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_world_plan_node.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help=(
            "one marked .agent-world-live/test-node-* copy with committed legacy WorldRules "
            "and an unheaded historical TaskCurriculum tail"
        ),
    )
    test_world_plan_node.add_argument(
        "--manifest-revision",
        metavar="SHA256",
        help=(
            "select one exact frozen legacy WorkGraph manifest when retained diagnostic "
            "topologies reuse the historical TaskCurriculum coordinate"
        ),
    )

    test_task_requirement_node = commands.add_parser(
        "test-task-requirement-node",
        help=(
            "derive the frozen plan-owned TaskRequirement fan-out and genuinely dispatch "
            "exactly one selected task-family node"
        ),
    )
    test_task_requirement_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_task_requirement_node.add_argument(
        "task_type",
        help="one exact task type declared by the committed CurriculumPlan",
    )
    test_task_requirement_node.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help=(
            "one marked .agent-world-live/test-node-* copy with a committed CurriculumPlan "
            "World epoch"
        ),
    )

    test_task_curriculum_join = commands.add_parser(
        "test-task-curriculum-join",
        help=(
            "dispatch the exact deterministic TaskCurriculum join below a committed "
            "Plan-derived TaskRequirement closure"
        ),
    )
    test_task_curriculum_join.add_argument("scope_id", help="captured WorkGraph scope id")
    test_task_curriculum_join.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help=(
            "one marked .agent-world-live/test-node-* copy with committed CurriculumPlan "
            "and every plan-derived TaskRequirement"
        ),
    )

    test_plan_derived_design_node = commands.add_parser(
        "test-plan-derived-design-node",
        help=(
            "dispatch one exact deterministic TaskCurriculum, ModelingBoundary, or "
            "VerifierPlan node from the committed Plan-derived Design epoch"
        ),
    )
    test_plan_derived_design_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_plan_derived_design_node.add_argument(
        "target_stage",
        choices=("task_curriculum", "modeling_boundary", "verifier_plan"),
        help=(
            "one closed deterministic tail stage; the framework selects the exact "
            "Plan-derived manifest rather than accepting a caller-supplied revision"
        ),
    )
    test_plan_derived_design_node.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help=(
            "one marked .agent-world-live/test-node-* copy with the committed parents "
            "of the requested Plan-derived tail node"
        ),
    )

    test_final_node = commands.add_parser(
        "test-final-node",
        help=(
            "freeze the exact final graph from a committed diagnostic Design and VerifierPlan "
            "closure, then genuinely dispatch one independent initial implementation-plan or "
            "Challenger node"
        ),
    )
    test_final_node.add_argument("scope_id", help="captured WorkGraph scope id")
    test_final_node.add_argument(
        "target_stage",
        choices=("implementation_plan", "verifier_intent_batch"),
        help=(
            "one initial final-graph boundary; batch selection is derived from the persisted "
            "VerifierPlan"
        ),
    )
    test_final_node.add_argument(
        "--batch-index",
        metavar="INDEX",
        type=int,
        help="1-based frozen VerifierPlan batch index; required only for verifier_intent_batch",
    )
    test_final_node.add_argument(
        "--diagnostic-state-root",
        metavar="PATH",
        required=True,
        help=(
            "one marked .agent-world-live/test-node-* copy with committed plan-derived "
            "ModelingBoundary and VerifierPlan"
        ),
    )
    test_final_node.add_argument(
        "--proposal-llm-tokens",
        metavar="TOKENS",
        type=int,
        help=(
            "compile a new diagnostic-only final WorkDefinition for the selected Agent node "
            "with this larger finite rollout-token budget; it is not a retry of the source "
            "definition"
        ),
    )
    test_final_node.add_argument(
        "--proposal-wall-seconds",
        metavar="SECONDS",
        type=float,
        help=(
            "compile the same new diagnostic-only final WorkDefinition with this larger finite "
            "wall budget, up to the configured Direct-generation budget"
        ),
    )

    semantic_prefix = commands.add_parser(
        "semantic-prefix",
        help=(
            "run a fresh normal Direct prefix through ModelingBoundary and "
            "VerifierPlan without starting Build, Judge, or Registry"
        ),
    )
    semantic_prefix.add_argument(
        "--need",
        required=True,
        help="natural-language environment need for the staged semantic closure",
    )
    semantic_prefix.add_argument(
        "--request-id",
        help="optional identity for this fresh staged prefix",
    )

    generate = commands.add_parser(
        "generate",
        help="turn one natural-language need into a judged Registry release",
    )
    generate.add_argument("--need", required=True, help="natural-language environment need")
    generate.add_argument(
        "--request-id",
        help=(
            "durable idempotency key: identical completed requests return the original result; "
            "different inputs conflict"
        ),
    )
    generate.add_argument(
        "--no-discovery",
        action="store_true",
        help="disable the separately budgeted discovery lane for this run",
    )

    run = commands.add_parser(
        "run",
        help="inspect durable Direct Generation progress without model credentials",
    )
    run_commands = run.add_subparsers(dest="run_command", required=True)
    run_inspect = run_commands.add_parser(
        "inspect",
        help="return the current snapshot, attempts, and typed progress events",
    )
    run_inspect.add_argument("request_id")
    run_inspect.add_argument(
        "--metrics",
        action="store_true",
        help="include hierarchical spans, resource usage, and critical-path metrics",
    )
    run_resume = run_commands.add_parser(
        "resume",
        help="resume a failed Direct Generation from its last verified phase checkpoint",
    )
    run_resume.add_argument("request_id")

    observe = commands.add_parser(
        "observe",
        help="read bounded, secret-screened durable WorkAttempt diagnostics",
    )
    observe_commands = observe.add_subparsers(dest="observe_command", required=True)
    observe_scene = observe_commands.add_parser(
        "scene",
        help="read the current scope map and rebuild a stale cache from durable facts",
    )
    observe_scene.add_argument("scope_id", nargs="?")
    observe_scene.add_argument("--latest", action="store_true")
    observe_coordinate = observe_commands.add_parser(
        "coordinate",
        help="read one current coordinate terrain view",
    )
    observe_coordinate.add_argument("scope_id")
    observe_coordinate.add_argument("coordinate")
    observe_subprocess = observe_commands.add_parser(
        "subprocess",
        help="read one correlated Runtime subprocess crash scene",
    )
    observe_subprocess.add_argument("scope_id")
    observe_subprocess.add_argument("coordinate")
    observe_candidate = observe_commands.add_parser(
        "candidate",
        help="read the exact generated source file targeted by a failed gate",
    )
    observe_candidate.add_argument("scope_id")
    observe_candidate.add_argument("coordinate")
    observe_contract = observe_commands.add_parser(
        "contract",
        help="read the frozen WorldSpec surface and verifier expectations",
    )
    observe_contract.add_argument("scope_id")
    observe_contract.add_argument("coordinate")
    observe_rebuild = observe_commands.add_parser(
        "rebuild",
        help="force a Tier A scene rebuild from durable heads and Tier B events",
    )
    observe_rebuild.add_argument("scope_id", nargs="?")
    observe_rebuild.add_argument("--latest", action="store_true")
    observe_frontier_diff = observe_commands.add_parser(
        "frontier-diff",
        help="compare two retained unresolved frontiers for one coordinate",
    )
    observe_frontier_diff.add_argument("scope_id")
    observe_frontier_diff.add_argument("coordinate")
    observe_frontier_diff.add_argument(
        "--from",
        dest="from_attempt_ordinal",
        type=int,
        metavar="N",
    )
    observe_frontier_diff.add_argument(
        "--to",
        dest="to_attempt_ordinal",
        type=int,
        metavar="N",
    )
    observe_compare = observe_commands.add_parser(
        "compare",
        help="compare first diverging coordinate status across two scopes",
    )
    observe_compare.add_argument(
        "--scope",
        dest="scope_ids",
        action="append",
        required=True,
        metavar="SCOPE",
    )
    observe_replay = observe_commands.add_parser(
        "replay",
        help="reconstruct compact terminal attempt history from Tier B telemetry",
    )
    observe_replay.add_argument("scope_id")
    observe_replay.add_argument("coordinate")

    metrics = commands.add_parser(
        "metrics",
        help="inspect or export credential-free operational telemetry",
    )
    metrics_commands = metrics.add_subparsers(dest="metrics_command", required=True)
    metrics_status = metrics_commands.add_parser("status", help="show telemetry store health")
    metrics_status.add_argument("--trace-id", help="optionally inspect one exact trace")
    metrics_export = metrics_commands.add_parser("export", help="export one exact trace")
    metrics_export.add_argument("--trace-id", required=True)
    metrics_export.add_argument("--format", choices=("json", "parquet"), required=True)
    metrics_export.add_argument("--output", required=True)
    metrics_summarize = metrics_commands.add_parser(
        "summarize",
        help="summarize distributions across one or more exact traces",
    )
    metrics_summarize.add_argument("--trace-id", action="append", required=True)
    metrics_compare = metrics_commands.add_parser(
        "compare",
        help="compare traces against the first trace as an explicit baseline",
    )
    metrics_compare.add_argument("--trace-id", action="append", required=True)

    experiment = commands.add_parser(
        "experiment",
        help="freeze reproducible metrics and Artifact roots for paper experiments",
    )
    experiment_commands = experiment.add_subparsers(
        dest="experiment_command",
        required=True,
    )
    experiment_snapshot = experiment_commands.add_parser(
        "snapshot",
        help="create one immutable Direct-run experiment snapshot",
    )
    experiment_snapshot.add_argument("request_id")

    discovery = commands.add_parser(
        "discovery",
        help="resume separately budgeted Discovery work without reopening Direct Generation",
    )
    discovery_commands = discovery.add_subparsers(dest="discovery_command", required=True)
    discovery_resume = discovery_commands.add_parser(
        "resume",
        help="resume one durable deferred lane under the configured Discovery budget",
    )
    discovery_resume.add_argument("discovery_run_id")

    expand = commands.add_parser(
        "expand",
        help="run optional tool-first search over released EnvironmentPackages",
    )
    expand_commands = expand.add_subparsers(dest="expand_command", required=True)
    expand_start = expand_commands.add_parser("start", help="start a durable Campaign")
    expand_start.add_argument(
        "--anchor",
        action="append",
        required=True,
        metavar="PACKAGE_ID@VERSION",
        help="repeat for each exact released semantic parent",
    )
    expand_start.add_argument(
        "--target",
        action="append",
        required=True,
        metavar="DIMENSION",
        help="repeat for each desired coverage dimension",
    )
    expand_start.add_argument(
        "--campaign-id",
        required=True,
        help="stable durable idempotency/recovery key chosen before external work starts",
    )
    expand_start.add_argument(
        "--policy",
        choices=("random-search", "wide-search", "evolutionary-archive"),
        help="replaceable ask/tell selection strategy",
    )
    expand_start.add_argument("--seed", type=int, help="non-negative deterministic search seed")
    expand_start.add_argument(
        "--inbox-revision",
        help="exact sha256 revision id of a frozen Discovery ExpansionInbox",
    )
    expand_start.add_argument(
        "--source",
        action="append",
        metavar="SOURCE_ID",
        help=(
            "repeat to select configured evidence Sources; defaults to configured "
            "default_source_ids"
        ),
    )
    expand_start.add_argument(
        "--feedback-revision",
        action="append",
        metavar="SHA256_REVISION",
        help="repeat for exact frozen consumer.capability_feedback artifacts",
    )
    expand_resume = expand_commands.add_parser("resume", help="resume a durable Campaign")
    expand_resume.add_argument("campaign_id")
    expand_inspect = expand_commands.add_parser(
        "inspect",
        help="inspect Campaign state without model credentials",
    )
    expand_inspect.add_argument("campaign_id")

    registry = commands.add_parser("registry", help="inspect released EnvironmentPackages")
    registry_commands = registry.add_subparsers(dest="registry_command", required=True)
    registry_list = registry_commands.add_parser("list", help="list Registry releases")
    registry_list.add_argument("--package-id", help="filter by exact package id")
    registry_list.add_argument(
        "--status",
        action="append",
        choices=("released", "quarantined", "superseded"),
        help="repeat to include multiple statuses",
    )
    registry_inspect = registry_commands.add_parser(
        "inspect",
        help="verify and return one exact Registry release",
    )
    registry_inspect.add_argument("package_id")
    registry_inspect.add_argument("version")
    registry_inspect.add_argument("--digest", help="require an exact package digest")

    suite = commands.add_parser(
        "suite",
        help="freeze and consume exact released EnvironmentPackages",
    )
    suite_commands = suite.add_subparsers(dest="suite_command", required=True)
    suite_create = suite_commands.add_parser(
        "create",
        help="atomically create an immutable EnvironmentSuiteSnapshot",
    )
    suite_create.add_argument(
        "--package",
        action="append",
        required=True,
        metavar="PACKAGE_ID@VERSION[=WEIGHT]",
        help="repeat for each exact release; WEIGHT is a positive decimal",
    )
    suite_create.add_argument(
        "--max-steps",
        type=int,
        default=128,
        help="framework truncation limit frozen into each curriculum policy",
    )
    suite_inspect = suite_commands.add_parser(
        "inspect",
        help="verify and return one immutable Suite snapshot",
    )
    suite_inspect.add_argument("snapshot_id")
    suite_start = suite_commands.add_parser(
        "start",
        help="start, reset, and inspect one real deterministic episode",
    )
    suite_start.add_argument("snapshot_id")
    suite_start.add_argument("--seed", required=True, type=int)
    suite_rollout = suite_commands.add_parser(
        "rollout",
        help="reconstruct a deterministic episode and run supplied actions in fresh isolation",
    )
    suite_rollout.add_argument("snapshot_id")
    suite_rollout.add_argument("--seed", required=True, type=int)
    suite_rollout.add_argument(
        "--action",
        action="append",
        required=True,
        metavar="TOOL_ID=JSON_OBJECT",
        help="repeat actions in episode order",
    )

    feedback = commands.add_parser(
        "feedback",
        help="record optional aggregate capability signals against an immutable Suite",
    )
    feedback_commands = feedback.add_subparsers(dest="feedback_command", required=True)
    feedback_record = feedback_commands.add_parser(
        "record",
        help="validate and persist one Registry-bound CapabilityFeedback aggregate",
    )
    feedback_record.add_argument("snapshot_id")
    feedback_record.add_argument(
        "--signal",
        action="append",
        required=True,
        metavar="JSON_OBJECT",
        help=(
            "repeat one closed aggregate signal; raw tasks, trajectories, verifier data, "
            "and Oracle data are not accepted"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        _write_error("interrupted", "operation interrupted")
        return EXIT_INTERRUPTED
    except ApplicationConfigurationError as exc:
        _write_error("application_configuration", str(exc))
        return EXIT_OPERATION_FAILED
    except ConfigError:
        # Pydantic/TOML diagnostics can echo rejected input.  Do not risk printing
        # a credential that was accidentally placed under an unknown key.
        _write_error("configuration", "Foundry configuration is missing or invalid")
        return EXIT_OPERATION_FAILED
    except DirectRequestConflictError as exc:
        _write_error("direct_request_conflict", str(exc))
        return EXIT_OPERATION_FAILED
    except DirectJobAlreadyRunningError as exc:
        _write_error("direct_request_in_progress", str(exc))
        return EXIT_OPERATION_FAILED
    except DirectJobResumeRequiredError as exc:
        _write_error("direct_resume_required", str(exc))
        return EXIT_OPERATION_FAILED
    except DirectJobStoreError:
        _write_error("direct_state_integrity", "Direct Generation state is invalid or unavailable")
        return EXIT_OPERATION_FAILED
    except RegistryError as exc:
        _write_error("registry", str(exc))
        return EXIT_OPERATION_FAILED
    except LocalConsumerError as exc:
        _write_error(exc.code, str(exc))
        return EXIT_OPERATION_FAILED
    except ObservabilityError as exc:
        _write_error(exc.code, str(exc))
        return EXIT_OPERATION_FAILED
    except TestNodeError as exc:
        _write_error(exc.code, str(exc))
        return EXIT_OPERATION_FAILED
    except SemanticPrefixError as exc:
        _write_error(exc.code, str(exc))
        return EXIT_OPERATION_FAILED
    except Exception as exc:  # fail closed without exposing backend/auth exception text
        _write_error("operation_failed", f"operation failed ({type(exc).__name__})")
        return EXIT_OPERATION_FAILED


async def _dispatch(args: argparse.Namespace) -> int:
    config = load_foundry_config(args.config)
    if args.command == "doctor":
        doctor_report = await run_doctor(
            config,
            live_agent=args.live_agent or args.production,
            live_research=args.live_research or args.production,
        )
        _write_json(doctor_report)
        return EXIT_OK if doctor_report.ok else EXIT_OPERATION_FAILED
    if args.command == "invocation-audit":
        audit_report = await run_invocation_audit(
            config,
            lane_ids=tuple(args.lane or ()),
            structured_output_transport=args.structured_output_transport,
        )
        _write_json(audit_report)
        return EXIT_OK if audit_report.status == "passed" else EXIT_OPERATION_FAILED
    if args.command == "test-node":
        test_node_result = await TestNodeRunner(
            config=config,
            source_state_root=(
                Path(args.source_state_root) if args.source_state_root is not None else None
            ),
        ).run(
            scope_id=args.scope_id,
            target_coordinate=args.target_coordinate,
            proposal_llm_tokens=args.proposal_llm_tokens,
            proposal_wall_seconds=args.proposal_wall_seconds,
            refresh_current_implementation=args.refresh_current_implementation,
            diagnostic_structured_output_transport=args.diagnostic_structured_output_transport,
            diagnostic_model=args.diagnostic_model,
            diagnostic_source_model=args.diagnostic_source_model,
        )
        _write_json(test_node_result)
        return EXIT_OK
    if args.command == "test-successor-node":
        successor_result = await DiagnosticSuccessorNodeRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(
            scope_id=args.scope_id,
            target_coordinate=args.target_coordinate,
        )
        _write_json(successor_result)
        return EXIT_OK
    if args.command == "test-descendant-node":
        descendant_result = await DiagnosticDescendantNodeRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(
            scope_id=args.scope_id,
            target_coordinate=args.target_coordinate,
            proposal_llm_tokens=args.proposal_llm_tokens,
            proposal_wall_seconds=args.proposal_wall_seconds,
            required_manifest_revision=args.manifest_revision,
            infrastructure_retry=args.infrastructure_retry,
            execute_authorized_repair=args.execute_authorized_repair,
            authorize_semantic_repair=args.authorize_semantic_repair,
            diagnostic_terminal_feedback=args.diagnostic_terminal_feedback,
            refresh_current_implementation=args.refresh_current_implementation,
            diagnostic_structured_output_transport=args.diagnostic_structured_output_transport,
            diagnostic_model=args.diagnostic_model,
            diagnostic_source_model=args.diagnostic_source_model,
        )
        _write_json(descendant_result)
        return EXIT_OK
    if args.command == "test-world-plan-node":
        plan_result = await DiagnosticWorldPlanNodeRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(
            scope_id=args.scope_id,
            required_manifest_revision=args.manifest_revision,
        )
        _write_json(plan_result)
        return EXIT_OK
    if args.command == "test-task-requirement-node":
        task_requirement_result = await DiagnosticTaskRequirementNodeRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(
            scope_id=args.scope_id,
            task_type=args.task_type,
        )
        _write_json(task_requirement_result)
        return EXIT_OK
    if args.command == "test-task-curriculum-join":
        task_curriculum_join_result = await DiagnosticTaskCurriculumJoinRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(scope_id=args.scope_id)
        _write_json(task_curriculum_join_result)
        return EXIT_OK
    if args.command == "test-plan-derived-design-node":
        plan_derived_design_result = await DiagnosticPlanDerivedDesignNodeRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(
            scope_id=args.scope_id,
            target_stage=args.target_stage,
        )
        _write_json(plan_derived_design_result)
        return EXIT_OK
    if args.command == "test-final-node":
        final_node_result = await DiagnosticFinalNodeRunner(
            config=config,
            diagnostic_state_root=Path(args.diagnostic_state_root),
        ).run(
            scope_id=args.scope_id,
            target_stage=args.target_stage,
            batch_index=args.batch_index,
            proposal_llm_tokens=args.proposal_llm_tokens,
            proposal_wall_seconds=args.proposal_wall_seconds,
        )
        _write_json(final_node_result)
        return EXIT_OK
    if args.command == "semantic-prefix":
        prefix_result = await SemanticPrefixRunner(config=config).run(
            need=args.need,
            request_id=args.request_id,
            permissions=_job_permissions(config),
        )
        _write_json(prefix_result)
        return (
            EXIT_OK
            if prefix_result.run.status == "semantic_prefix_ready"
            else EXIT_OPERATION_FAILED
        )
    if args.command == "generate":
        app = build_application(config)
        generation_result = await app.controller.generate(
            args.need,
            request_id=args.request_id,
            permissions=_job_permissions(config),
            enable_discovery=not args.no_discovery,
        )
        _write_json(generation_result)
        return EXIT_OK if generation_result.status == "released" else EXIT_NOT_RELEASED
    if args.command == "run":
        if args.run_command == "inspect":
            _write_json(
                open_direct_runs(config).inspect(
                    args.request_id,
                    include_metrics=args.metrics,
                )
            )
            return EXIT_OK
        if args.run_command == "resume":
            app = build_application(config)
            resume_result = await app.controller.resume_generation(args.request_id)
            _write_json(resume_result)
            return EXIT_OK if resume_result.status == "released" else EXIT_NOT_RELEASED
        raise RuntimeError("unreachable run command")
    if args.command == "observe":
        reader = open_observability(config)
        if args.observe_command == "scene":
            scope_id = _observe_scope_id(args, reader)
            _write_json(reader.scene_payload(scope_id))
            return EXIT_OK
        if args.observe_command == "coordinate":
            _write_json(reader.coordinate(args.scope_id, args.coordinate))
            return EXIT_OK
        if args.observe_command == "subprocess":
            _write_json(reader.subprocess(args.scope_id, args.coordinate))
            return EXIT_OK
        if args.observe_command == "candidate":
            _write_json(reader.candidate(args.scope_id, args.coordinate))
            return EXIT_OK
        if args.observe_command == "contract":
            _write_json(reader.contract(args.scope_id, args.coordinate))
            return EXIT_OK
        if args.observe_command == "rebuild":
            scope_id = _observe_scope_id(args, reader)
            _write_json(reader.scene_payload(scope_id, force_rebuild=True))
            return EXIT_OK
        if args.observe_command == "frontier-diff":
            _write_json(
                reader.frontier_diff(
                    args.scope_id,
                    args.coordinate,
                    from_attempt_ordinal=args.from_attempt_ordinal,
                    to_attempt_ordinal=args.to_attempt_ordinal,
                )
            )
            return EXIT_OK
        if args.observe_command == "compare":
            if len(args.scope_ids) != 2:
                raise ObservabilityError(
                    "observe compare requires exactly two --scope values",
                    code="observability_selector_invalid",
                )
            _write_json(
                reader.compare(
                    baseline_scope_id=args.scope_ids[0],
                    candidate_scope_id=args.scope_ids[1],
                )
            )
            return EXIT_OK
        if args.observe_command == "replay":
            _write_json(reader.replay(args.scope_id, args.coordinate))
            return EXIT_OK
        raise RuntimeError("unreachable observe command")
    if args.command == "metrics":
        telemetry = open_telemetry(config)
        if args.metrics_command == "status":
            output = telemetry.health()
            if args.trace_id is not None:
                output["trace"] = telemetry.inspect_trace(args.trace_id)
            _write_json(output)
            return EXIT_OK
        if args.metrics_command == "export":
            if args.format == "json":
                path = telemetry.export_json(args.output, trace_id=args.trace_id)
            else:
                path = telemetry.export_parquet(args.output, trace_id=args.trace_id)
            _write_json({"trace_id": args.trace_id, "format": args.format, "path": str(path)})
            return EXIT_OK
        if args.metrics_command == "summarize":
            _write_json(telemetry.summarize_traces(args.trace_id))
            return EXIT_OK
        if args.metrics_command == "compare":
            _write_json(telemetry.compare_traces(args.trace_id))
            return EXIT_OK
        raise RuntimeError("unreachable metrics command")
    if args.command == "experiment":
        if args.experiment_command != "snapshot":
            raise RuntimeError("unreachable experiment command")
        projection = open_direct_runs(config).inspect(args.request_id)
        head = projection["head"]
        assert isinstance(head, dict)
        trace_id = str(head["run_id"])
        request_ref = ArtifactRef.model_validate(head["request_ref"])
        experiment_manifest = open_telemetry(config).create_experiment_snapshot(
            trace_ids=(trace_id,),
            code_revision=None,
            config_hash=sha256_digest(canonical_json_bytes(config.model_dump(mode="json"))),
            request_or_campaign_refs=(request_ref,),
        )
        _write_json(experiment_manifest)
        return EXIT_OK
    if args.command == "discovery":
        app = build_application(config)
        if args.discovery_command != "resume":
            raise RuntimeError("unreachable discovery command")
        discovery_result = await app.controller.resume_discovery(args.discovery_run_id)
        _write_json(discovery_result)
        return EXIT_OPERATION_FAILED if discovery_result.status == "failed" else EXIT_OK
    if args.command == "expand":
        if args.expand_command == "inspect":
            _write_json(open_campaigns(config).inspect(args.campaign_id))
            return EXIT_OK
        app = build_application(config)
        if args.expand_command == "start":
            if args.seed is not None and args.seed < 0:
                raise ValueError("Campaign seed must be non-negative")
            anchor_refs = tuple(_resolve_anchor(app, coordinate) for coordinate in args.anchor)
            inbox_ref = (
                _resolve_artifact_revision(
                    app,
                    args.inbox_revision,
                    expected_artifact_type="discovery.expansion_inbox_snapshot",
                )
                if args.inbox_revision is not None
                else None
            )
            feedback_refs = tuple(
                _resolve_artifact_revision(
                    app,
                    revision,
                    expected_artifact_type="consumer.capability_feedback",
                )
                for revision in (args.feedback_revision or ())
            )
            expansion_result = await app.controller.expand(
                anchor_package_refs=anchor_refs,
                target_coverage_dimensions=tuple(args.target),
                inbox_snapshot_ref=inbox_ref,
                source_ids=tuple(args.source) if args.source else None,
                feedback_refs=feedback_refs,
                campaign_id=args.campaign_id,
                policy_id=args.policy,
                campaign_seed=args.seed,
                permissions=_job_permissions(config),
            )
        elif args.expand_command == "resume":
            expansion_result = await app.controller.resume_expansion(args.campaign_id)
        else:
            raise RuntimeError("unreachable expand command")
        _write_json(expansion_result)
        return (
            EXIT_NOT_RELEASED
            if expansion_result.report.stop_reason in {"needs_human", "infrastructure_error"}
            else EXIT_OK
        )
    if args.command == "registry":
        registry = open_registry(config)
        if args.registry_command == "list":
            records = registry.list(
                package_id=args.package_id,
                statuses=args.status,
            )
            _write_json(
                {
                    "count": len(records),
                    "releases": [item.model_dump(mode="json") for item in records],
                }
            )
            return EXIT_OK
        if args.registry_command == "inspect":
            record = registry.inspect(
                args.package_id,
                args.version,
                package_digest=args.digest,
            )
            _write_json(record)
            return EXIT_OK
    if args.command == "suite":
        consumption = open_consumption(config)
        if args.suite_command == "create":
            policy = CurriculumSamplingPolicy(maximum_steps=args.max_steps)
            selections = tuple(
                _parse_suite_selection(value, policy=policy) for value in args.package
            )
            _write_json(consumption.registry.create_suite_snapshot(selections))
            return EXIT_OK
        if args.suite_command == "inspect":
            _write_json(consumption.registry.load_suite_snapshot(args.snapshot_id))
            return EXIT_OK
        if args.suite_command == "start":
            episode = await consumption.rollout.start(args.snapshot_id, seed=args.seed)
            try:
                start_result = episode.start_result()
            finally:
                await episode.close()
            _write_json(start_result)
            return EXIT_OK
        if args.suite_command == "rollout":
            actions = tuple(_parse_rollout_action(value) for value in args.action)
            rollout_result = await consumption.rollout.rollout(
                args.snapshot_id,
                seed=args.seed,
                actions=actions,
            )
            _write_json(rollout_result)
            return EXIT_OK
    if args.command == "feedback":
        if args.feedback_command != "record":
            raise RuntimeError("unreachable feedback command")
        consumption = open_consumption(config)
        snapshot = consumption.registry.load_suite_snapshot(args.snapshot_id)
        signals = tuple(_parse_capability_signal(value) for value in args.signal)
        recorded = consumption.feedback.record(
            suite_snapshot_id=snapshot.snapshot_id,
            suite_snapshot_digest=snapshot.snapshot_digest,
            signals=signals,
        )
        _write_json(
            {
                "feedback": recorded.feedback.model_dump(mode="json"),
                "feedback_ref": recorded.feedback_ref.model_dump(mode="json"),
            }
        )
        return EXIT_OK
    raise RuntimeError("unreachable command dispatch")


def _parse_suite_selection(
    value: str,
    *,
    policy: CurriculumSamplingPolicy,
) -> SuiteSelectionRequest:
    coordinate, separator, raw_weight = value.partition("=")
    try:
        package_id, version = coordinate.rsplit("@", 1)
    except ValueError as exc:
        raise ValueError("Suite package must use PACKAGE_ID@VERSION[=WEIGHT]") from exc
    if not package_id or not version or (separator and not raw_weight):
        raise ValueError("Suite package must use PACKAGE_ID@VERSION[=WEIGHT]")
    try:
        weight = Decimal(raw_weight) if separator else Decimal("1")
    except InvalidOperation as exc:
        raise ValueError("Suite package weight must be a positive decimal") from exc
    return SuiteSelectionRequest(
        package_id=package_id,
        version=version,
        weight=weight,
        curriculum_policy=policy,
    )


def _parse_rollout_action(value: str) -> RolloutAction:
    tool_id, separator, raw_arguments = value.partition("=")
    if not separator or not tool_id or not raw_arguments:
        raise ValueError("rollout action must use TOOL_ID=JSON_OBJECT")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("rollout action arguments must be valid JSON") from exc
    if not isinstance(arguments, dict):
        raise ValueError("rollout action arguments must be a JSON object")
    return RolloutAction(tool_id=tool_id, arguments=arguments)


def _parse_capability_signal(value: str) -> CapabilityAggregateSignal:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("capability signal must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("capability signal must be a JSON object")
    return TypeAdapter(CapabilityAggregateSignal).validate_python(payload)


def _job_permissions(config: FoundryConfig) -> PermissionScope:
    handles = (
        (config.research.jina_credential_handle,)
        if config.research.jina_api_key_environment is not None
        else ()
    )
    dependency_domains = config.agent.engineer_dependency_network_domains
    network_domains = tuple(sorted({"*", *dependency_domains})) if dependency_domains else ()
    return PermissionScope(
        network_domains=network_domains,
        credential_handles=handles,
    )


def _observe_scope_id(args: argparse.Namespace, reader: Any) -> str:
    """Resolve the two explicitly supported scene selectors without guessing."""

    scope_id = getattr(args, "scope_id", None)
    latest = bool(getattr(args, "latest", False))
    if latest and scope_id is not None:
        raise ObservabilityError(
            "use either one scope id or --latest",
            code="observability_selector_invalid",
        )
    if latest:
        return reader.latest_scope_id()
    if isinstance(scope_id, str) and scope_id:
        return scope_id
    raise ObservabilityError(
        "one scope id or --latest is required",
        code="observability_selector_invalid",
    )


def _resolve_anchor(app: Any, coordinate: str) -> Any:
    try:
        package_id, version = coordinate.rsplit("@", 1)
    except ValueError as exc:
        raise ValueError("anchor must use PACKAGE_ID@VERSION") from exc
    if not package_id or not version:
        raise ValueError("anchor must use PACKAGE_ID@VERSION")
    return app.registry.inspect(package_id, version).manifest_ref


def _resolve_artifact_revision(
    app: Any,
    revision_id: str,
    *,
    expected_artifact_type: str,
) -> Any:
    matches = tuple(ref for ref in app.artifacts.list_revisions() if ref.revision_id == revision_id)
    if len(matches) != 1:
        raise ValueError("revision does not resolve to one exact artifact")
    selected = matches[0]
    if selected.artifact_type != expected_artifact_type:
        raise ValueError(f"revision must reference an exact {expected_artifact_type} artifact")
    return selected


def _write_json(value: BaseModel | dict[str, Any]) -> None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def _write_error(code: str, message: str) -> None:
    sys.stderr.write(
        json.dumps(
            {"error": {"code": code, "message": message}},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
