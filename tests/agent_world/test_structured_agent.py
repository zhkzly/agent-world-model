from pathlib import Path
from types import SimpleNamespace

from agent_world.executors.structured_agent import _fields_for_stage
from agent_world.pipeline import _agent_work_dir


def test_s8_llm_feasibility_review_is_advisory_only():
    context = _context(
        KnowledgePack={"uncertainties": []},
        TaskSet={"tasks": [{"task_id": "task_001_create_alert"}]},
        VerifierPlan={"verifiers": [{"verifier_id": "verifier_task_001_create_alert"}]},
    )

    fields = _fields_for_stage(
        context,
        "S8",
        {
            "status": "needs_human",
            "summary": "Semantic risks remain, but upstream gates passed.",
        },
    )

    assert fields["status"] == "pass"
    assert fields["implementation_blockers"] == []
    assert fields["llm_feasibility_review"]["status"] == "needs_human"
    assert fields["advisory_implementation_risks"] == [
        {
            "source": "llm_feasibility_review",
            "reason": "Semantic risks remain, but upstream gates passed.",
            "blocking": False,
        }
    ]


def test_agent_work_dir_is_absolute_for_relative_output_dir():
    context = SimpleNamespace(
        store=SimpleNamespace(root=Path("outputs/relative-pipeline-store")),
        config=SimpleNamespace(run_id="pipeline-run-request-driven"),
    )

    work_dir = _agent_work_dir(context, "env/task handoff")

    assert work_dir.is_absolute()
    assert work_dir.as_posix().endswith("/outputs/relative-pipeline-store/build/agent-runs/pipeline-run-request-driven/env-task-handoff")


class _Context(SimpleNamespace):
    def artifact(self, name):
        return self.artifacts[name]


def _context(**artifacts):
    return _Context(artifacts=artifacts, gate_records=[])
