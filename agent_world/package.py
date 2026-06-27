from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_world.artifacts import write_jsonl, write_yaml
from agent_world.fixtures.support_desk_lite import create_seed_db


@dataclass(frozen=True)
class PackageAssemblyResult:
    package_dir: Path
    written_files: list[Path]


class PackageAssembler:
    """Writes the surface-neutral first-slice package layout."""

    def assemble(
        self,
        *,
        output_dir: Path,
        artifacts: dict[str, dict[str, Any]],
        gate_records: list[dict[str, Any]],
        review_records: list[dict[str, Any]],
        agent_invocations: list[dict[str, Any]],
    ) -> PackageAssemblyResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        def dump_yaml(relative: str, value: Any) -> None:
            path = output_dir / relative
            write_yaml(path, value)
            written.append(path)

        dump_yaml("package.yaml", artifacts["EnvironmentPackagePlan"])
        dump_yaml("sources/evidence-index.yaml", artifacts["SourceEvidenceIndex"])
        dump_yaml("spec/need.yaml", artifacts["NeedSpec"])
        dump_yaml("spec/knowledge-pack.yaml", artifacts["KnowledgePack"])
        dump_yaml("spec/environment.yaml", artifacts["EnvironmentSpec"])
        dump_yaml("spec/logical-tools.yaml", {"logical_tools": artifacts["EnvironmentSpec"]["logical_tools"]})
        dump_yaml("spec/tool-graph.yaml", artifacts["LogicalToolGraph"])
        dump_yaml("spec/tasks.yaml", artifacts["TaskSet"])
        dump_yaml("spec/surfaces.yaml", artifacts["SurfacePlan"])
        dump_yaml("spec/verifiers.yaml", artifacts["VerifierPlan"])
        dump_yaml("spec/feasibility.yaml", artifacts["FeasibilityReport"])
        dump_yaml("spec/implementation-request.yaml", artifacts["ImplementationRequest"])
        dump_yaml("spec/package-plan.yaml", artifacts["EnvironmentPackagePlan"])
        dump_yaml("checks/agent-backend-config.yaml", artifacts["AgentBackendConfig"])
        dump_yaml("checks/static-gates.yaml", {"stage_gates": artifacts["EnvironmentPackagePlan"]["static_check_refs"]})
        dump_yaml("checks/gate-records.yaml", {"gate_records": gate_records})
        dump_yaml("checks/review-records.yaml", {"review_records": review_records})
        dump_yaml("checks/replay-plan.yaml", artifacts["ReplayPlan"])
        dump_yaml("release/release-manifest.yaml", artifacts["ReleaseManifest"])
        dump_yaml("release/consumer-index.yaml", artifacts["ConsumerIndex"])

        invocations_path = output_dir / "checks/agent-invocations.jsonl"
        write_jsonl(invocations_path, agent_invocations)
        written.append(invocations_path)
        surface_traces_path = output_dir / "checks/surface-traces.jsonl"
        write_jsonl(surface_traces_path, [])
        written.append(surface_traces_path)
        task_records_path = output_dir / "release/task-records.jsonl"
        write_jsonl(task_records_path, artifacts["TaskSet"]["tasks"])
        written.append(task_records_path)
        verifier_records_path = output_dir / "release/verifier-records.jsonl"
        write_jsonl(verifier_records_path, artifacts["VerifierPlan"]["verifiers"])
        written.append(verifier_records_path)

        seed_path = create_seed_db(output_dir / "fixtures/seed/support-desk-lite.sqlite")
        written.append(seed_path)
        (output_dir / "fixtures/positive").mkdir(parents=True, exist_ok=True)
        (output_dir / "fixtures/negative").mkdir(parents=True, exist_ok=True)
        return PackageAssemblyResult(package_dir=output_dir, written_files=written)


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
