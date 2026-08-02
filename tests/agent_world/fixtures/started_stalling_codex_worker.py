"""Controlled child proving post-progress Codex stream liveness recovery.

The fixture consumes the normal trusted worker payload, writes only its own
PID below the resolved workspace, emits one valid Provider event, then ignores
SIGTERM.  It is not an Agent/code-generation substitute: the test exercises
the production parent, process-group cleanup, protocol parser, and Invocation
Control record after a stream has demonstrably started.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

PROTOCOL_VERSION = "agent-world.codex-worker.v1"


def main() -> None:
    payload = json.loads(sys.stdin.buffer.readline())
    workspace = Path(payload["workspace"])
    (workspace / ".started-stalling-worker-pid").write_text(str(os.getpid()), encoding="utf-8")
    records = (
        {
            "type": "lifecycle",
            "protocol_version": PROTOCOL_VERSION,
            "phase": "sdk_session_open",
        },
        {
            "type": "event",
            "protocol_version": PROTOCOL_VERSION,
            "event": {
                "sequence": 0,
                "method": "turn/started",
                "payload": {"kind": "provider_progress"},
            },
        },
    )
    for record in records:
        sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
