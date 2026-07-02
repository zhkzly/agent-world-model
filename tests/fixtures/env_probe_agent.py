import json
import os
import sys


json.loads(sys.stdin.read() or "{}")
print(
    json.dumps(
        {
            "text": json.dumps({"has_secret": "OPENAI_API_KEY" in os.environ}),
            "evidence_refs": ["process://env-probe-agent"],
            "trace_ref": "process://env-probe-agent/stdout",
            "status": "pass",
        }
    )
)
