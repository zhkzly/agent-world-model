import json
from pathlib import Path

from agent_world.generated_project import _run_runtime_command


def test_packaged_runtime_command_creates_agent_output_dir(tmp_path):
    runtime_dir = tmp_path / "runtime" / "project"
    scripts_dir = runtime_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "self_check.py").write_text(
        "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "report = Path.cwd().parent / 'agent-output' / 'local_check_report.json'",
                "report.write_text(json.dumps({'success': True}) + '\\n', encoding='utf-8')",
                "print(json.dumps({'success': True}))",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_runtime_command(runtime_dir, ["python", "scripts/self_check.py"])

    assert result["success"] is True
    report = tmp_path / "runtime" / "agent-output" / "local_check_report.json"
    assert json.loads(report.read_text(encoding="utf-8")) == {"success": True}
