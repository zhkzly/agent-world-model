from pathlib import Path
from types import SimpleNamespace

from agent_world.pipeline import _agent_work_dir, request_driven_node_registry
from agent_world.strategies import attempt_profile_for_stage


def test_s8_feasibility_is_framework_deterministic():
    node = request_driven_node_registry().get("S8")

    assert node.execution_mode == "deterministic"
    assert node.factory is not None
    assert attempt_profile_for_stage("S8") is None


def test_agent_work_dir_is_absolute_for_relative_output_dir():
    context = SimpleNamespace(
        store=SimpleNamespace(root=Path("outputs/relative-pipeline-store")),
        config=SimpleNamespace(run_id="pipeline-run-request-driven"),
    )

    work_dir = _agent_work_dir(context, "env/task handoff")

    assert work_dir.is_absolute()
    assert work_dir.as_posix().endswith("/outputs/relative-pipeline-store/build/agent-runs/pipeline-run-request-driven/env-task-handoff")
