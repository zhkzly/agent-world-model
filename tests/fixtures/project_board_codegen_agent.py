import json
import sys
from pathlib import Path

from agent_world.fixtures.project_board_lite_codegen import write_project_board_agent_candidate_files


payload = json.loads(sys.stdin.read() or "{}")
work_dir = Path(payload["permissions"]["filesystem_root"])
manifest = write_project_board_agent_candidate_files(
    work_dir,
    source_refs=payload.get("input_artifact_ids") or ["process-agent-source-ref"],
    implementation_request_id=(payload.get("input_artifact_ids") or ["impl-project-board-lite-first-slice"])[0],
)
print(
    json.dumps(
        {
            "text": json.dumps(manifest, sort_keys=True),
            "evidence_refs": ["process://project-board-codegen-agent"],
            "output_artifact_ids": ["bundle-project-board-lite-agent-generated"],
            "trace_ref": "process://project-board-codegen-agent/stdout",
            "status": "pass",
        }
    )
)
