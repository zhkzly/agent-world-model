"""Run the real invocation-audit CLI path with a controlled blocking worker.

This fixture changes only the private worker entry point for a test process.
The audit still resolves a real profile, constructs the production router and
control plane, and uses the production CLI dispatch path.  It is never a
model-success fixture and is not imported by production code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repository = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repository))

    import agent_world.invocation.audit as audit
    from agent_world.control.telemetry import TelemetryStore
    from agent_world.invocation.codex_sdk import CodexSdkBackend

    worker = Path(os.environ["AGENT_WORLD_TEST_BLOCKING_WORKER"]).resolve(strict=True)

    class BlockingWorkerCodexBackend(CodexSdkBackend):
        def __init__(
            self,
            *,
            max_concurrent_invocations: int = 1,
            telemetry: TelemetryStore | None = None,
        ) -> None:
            super().__init__(
                max_concurrent_invocations=max_concurrent_invocations,
                telemetry=telemetry,
            )
            self._worker_path = worker

    audit.__dict__["CodexSdkBackend"] = BlockingWorkerCodexBackend
    from agent_world.cli import main as cli_main

    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
