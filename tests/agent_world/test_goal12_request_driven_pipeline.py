import hashlib
import json
from pathlib import Path

from agent_world import library_lending
from agent_world.agents import AgentBackendRegistry, AgentResult, MockAgentBackend
from agent_world.generated_bundle import run_packaged_generated_bundle_check
from agent_world.pipeline import (
    PipelineNode,
    PipelineRunConfig,
    PipelineRunner,
    project_board_lite_node_registry,
    request_driven_node_registry,
    run_request_driven_pipeline,
)
from agent_world.request_driven import (
    BOOKING_AGENT_BUNDLE_ID,
    BOOKING_ENVIRONMENT_ID,
    GENERATED_FILE_KINDS,
    generated_implementation_record,
    run_summary,
    write_booking_agent_candidate_files,
)


BOOKING_REQUEST = "生成一个订票服务环境，支持演出/航班/活动查询、座位余量、座位暂占、预订确认、支付状态、取消和退款释放座位。"
INVENTORY_REPLENISHMENT_REQUEST = "生成一个库存补货管理环境，支持查询商品库存、创建补货请求、审批补货、入库更新库存、取消补货请求，并能验证库存状态变化。"
LIBRARY_LENDING_REQUEST = "生成一个图书馆借阅管理环境，支持搜索图书、查询可借副本、为读者借书、归还图书、逾期罚金记录，以及只读查询可用副本数量。"


def test_goal12_booking_raw_request_runs_selector_and_releases_booking_envpkg(tmp_path):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(run_id="goal12-booking", output_dir=tmp_path, raw_request=BOOKING_REQUEST)
    )

    assert record.status == "pass"
    assert context.artifacts["DomainPlan"]["domain_seed"] == BOOKING_ENVIRONMENT_ID
    assert context.artifacts["StrategySelection"]["selection_status"] == "selected"
    assert context.artifacts["ReleaseManifest"]["environment_id"] == BOOKING_ENVIRONMENT_ID
    assert context.artifacts["ReleaseManifest"]["environment_id"] != "project-board-lite"
    assert context.artifacts["ReleaseManifest"]["request_lineage"]["domain_plan_ref"] == context.artifacts["DomainPlan"]["id"]
    assert context.artifacts["ReleaseManifest"]["request_lineage"]["generated_bundle_ref"] == context.artifacts["GeneratedEnvironmentBundle"]["id"]
    assert context.artifacts["ReleaseManifest"]["request_lineage"]["independent_verification_report_ref"] == context.artifacts["IndependentVerificationReport"]["id"]

    package_dir = tmp_path / "envpkg"
    runtime_index_path = package_dir / "release" / "generated-runtime-index.yaml"
    runtime_dir = package_dir / "runtime" / "generated" / context.artifacts["GeneratedEnvironmentBundle"]["id"]
    assert runtime_index_path.is_file()
    assert runtime_dir.is_dir()
    files_by_name = {Path(item["path"]).name: item for item in context.artifacts["GeneratedEnvironmentBundle"]["generated_files"]}
    assert set(files_by_name) == set(GENERATED_FILE_KINDS)
    for filename, record_file in files_by_name.items():
        packaged = runtime_dir / filename
        assert packaged.is_file()
        assert _sha256(packaged) == record_file["sha256"]

    independent = context.artifacts["IndependentVerificationReport"]
    assert independent["success"] is True
    assert independent["positive_record_count"] >= 3
    assert independent["negative_record_count"] >= 3
    assert set(independent["verified_task_ids"]) == {"booking-task-1", "booking-task-2", "booking-task-3"}
    assert {item["task_id"] for item in independent["task_records"]} == {"booking-task-1", "booking-task-2", "booking-task-3"}

    packaged_check = run_packaged_generated_bundle_check(package_dir)
    assert packaged_check["success"] is True
    assert {item["task_id"] for item in packaged_check["independent_task_records"]} == {"booking-task-1", "booking-task-2", "booking-task-3"}

    summary = run_summary(context)
    assert [item["artifact_type"] for item in summary["artifact_flow"]] == [
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "SourceEvidenceIndex",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
        "FeasibilityReport",
        "ImplementationRequest",
        "GeneratedEnvironmentBundle",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]
    assert summary["environment_id"] == BOOKING_ENVIRONMENT_ID


def test_goal12_english_booking_request_does_not_match_library_book_substring(tmp_path):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            run_id="goal12-english-booking",
            output_dir=tmp_path,
            raw_request=(
                "Generate a booking reservation service environment for event search, seat availability, "
                "temporary holds, booking confirmation, payment status, cancellation, refund, and deterministic state verification."
            ),
        )
    )

    assert record.status == "pass"
    assert context.artifacts["DomainPlan"]["domain_seed"] == BOOKING_ENVIRONMENT_ID
    assert context.artifacts["ReleaseManifest"]["environment_id"] == BOOKING_ENVIRONMENT_ID


def test_goal12_new_library_lending_request_runs_full_pipeline_and_packaged_check(tmp_path):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(run_id="goal12-library", output_dir=tmp_path, raw_request=LIBRARY_LENDING_REQUEST)
    )

    assert record.status == "pass"
    assert context.artifacts["DomainPlan"]["domain_seed"] == library_lending.LIBRARY_ENVIRONMENT_ID
    assert context.artifacts["ReleaseManifest"]["environment_id"] == library_lending.LIBRARY_ENVIRONMENT_ID
    assert context.artifacts["ReleaseManifest"]["environment_id"] not in {BOOKING_ENVIRONMENT_ID, "project-board-lite"}
    assert context.artifacts["GeneratedEnvironmentBundle"]["id"] == library_lending.LIBRARY_DETERMINISTIC_BUNDLE_ID

    package_dir = tmp_path / "envpkg"
    packaged_check = run_packaged_generated_bundle_check(package_dir)
    assert packaged_check["success"] is True
    assert {item["task_id"] for item in packaged_check["independent_task_records"]} == set(library_lending.LIBRARY_TASK_IDS)

    repeated_check = run_packaged_generated_bundle_check(package_dir)
    assert repeated_check["success"] is True

    summary = run_summary(context)
    assert summary["environment_id"] == library_lending.LIBRARY_ENVIRONMENT_ID
    assert [item["artifact_type"] for item in summary["artifact_flow"]] == [
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "SourceEvidenceIndex",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
        "FeasibilityReport",
        "ImplementationRequest",
        "GeneratedEnvironmentBundle",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]


def test_goal12_s0_s11_artifacts_have_lineage(tmp_path):
    _, context = run_request_driven_pipeline(PipelineRunConfig(output_dir=tmp_path, raw_request=BOOKING_REQUEST))

    for artifact_type in [
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "SourceEvidenceIndex",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
        "FeasibilityReport",
        "ImplementationRequest",
        "GeneratedEnvironmentBundle",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]:
        artifact = context.artifacts[artifact_type]
        assert artifact["producer"]
        assert artifact["produced_by"] == artifact["producer"]
        assert artifact["consumed_inputs"] == artifact["inputs"]
        if artifact_type != "DomainPlan":
            assert artifact["inputs"], artifact_type


def test_goal12_project_board_registry_with_booking_request_is_not_goal12_success(tmp_path):
    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(output_dir=tmp_path, raw_request=BOOKING_REQUEST)
    )

    assert record.status == "pass"
    assert context.artifacts["ReleaseManifest"]["environment_id"] == "project-board-lite"
    assert "DomainPlan" not in context.artifacts
    assert not _is_goal12_success(context)


def test_goal12_non_booking_request_is_blocked_not_mapped_to_booking(tmp_path):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(output_dir=tmp_path, raw_request=INVENTORY_REPLENISHMENT_REQUEST)
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S1"
    assert context.artifacts["DomainPlan"]["domain_seed"] == "unsupported-request"
    assert context.artifacts["DomainPlan"]["planning_status"] == "unsupported"
    assert "取消" in context.artifacts["DomainPlan"]["planner_evidence"]["matched_supporting_terms"]
    assert context.artifacts["DomainPlan"]["planner_evidence"]["matched_domain_terms"] == []
    assert context.artifacts["StrategySelection"]["selection_status"] == "unsupported"
    assert context.repair_failure_packets
    assert context.repair_failure_packets[-1]["stage"] == "S1"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_source_failure_writes_failure_packet_and_stops_before_release(tmp_path):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request=BOOKING_REQUEST,
            env={"AGENT_WORLD_REQUEST_SOURCE_STRATEGY": "none"},
        )
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S1"
    assert context.repair_failure_packets
    assert context.repair_failure_packets[-1]["stage"] == "S1"
    assert context.repair_failure_packets[-1]["failure_class"]
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_forged_booking_check_replay_is_rejected_before_release(tmp_path):
    registry = request_driven_node_registry()
    registry.register(
        PipelineNode(
            node_id="request-driven-booking-forged-check-replay",
            stage="IMPLEMENT",
            artifact_type="CodeImplementation",
            input_artifact_types=["ImplementationRequest"],
            output_artifact_type="CodeImplementation",
            allowed_agent_backend=True,
            factory=lambda context: generated_implementation_record(context, forge_check_success=True),
        )
    )

    record, context = PipelineRunner(registry).run(PipelineRunConfig(output_dir=tmp_path, raw_request=BOOKING_REQUEST))

    assert record.status == "fail"
    assert record.failure_class == "independent_generated_bundle_verification_failed"
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert context.artifacts["IndependentVerificationReport"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_booking_bounded_repair_retries_agent_candidate_and_releases(tmp_path):
    backend = RepairingBookingCodegenBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request=BOOKING_REQUEST,
            implementation_mode="agent",
            max_repair_attempts=1,
        ),
        agent_registry=registry,
    )

    assert record.status == "pass"
    assert len(backend.requests) == 2
    assert [item["attempt_index"] for item in context.build_check_replay_records] == [1, 2]
    assert context.build_check_replay_records[0]["status"] == "fail"
    assert context.build_check_replay_records[1]["status"] == "pass"
    assert len(context.repair_failure_packets) == 1
    repair_packet = context.repair_failure_packets[0]
    assert repair_packet["stage"] == "IMPLEMENT"
    assert "booking-task-1" in repair_packet["failed_task_ids"]
    assert repair_packet["manifest_contract"]["candidate_dir"] == "generated"
    assert repair_packet["manifest_contract"]["generated_file_kinds"]["runtime.py"] == "runtime_code"
    assert "not generated/runtime.py" in repair_packet["manifest_contract"]["path_rule"]
    assert "runtime.py" in repair_packet["candidate"]["generated_paths"]
    assert all(not path.startswith(str(tmp_path)) for path in repair_packet["candidate"]["generated_paths"])
    assert "Previous failure packet JSON" in backend.requests[1].instruction
    assert "Keep candidate_manifest.json paths relative to candidate_dir" in backend.requests[1].instruction
    assert context.artifacts["GeneratedEnvironmentBundle"]["id"] == BOOKING_AGENT_BUNDLE_ID
    assert context.artifacts["ReleaseManifest"]["environment_id"] == BOOKING_ENVIRONMENT_ID


def test_goal12_booking_agent_candidate_ignores_python_bytecode_cache(tmp_path):
    backend = BookingCodegenWithPycacheBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request=BOOKING_REQUEST,
            implementation_mode="agent",
        ),
        agent_registry=registry,
    )

    assert record.status == "pass"
    assert context.artifacts["GeneratedEnvironmentBundle"]["id"] == BOOKING_AGENT_BUNDLE_ID
    assert context.artifacts["ReleaseManifest"]["environment_id"] == BOOKING_ENVIRONMENT_ID


def test_goal12_booking_bounded_repair_exhaustion_stops_before_release(tmp_path):
    backend = RepairingBookingCodegenBackend(always_fail=True)
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request=BOOKING_REQUEST,
            implementation_mode="agent",
            max_repair_attempts=1,
        ),
        agent_registry=registry,
    )

    assert record.status == "fail"
    assert record.failure_class == "generated_bundle_check_failed"
    assert len(backend.requests) == 2
    assert len(context.repair_failure_packets) == 2
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


class BookingCodegenWithPycacheBackend(MockAgentBackend):
    def invoke(self, request, config):
        work_dir = Path(request.permissions["filesystem_root"])
        manifest = write_booking_agent_candidate_files(
            work_dir,
            source_refs=request.input_artifact_ids,
            implementation_request_id=request.input_artifact_ids[0],
        )
        pycache = work_dir / "__pycache__"
        pycache.mkdir(exist_ok=True)
        (pycache / "runtime.cpython-312.pyc").write_bytes(b"python bytecode cache")
        return AgentResult(
            text=json.dumps(manifest, sort_keys=True),
            evidence_refs=["mock://booking-pycache-candidate"],
            output_artifact_ids=[manifest["bundle_id"]],
            trace_ref="mock://trace/booking-pycache-candidate",
        )


class RepairingBookingCodegenBackend(MockAgentBackend):
    def __init__(self, *, always_fail: bool = False) -> None:
        super().__init__()
        self.requests = []
        self.always_fail = always_fail

    def invoke(self, request, config):
        self.requests.append(request)
        work_dir = Path(request.permissions["filesystem_root"])
        manifest = write_booking_agent_candidate_files(
            work_dir,
            source_refs=request.input_artifact_ids,
            implementation_request_id=request.input_artifact_ids[0],
        )
        if self.always_fail or len(self.requests) == 1:
            (work_dir / "verifier.py").write_text(
                "def verify_task_completion(*args, **kwargs):\n"
                "    return {'success': False, 'checks': [{'name': 'forced_failure', 'passed': False}]}\n",
                encoding="utf-8",
            )
            manifest = _manifest_from_files(work_dir, request.input_artifact_ids)
        return AgentResult(
            text=json.dumps(manifest, sort_keys=True),
            evidence_refs=[f"mock://booking-repair-attempt-{len(self.requests)}"],
            output_artifact_ids=[manifest["bundle_id"]],
            trace_ref=f"mock://trace/booking-repair-attempt-{len(self.requests)}",
        )


def _manifest_from_files(work_dir: Path, source_refs: list[str]) -> dict[str, object]:
    return {
        "candidate_dir": ".",
        "bundle_id": BOOKING_AGENT_BUNDLE_ID,
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "generated_files": [
            {
                "path": filename,
                "kind": kind,
                "sha256": _sha256(work_dir / filename),
                "source_refs": source_refs,
            }
            for filename, kind in GENERATED_FILE_KINDS.items()
        ],
        "runtime_entrypoint": "runtime.BookingServiceLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in ["booking-task-1", "booking-task-2", "booking-task-3"]],
    }


def _is_goal12_success(context) -> bool:
    release = context.artifacts.get("ReleaseManifest", {})
    return (
        release.get("environment_id") == BOOKING_ENVIRONMENT_ID
        and "DomainPlan" in context.artifacts
        and "StrategySelection" in context.artifacts
        and context.artifacts.get("StrategySelection", {}).get("selection_status") == "selected"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
