"""Private subprocess entry point for the Builder's standard loader smoke."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from agent_env_foundry.environment import load_environment


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    if len(arguments) != 2:
        print("usage: python -m agent_env_foundry._smoke RELEASE_ROOT", file=sys.stderr)
        return 2
    release_root = Path(arguments[1]).resolve()
    sys.path.insert(0, str(release_root / "src"))
    with tempfile.TemporaryDirectory(
        prefix="agent-env-foundry-smoke-instance-",
        dir=release_root.parent,
    ) as temporary:
        environment = load_environment(release_root, Path(temporary) / "instance")
        try:
            observation = environment.reset(None)
            tools = environment.tools()
            if not tools:
                print("environment tools() returned an empty catalog", file=sys.stderr)
                return 1
        finally:
            environment.close()
    print(
        "environment_load_ok "
        + json.dumps(
            {"observation_type": type(observation).__name__, "tool_count": len(tools)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
