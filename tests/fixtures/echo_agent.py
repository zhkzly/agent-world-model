import json
import sys


payload = json.loads(sys.stdin.read() or "{}")
print(
    json.dumps(
        {
            "text": f"echo:{payload.get('stage')}:{payload.get('node_purpose')}",
            "evidence_refs": ["process://echo-agent"],
            "output_artifact_ids": [],
            "trace_ref": "process://echo-agent/stdout",
            "status": "pass",
        }
    )
)
