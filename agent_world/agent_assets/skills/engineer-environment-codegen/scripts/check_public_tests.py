#!/usr/bin/env python3
"""Run Candidate public tests from a clean frozen offline project copy.

This is a local Code-Agent preflight.  It intentionally mirrors the framework
Candidate boundary: ``uv sync --offline --frozen --no-install-project`` first,
then one direct Python process per declared Candidate-relative public test. It
reports stable, value-free failure classes and never forwards test output.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

_PUBLIC_TEST_RUNNER = r"""from __future__ import annotations

import os
import runpy
import sys
from pathlib import PurePosixPath


def fail(message: str, exit_code: int = 70) -> None:
    sys.stderr.write(message + "\n")
    raise SystemExit(exit_code)


if len(sys.argv) != 2:
    fail("public-test preflight requires exactly one candidate-relative test path")
relative = PurePosixPath(sys.argv[1])
if relative.is_absolute() or not relative.parts or ".." in relative.parts or "\\" in sys.argv[1]:
    fail("public-test preflight received an invalid candidate-relative test path")
workspace = os.environ.get("AGENT_WORLD_CANDIDATE_WORKSPACE")
if not workspace:
    fail("public-test preflight has no Candidate workspace")
test_path = os.path.join(workspace, *relative.parts)
if not os.path.isfile(test_path):
    fail("public-test preflight could not find the declared test file")
for import_root in (os.path.join(workspace, "src"), workspace):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)
sys.argv = [relative.as_posix()]
runpy.run_path(test_path, run_name="__main__")
"""


def _test_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in raw:
        raise ValueError("public-test path must be Candidate-relative POSIX text")
    return path


def _failure_code(result: subprocess.CompletedProcess[str]) -> str:
    text = f"{result.stderr}\n{result.stdout}"
    if "ModuleNotFoundError: No module named" in text:
        return "public_test_import_unavailable"
    if "AssertionError" in text:
        return "public_test_assertion_failed"
    return "public_test_failed"


def _run(
    command: list[str], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def check_public_tests(workspace: Path, test_paths: tuple[PurePosixPath, ...]) -> int:
    candidate = workspace / "candidate"
    if not candidate.is_dir() or candidate.is_symlink():
        print("ERROR candidate_workspace_invalid path=candidate expected=real_project_directory")
        return 1

    with tempfile.TemporaryDirectory(prefix="agent-world-public-test-preflight-") as temporary:
        temporary_root = Path(temporary)
        clean_candidate = temporary_root / "candidate"
        try:
            shutil.copytree(candidate, clean_candidate)
        except OSError:
            print(
                "ERROR candidate_copy_failed "
                "path=candidate expected=readable_regular_project_tree"
            )
            return 1

        environment = dict(os.environ)
        environment["UV_PROJECT_ENVIRONMENT"] = str(temporary_root / "venv")
        try:
            sync = _run(
                ["uv", "sync", "--offline", "--frozen", "--no-install-project"],
                cwd=clean_candidate,
                environment=environment,
            )
        except OSError:
            print("ERROR uv_unavailable expected=normal_host_uv")
            return 1
        if sync.returncode != 0:
            print("ERROR public_tests_offline_sync_failed expected=frozen_offline_project_sync")
            return 1

        runner_path = temporary_root / "public-test-runner.py"
        runner_path.write_text(_PUBLIC_TEST_RUNNER, encoding="utf-8")
        python = temporary_root / "venv" / "bin" / "python"
        for test_path in test_paths:
            test_file = clean_candidate.joinpath(*test_path.parts)
            if not test_file.is_file():
                print(
                    "ERROR public_test_missing "
                    f"path={test_path.as_posix()} expected=regular_candidate_test_file"
                )
                return 1
            test_environment = dict(environment)
            test_environment["AGENT_WORLD_CANDIDATE_WORKSPACE"] = str(clean_candidate)
            result = _run(
                [str(python), str(runner_path), test_path.as_posix()],
                cwd=clean_candidate,
                environment=test_environment,
            )
            if result.returncode != 0:
                print(
                    f"ERROR {_failure_code(result)} path={test_path.as_posix()} "
                    "expected=direct_frozen_public_test_pass"
                )
                return 1

    print(f"OK candidate-public-tests count={len(test_paths)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--test", action="append", required=True, dest="tests")
    args = parser.parse_args(argv)
    try:
        test_paths = tuple(_test_path(raw) for raw in args.tests)
    except ValueError as exc:
        parser.error(str(exc))
    return check_public_tests(args.workspace.resolve(), test_paths)


if __name__ == "__main__":
    raise SystemExit(main())
