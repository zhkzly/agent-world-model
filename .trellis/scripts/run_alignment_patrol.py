#!/usr/bin/env python3
"""Collect a bounded harness review request and run a read-only Trellis Patrol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable


CHECK_IDS = ["F1", "F2", "F3", "F4", "F5"]
CHECK_STATUSES = {"PASS", "FAIL", "N/A", "UNDETERMINED"}
DECISIONS = {"ALLOW", "BLOCK", "ASK"}
HOOK_SOURCES = {"compact", "resume", "fork"}
CHECK_TRIGGERS = ("plan-document-write", "worker-turn", "transition")
RUNTIME_REL = Path(".trellis/.runtime/alignment")
DEFAULT_MAX_UNTRACKED_BYTES = 131_072
DEFAULT_TIMEOUT = "5m"


class PatrolError(RuntimeError):
    """Patrol collection or execution failed."""


class VerdictError(PatrolError):
    """Patrol output did not satisfy the closed verdict contract."""


class NoActiveTaskError(PatrolError):
    """A task-bound transition had no canonical active task."""


class TaskAuthorityError(PatrolError):
    """A caller-supplied task assertion did not match canonical authority."""


class CandidateTaskError(PatrolError):
    """A proposed planning task was invalid or escaped the task root."""


class UnsupportedTriggerError(PatrolError):
    """A public check requested a trigger outside the closed contract."""


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_bytes(data.encode("utf-8"))


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_text_artifact(
    path: Path, root: Path, max_bytes: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path.is_symlink():
        relative = path.relative_to(root).as_posix()
        target = os.fsencode(os.readlink(path))
        return None, {
            "path": relative,
            "reason": "symlink",
            "size": len(target),
            "sha256": _sha256_bytes(target),
        }
    relative = _relative(path, root)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, {"path": relative, "reason": f"read_error:{exc.__class__.__name__}"}
    fingerprint = {"size": len(data), "sha256": _sha256_bytes(data)}
    if len(data) > max_bytes:
        return None, {
            "path": relative,
            "reason": f"oversized:{len(data)}>{max_bytes}",
            **fingerprint,
        }
    if b"\0" in data:
        return None, {"path": relative, "reason": "binary", **fingerprint}
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, {"path": relative, "reason": "non_utf8", **fingerprint}
    return {"content": content, **fingerprint}, None


def _untracked_paths(repo_root: Path) -> list[Path]:
    result = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
    )
    paths: list[Path] = []
    for raw in result.stdout.split("\0"):
        if not raw:
            continue
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        path = repo_root / relative
        if relative.parts[:3] == (".trellis", ".runtime", "alignment"):
            continue
        if path.is_file() or path.is_symlink():
            paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(repo_root).as_posix())


def collect_git_state(
    repo_root: Path, *, max_untracked_bytes: int = DEFAULT_MAX_UNTRACKED_BYTES
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    status = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_root)
    unstaged = _run(["git", "diff", "--no-ext-diff", "--binary"], cwd=repo_root)
    staged = _run(["git", "diff", "--cached", "--no-ext-diff", "--binary"], cwd=repo_root)

    untracked: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, Any]] = []
    for path in _untracked_paths(repo_root):
        text, missing = _read_text_artifact(path, repo_root, max_untracked_bytes)
        relative = path.relative_to(repo_root).as_posix()
        if missing is not None:
            unavailable.append(missing)
        elif text is not None:
            untracked[relative] = text

    return {
        "status": status.stdout,
        "unstaged_diff": unstaged.stdout,
        "staged_diff": staged.stdout,
        "untracked": untracked,
        "unavailable": unavailable,
    }


def _authority_paths(
    repo_root: Path, task_dir: Path, *, include_task: bool = True
) -> list[Path]:
    paths = [
        repo_root / "PROJECT.md",
        repo_root / "DECISIONS.md",
    ]
    if include_task:
        paths.extend([task_dir / "prd.md", task_dir / "task.json"])
    return paths


def _snapshot_text_path(repo_root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(repo_root).as_posix()
    if path.is_symlink():
        raise PatrolError(f"review file must not be a symlink: {relative}")
    if not path.is_file():
        raise PatrolError(f"required review file missing: {relative}")
    try:
        data = path.read_bytes()
        content = data.decode("utf-8")
    except OSError as exc:
        raise PatrolError(
            f"review file unreadable: {relative}:{exc.__class__.__name__}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise PatrolError(f"review file was not UTF-8: {relative}") from exc
    return {"sha256": _sha256_bytes(data), "size": len(data), "content": content}


def _authority_snapshot(
    repo_root: Path, task_dir: Path, *, include_task: bool = True
) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for path in _authority_paths(repo_root, task_dir, include_task=include_task):
        relative = path.relative_to(repo_root).as_posix()
        snapshot[relative] = _snapshot_text_path(repo_root, path)
    return snapshot


def _candidate_task_snapshot(
    repo_root: Path, task_dir: Path
) -> dict[str, dict[str, Any]]:
    required = [task_dir / "task.json", task_dir / "prd.md"]
    optional = [task_dir / "design.md", task_dir / "implement.md"]
    snapshot: dict[str, dict[str, Any]] = {}
    for path in [*required, *[item for item in optional if item.exists()]]:
        snapshot[path.relative_to(repo_root).as_posix()] = _snapshot_text_path(
            repo_root, path
        )
    return snapshot


def _load_optional_files(
    paths: Iterable[Path], repo_root: Path, max_bytes: int
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    observed: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, Any]] = []
    for path in paths:
        resolved = path if path.is_absolute() else repo_root / path
        try:
            resolved.resolve().relative_to(repo_root.resolve())
        except ValueError as exc:
            raise PatrolError(f"evidence path escaped repository: {path}") from exc
        if not resolved.is_file():
            unavailable.append({"path": str(path), "reason": "missing"})
            continue
        text, missing = _read_text_artifact(resolved, repo_root, max_bytes)
        if missing is not None:
            unavailable.append(missing)
        elif text is not None:
            observed[_relative(resolved, repo_root)] = text
    return observed, unavailable


def build_request(
    repo_root: Path,
    trigger: str,
    transition: str,
    task_dir: Path,
    *,
    output_files: Iterable[Path] = (),
    evidence_files: Iterable[Path] = (),
    task_assertion: str | None = None,
    task_mode: str = "active",
    candidate_task_assertion: str | None = None,
    max_untracked_bytes: int = DEFAULT_MAX_UNTRACKED_BYTES,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    task_dir = task_dir.resolve()
    try:
        task_rel = task_dir.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise PatrolError("task directory escaped repository") from exc
    if not task_dir.is_dir():
        raise PatrolError(f"task directory did not exist: {task_rel}")
    if task_mode not in {"active", "candidate"}:
        raise PatrolError(f"invalid task mode: {task_mode}")

    outputs, output_unavailable = _load_optional_files(
        output_files, repo_root, max_untracked_bytes
    )
    evidence, evidence_unavailable = _load_optional_files(
        evidence_files, repo_root, max_untracked_bytes
    )
    git_state = collect_git_state(repo_root, max_untracked_bytes=max_untracked_bytes)
    unavailable = [
        *git_state.pop("unavailable"),
        *output_unavailable,
        *evidence_unavailable,
    ]
    observed = [
        "authority_files",
        *(["candidate_task_files"] if task_mode == "candidate" else []),
        "git_status",
        "staged_diff",
        "unstaged_diff",
        "untracked_text_files",
        *[f"output:{path}" for path in outputs],
        *[f"evidence:{path}" for path in evidence],
    ]

    request: dict[str, Any] = {
        "schema_version": 1,
        "trigger": trigger,
        "attempted_transition": transition,
        "task": task_rel,
        "task_mode": task_mode,
        "task_assertion": task_assertion,
        "candidate_task_assertion": candidate_task_assertion,
        "authority": _authority_snapshot(
            repo_root, task_dir, include_task=task_mode == "active"
        ),
        "candidate_task": (
            _candidate_task_snapshot(repo_root, task_dir)
            if task_mode == "candidate"
            else {}
        ),
        "git": git_state,
        "outputs": outputs,
        "evidence": evidence,
        "observed": observed,
        "unavailable": unavailable,
    }
    request["request_digest"] = _canonical_digest(request)
    return request


def parse_verdict(raw: str) -> dict[str, Any]:
    if raw.strip() != raw or raw.startswith("```"):
        raise VerdictError("verdict must be one bare JSON object")
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerdictError("verdict was not valid JSON") from exc
    if not isinstance(verdict, dict):
        raise VerdictError("verdict must be an object")
    if verdict.get("decision") not in DECISIONS:
        raise VerdictError("invalid decision")
    checks = verdict.get("checks")
    if not isinstance(checks, list) or len(checks) != 5:
        raise VerdictError("verdict must contain exactly five checks")
    ids = [check.get("id") for check in checks if isinstance(check, dict)]
    if ids != CHECK_IDS:
        raise VerdictError("check IDs must be F1..F5 in order")
    statuses: list[str] = []
    for check in checks:
        status = check.get("status")
        reason = check.get("reason")
        evidence = check.get("evidence")
        if status not in CHECK_STATUSES:
            raise VerdictError("invalid check status")
        if not isinstance(reason, str) or not reason.strip():
            raise VerdictError("each check needs a reason")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item.strip() for item in evidence)
        ):
            raise VerdictError("each check needs at least one evidence item")
        statuses.append(status)
    if not isinstance(verdict.get("summary"), str):
        raise VerdictError("summary must be a string")
    if not isinstance(verdict.get("unverified"), list) or not all(
        isinstance(item, str) for item in verdict["unverified"]
    ):
        raise VerdictError("unverified must be a string list")

    decision = verdict["decision"]
    if decision == "ALLOW" and any(status in {"FAIL", "UNDETERMINED"} for status in statuses):
        raise VerdictError("ALLOW cannot contain FAIL or UNDETERMINED")
    if decision == "BLOCK" and "FAIL" not in statuses:
        raise VerdictError("BLOCK requires a failed check")
    if decision == "ASK" and ("FAIL" in statuses or "UNDETERMINED" not in statuses):
        raise VerdictError("ASK requires no FAIL and at least one UNDETERMINED")
    return verdict


def should_trigger_hook(hook_input: dict[str, Any], environ: dict[str, str]) -> bool:
    if environ.get("TRELLIS_ALIGNMENT_PATROL") == "1":
        return False
    source = str(hook_input.get("source", "")).strip().lower()
    return source in HOOK_SOURCES


def _runtime_dir(repo_root: Path) -> Path:
    path = repo_root / RUNTIME_REL
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _resolve_active_task(repo_root: Path, hook_input: dict[str, Any] | None = None) -> Path:
    common_dir = repo_root / ".trellis/scripts/common"
    sys.path.insert(0, str(common_dir))
    try:
        from active_task import resolve_active_task  # type: ignore
    finally:
        sys.path.pop(0)
    active = resolve_active_task(repo_root, hook_input)
    if not active.task_path or active.stale:
        raise NoActiveTaskError("no current non-stale Trellis task")
    task_dir = repo_root / active.task_path
    if not task_dir.is_dir():
        raise PatrolError(f"active task did not exist: {active.task_path}")
    return task_dir


def _resolve_checked_task(repo_root: Path, asserted_task: str | None) -> Path:
    active_task = _resolve_active_task(repo_root)
    if asserted_task is None:
        return active_task
    asserted = Path(asserted_task)
    if not asserted.is_absolute():
        asserted = repo_root / asserted
    if asserted.resolve() != active_task.resolve():
        raise TaskAuthorityError(
            "asserted task did not match canonical active task: "
            f"{asserted_task!r} != {_relative(active_task, repo_root)!r}"
        )
    return active_task


def _resolve_candidate_task(repo_root: Path, asserted_task: str | Path) -> Path:
    tasks_root = (repo_root / ".trellis/tasks").resolve()
    asserted = Path(asserted_task)
    if not asserted.is_absolute():
        asserted = repo_root / asserted
    if asserted.is_symlink():
        raise CandidateTaskError("candidate task directory must not be a symlink")
    resolved = asserted.resolve()
    try:
        resolved.relative_to(tasks_root)
    except ValueError as exc:
        raise CandidateTaskError("candidate task escaped .trellis/tasks") from exc
    if not resolved.is_dir():
        raise CandidateTaskError(f"candidate task did not exist: {asserted_task}")
    task_json = resolved / "task.json"
    prd = resolved / "prd.md"
    if task_json.is_symlink() or prd.is_symlink():
        raise CandidateTaskError("candidate authority files must not be symlinks")
    try:
        metadata = json.loads(task_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateTaskError("candidate task.json was missing or invalid") from exc
    if not isinstance(metadata, dict) or metadata.get("status") != "planning":
        raise CandidateTaskError("candidate task must have status 'planning'")
    if not prd.is_file():
        raise CandidateTaskError("candidate task requires prd.md")
    return resolved


def _latest_patrol_message(raw_events: str, minimum_seq: int) -> str:
    candidates: list[tuple[int, str]] = []
    for line in raw_events.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") != "message" or event.get("by") != "patrol":
            continue
        seq = event.get("seq")
        text = event.get("text")
        if isinstance(seq, int) and seq > minimum_seq and isinstance(text, str):
            candidates.append((seq, text))
    if not candidates:
        raise PatrolError("Patrol produced no final message")
    return max(candidates)[1]


def _duration_seconds(value: str) -> float:
    raw = value.strip().lower()
    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    for suffix in ("ms", "s", "m", "h"):
        if raw.endswith(suffix):
            try:
                return float(raw[: -len(suffix)]) * multipliers[suffix]
            except ValueError as exc:
                raise PatrolError(f"invalid timeout: {value}") from exc
    try:
        return float(raw)
    except ValueError as exc:
        raise PatrolError(f"invalid timeout: {value}") from exc


def _read_channel_events(
    repo_root: Path, channel: str, env: dict[str, str]
) -> list[dict[str, Any]]:
    result = _run(
        ["trellis", "channel", "messages", channel, "--raw", "--no-progress"],
        cwd=repo_root,
        env=env,
    )
    events: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _wait_for_worker_ready(
    repo_root: Path, channel: str, env: dict[str, str], timeout_seconds: float
) -> None:
    deadline = time.monotonic() + min(timeout_seconds, 30.0)
    while time.monotonic() < deadline:
        events = _read_channel_events(repo_root, channel, env)
        for event in events:
            if event.get("kind") in {"error", "killed"} and event.get("by") == "patrol":
                raise PatrolError(str(event.get("message") or event.get("reason") or "Patrol failed"))
        for event in events:
            worker_name = event.get("worker") or event.get("as")
            if event.get("kind") == "spawned" and worker_name == "patrol":
                return
        time.sleep(0.1)
    raise PatrolError("Patrol worker did not become ready")


def _wait_for_terminal(
    repo_root: Path,
    channel: str,
    env: dict[str, str],
    minimum_seq: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        events = _read_channel_events(repo_root, channel, env)
        for event in events:
            if event.get("kind") in {"error", "killed"} and event.get("by") == "patrol":
                raise PatrolError(str(event.get("message") or event.get("reason") or "Patrol failed"))
            if (
                event.get("kind") == "undeliverable"
                and event.get("targetWorker") == "patrol"
                and event.get("messageSeq") == minimum_seq
            ):
                reason = event.get("reason") or "unknown"
                raise PatrolError(f"Patrol request was undeliverable: {reason}")
            seq = event.get("seq")
            if not isinstance(seq, int) or seq <= minimum_seq or event.get("by") != "patrol":
                continue
            if event.get("kind") == "done":
                return event
            if event.get("kind") in {"error", "killed"}:
                raise PatrolError(str(event.get("message") or event.get("reason") or "Patrol failed"))
        time.sleep(0.2)
    raise PatrolError("Patrol timed out before a terminal event")


def run_patrol(repo_root: Path, request: dict[str, Any], *, timeout: str = DEFAULT_TIMEOUT) -> dict[str, Any]:
    runtime = _runtime_dir(repo_root)
    digest = str(request["request_digest"])
    request_path = runtime / "requests" / f"{digest}.json"
    verdict_path = runtime / "verdicts" / f"{digest}.json"
    _write_json(request_path, request)

    channel = f"alignment-patrol-{digest[:12]}"
    env = dict(os.environ)
    env["TRELLIS_ALIGNMENT_PATROL"] = "1"
    env["TRELLIS_CHANNEL_ROOT"] = str(runtime / "channels")
    request_rel = _relative(request_path, repo_root)
    send_seq = -1
    worker_registered = False
    timeout_seconds = _duration_seconds(timeout)
    try:
        _run(
            [
                "trellis",
                "channel",
                "create",
                channel,
                "--by",
                "alignment-runner",
                "--cwd",
                str(repo_root),
                "--ephemeral",
                "--force",
            ],
            cwd=repo_root,
            env=env,
        )
        _run(
            [
                "trellis",
                "channel",
                "spawn",
                channel,
                "--agent",
                "alignment-patrol",
                "--provider",
                "codex",
                "--model",
                "gpt-5.6-terra",
                "--as",
                "patrol",
                "--cwd",
                str(repo_root),
                "--sandbox",
                "read-only",
                "--file",
                request_rel,
                "--timeout",
                timeout,
                "--idle-timeout",
                "0",
                "--max-live-workers",
                "6",
            ],
            cwd=repo_root,
            env=env,
        )
        worker_registered = True
        _wait_for_worker_ready(repo_root, channel, env, timeout_seconds)
        sent = _run(
            [
                "trellis",
                "channel",
                "send",
                channel,
                "Review the supplied request and return the required bare JSON verdict.",
                "--as",
                "alignment-runner",
                "--to",
                "patrol",
                "--delivery-mode",
                "requireRunningWorker",
            ],
            cwd=repo_root,
            env=env,
        )
        sent_event = json.loads(sent.stdout)
        send_seq = int(sent_event["seq"])
        _wait_for_terminal(repo_root, channel, env, send_seq, timeout_seconds)
        events = _run(
            [
                "trellis",
                "channel",
                "messages",
                channel,
                "--raw",
                "--no-progress",
                "--from",
                "patrol",
            ],
            cwd=repo_root,
            env=env,
        )
        verdict = parse_verdict(_latest_patrol_message(events.stdout, send_seq))
        verdict["request_digest"] = digest
        _write_json(verdict_path, verdict)
        return verdict
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise PatrolError(f"command failed ({exc.returncode}): {detail}") from exc
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
        raise PatrolError(str(exc)) from exc
    finally:
        if worker_registered:
            _run(
                ["trellis", "channel", "kill", channel, "--as", "patrol"],
                cwd=repo_root,
                env=env,
                check=False,
            )


def _repo_root(path: str | None) -> Path:
    start = Path(path or ".").resolve()
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    return Path(result.stdout.strip()).resolve()


def _emit_session_context() -> None:
    context = (
        "Alignment context reset: Read-only discussion may continue. Before the "
        "next supported state-changing action, run a fresh transition-specific "
        "Alignment Patrol check."
    )
    payload = {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


def _hook_command(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        hook_input = {}
    if not isinstance(hook_input, dict):
        hook_input = {}
    if not should_trigger_hook(hook_input, dict(os.environ)):
        return 0
    _emit_session_context()
    return 0


def _emit_check_unavailable(code: str, error: Exception) -> None:
    payload = {
        "decision": "ASK",
        "code": code,
        "summary": f"{error.__class__.__name__}: {error}",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _check_command(args: argparse.Namespace) -> int:
    try:
        repo_root = _repo_root(args.repo)
        if args.trigger not in CHECK_TRIGGERS:
            raise UnsupportedTriggerError(f"unsupported trigger: {args.trigger}")
        if args.trigger == "plan-document-write":
            if not args.candidate_task:
                raise CandidateTaskError(
                    "plan-document-write requires --candidate-task"
                )
            task_dir = _resolve_candidate_task(repo_root, args.candidate_task)
            task_mode = "candidate"
        else:
            if args.candidate_task:
                raise CandidateTaskError(
                    "--candidate-task is only valid for plan-document-write"
                )
            task_dir = _resolve_checked_task(repo_root, args.task)
            task_mode = "active"
        request = build_request(
            repo_root,
            args.trigger,
            args.transition,
            task_dir,
            output_files=[Path(path) for path in args.output_file],
            evidence_files=[Path(path) for path in args.evidence_file],
            task_assertion=args.task,
            task_mode=task_mode,
            candidate_task_assertion=args.candidate_task,
            max_untracked_bytes=args.max_untracked_bytes,
        )
        if args.collect_only:
            print(json.dumps(request, ensure_ascii=False, indent=2))
            return 0
        verdict = run_patrol(repo_root, request, timeout=args.timeout)
    except NoActiveTaskError as exc:
        _emit_check_unavailable("NO_ACTIVE_TASK", exc)
        return 3
    except TaskAuthorityError as exc:
        _emit_check_unavailable("TASK_AUTHORITY_MISMATCH", exc)
        return 3
    except CandidateTaskError as exc:
        _emit_check_unavailable("CANDIDATE_TASK_INVALID", exc)
        return 3
    except UnsupportedTriggerError as exc:
        _emit_check_unavailable("UNSUPPORTED_TRIGGER", exc)
        return 3
    except Exception as exc:
        _emit_check_unavailable("PATROL_UNAVAILABLE", exc)
        return 3
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return {"ALLOW": 0, "BLOCK": 2, "ASK": 3}[verdict["decision"]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="repository root or descendant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("hook", help="handle SessionStart hook input on stdin")
    hook.set_defaults(func=_hook_command)

    check = subparsers.add_parser("check", help="collect and review one attempted transition")
    check.add_argument("--trigger", required=True, choices=CHECK_TRIGGERS)
    check.add_argument("--transition", required=True)
    task_group = check.add_mutually_exclusive_group()
    task_group.add_argument(
        "--task",
        help="optional assertion that must match the canonical active Trellis task",
    )
    task_group.add_argument(
        "--candidate-task",
        help="planning task reviewed as a proposal by plan-document-write",
    )
    check.add_argument("--output-file", action="append", default=[])
    check.add_argument("--evidence-file", action="append", default=[])
    check.add_argument("--max-untracked-bytes", type=int, default=DEFAULT_MAX_UNTRACKED_BYTES)
    check.add_argument("--timeout", default=DEFAULT_TIMEOUT)
    check.add_argument("--collect-only", action="store_true")
    check.set_defaults(func=_check_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
