"""Mechanical CLI behavior; no fake path can claim a released environment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_env_foundry.cli as cli_module
from agent_env_foundry.publication import PublicationError


def test_verify_release_reports_typed_failure_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = tmp_path / "invalid.zip"
    release.write_bytes(b"invalid")
    monkeypatch.setattr(
        cli_module,
        "_verify_path",
        lambda _path: (_ for _ in ()).throw(
            PublicationError("verification", "qualification_invalid", "summary invalid")
        ),
    )

    exit_code = cli_module.main(["verify-release", "--release", str(release)])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "not_verified",
        "phase": "verification",
        "code": "qualification_invalid",
        "message": "summary invalid",
    }


def test_verify_release_rejects_malformed_zip_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = tmp_path / "invalid.zip"
    release.write_bytes(b"not a zip")

    exit_code = cli_module.main(["verify-release", "--release", str(release)])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "not_verified"
    assert output["phase"] == "extraction"
    assert output["code"] == "zip_invalid"
