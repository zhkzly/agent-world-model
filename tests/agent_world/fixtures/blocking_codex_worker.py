"""Controlled child used to prove parent-side Codex worker recovery.

It is intentionally not a model substitute or a success fixture.  The parent
passes it the real trusted worker payload, it proves payload dispatch by
writing only its own PID below the resolved workspace, emits one safe local
lifecycle frame, then ignores graceful termination so the real process-group
cleanup has to converge through its declared kill grace.
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
    (workspace / ".blocking-worker-pid").write_text(str(os.getpid()), encoding="utf-8")
    record = {
        "type": "lifecycle",
        "protocol_version": PROTOCOL_VERSION,
        "phase": "sdk_session_open",
    }
    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
