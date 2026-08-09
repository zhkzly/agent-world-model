from __future__ import annotations

import subprocess
import sys

import agent_world


def test_clean_break_package_imports() -> None:
    assert agent_world.__version__ == "0.3.0"


def test_public_module_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_world.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Clean-break Direct environment foundry." in result.stdout
    assert "{generate,observe,check-config}" in result.stdout
