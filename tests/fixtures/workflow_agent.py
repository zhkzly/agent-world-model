import json
import sys


payload = json.loads(sys.stdin.read() or "{}")
stage = payload.get("stage", "")
purpose = payload.get("node_purpose", "")
inputs = payload.get("input_artifact_ids", [])

if purpose == "review":
    artifact_id = inputs[0] if inputs else ""
    text = json.dumps(
        {
            "alignment_status": "pass",
            "reviewed_artifact_ids": [artifact_id],
            "drift_findings": [],
            "required_fixes": [],
            "waived_risks": [],
            "reviewer_note": f"process review for {stage}",
        },
        sort_keys=True,
    )
else:
    text = f"process output for {stage}:{purpose}"

print(
    json.dumps(
        {
            "text": text,
            "evidence_refs": [f"process://workflow-agent/{stage}/{purpose}"],
            "output_artifact_ids": [],
            "trace_ref": f"process://workflow-agent/{stage}/{purpose}",
            "status": "pass",
        },
        sort_keys=True,
    )
)
