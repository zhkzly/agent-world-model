from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / ".trellis/scripts/run_alignment_patrol.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("alignment_patrol_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load alignment patrol runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def valid_checks(*, fail: str | None = None, undetermined: str | None = None):
    checks = []
    for index in range(1, 6):
        check_id = f"F{index}"
        status = "PASS"
        if check_id == fail:
            status = "FAIL"
        elif check_id == undetermined:
            status = "UNDETERMINED"
        checks.append(
            {
                "id": check_id,
                "status": status,
                "reason": f"reason-{check_id}",
                "evidence": [f"evidence-{check_id}"],
            }
        )
    return checks


class VerdictTests(unittest.TestCase):
    def test_allow_requires_exactly_five_passing_or_na_checks(self):
        runner = load_runner()
        payload = {
            "decision": "ALLOW",
            "checks": valid_checks(),
            "summary": "current slice aligned",
            "unverified": ["future work"],
        }
        verdict = runner.parse_verdict(json.dumps(payload))
        self.assertEqual("ALLOW", verdict["decision"])
        self.assertEqual([f"F{i}" for i in range(1, 6)], [c["id"] for c in verdict["checks"]])

    def test_allow_rejects_material_undetermined(self):
        runner = load_runner()
        payload = {
            "decision": "ALLOW",
            "checks": valid_checks(undetermined="F4"),
            "summary": "not actually decidable",
            "unverified": [],
        }
        with self.assertRaises(runner.VerdictError):
            runner.parse_verdict(json.dumps(payload))

    def test_allow_rejects_evidence_free_checks(self):
        runner = load_runner()
        checks = valid_checks()
        checks[0]["evidence"] = []
        payload = {
            "decision": "ALLOW",
            "checks": checks,
            "summary": "unsupported approval",
            "unverified": [],
        }
        with self.assertRaises(runner.VerdictError):
            runner.parse_verdict(json.dumps(payload))

    def test_block_requires_a_failed_check(self):
        runner = load_runner()
        missing_failure = {
            "decision": "BLOCK",
            "checks": valid_checks(),
            "summary": "unsupported block",
            "unverified": [],
        }
        with self.assertRaises(runner.VerdictError):
            runner.parse_verdict(json.dumps(missing_failure))

        valid = dict(missing_failure)
        valid["checks"] = valid_checks(fail="F3")
        self.assertEqual("BLOCK", runner.parse_verdict(json.dumps(valid))["decision"])

    def test_malformed_output_fails_closed(self):
        runner = load_runner()
        for raw in ("ALLOW", "```json\n{}\n```", "{}", "not-json"):
            with self.subTest(raw=raw):
                with self.assertRaises(runner.VerdictError):
                    runner.parse_verdict(raw)


class RequestAndDigestTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="alignment-patrol-test-"))
        run_git(root, "init", "-q")
        run_git(root, "config", "user.email", "test@example.com")
        run_git(root, "config", "user.name", "Test")
        (root / "PROJECT.md").write_text("project authority\n", encoding="utf-8")
        (root / "DECISIONS.md").write_text("accepted decision\n", encoding="utf-8")
        task_dir = root / ".trellis/tasks/01-01-task"
        task_dir.mkdir(parents=True)
        (task_dir / "prd.md").write_text("goal and non-goals\n", encoding="utf-8")
        (task_dir / "task.json").write_text(
            json.dumps({"status": "in_progress", "title": "task"}) + "\n",
            encoding="utf-8",
        )
        (root / "tracked.txt").write_text("base\n", encoding="utf-8")
        run_git(root, "add", ".")
        run_git(root, "commit", "-qm", "base")
        return root

    def test_collect_git_state_includes_staged_unstaged_and_untracked(self):
        runner = load_runner()
        root = self.make_repo()
        (root / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (root / "staged.txt").write_text("staged\n", encoding="utf-8")
        run_git(root, "add", "staged.txt")
        (root / "untracked.txt").write_text("untracked payload\n", encoding="utf-8")

        state = runner.collect_git_state(root, max_untracked_bytes=1024)
        self.assertIn("tracked.txt", state["unstaged_diff"])
        self.assertIn("staged.txt", state["staged_diff"])
        self.assertEqual(
            "untracked payload\n", state["untracked"]["untracked.txt"]["content"]
        )
        self.assertEqual([], state["unavailable"])

    def test_oversized_untracked_file_is_declared_unavailable(self):
        runner = load_runner()
        root = self.make_repo()
        (root / "large.bin").write_bytes(b"x" * 20)
        state = runner.collect_git_state(root, max_untracked_bytes=8)
        self.assertNotIn("large.bin", state["untracked"])
        self.assertTrue(any(item["path"] == "large.bin" for item in state["unavailable"]))

    def test_untracked_symlink_is_declared_unavailable_without_dereferencing(self):
        runner = load_runner()
        root = self.make_repo()
        outside = Path(tempfile.mkdtemp(prefix="alignment-patrol-outside-")) / "secret.txt"
        outside.write_text("must not be read\n", encoding="utf-8")
        (root / "outside-link").symlink_to(outside)

        state = runner.collect_git_state(root, max_untracked_bytes=1024)

        self.assertNotIn("outside-link", state["untracked"])
        self.assertTrue(
            any(
                item["path"] == "outside-link" and item["reason"] == "symlink"
                for item in state["unavailable"]
            )
        )
        self.assertNotIn("must not be read", json.dumps(state))

    def test_non_utf8_untracked_bytes_change_request_digest(self):
        runner = load_runner()
        root = self.make_repo()
        task = root / ".trellis/tasks/01-01-task"
        opaque = root / "opaque.bin"
        opaque.write_bytes(b"\xff")
        first = runner.build_request(root, "worker-turn", "continue", task)
        opaque.write_bytes(b"\xfe")
        second = runner.build_request(root, "worker-turn", "continue", task)

        self.assertNotEqual(first["request_digest"], second["request_digest"])
        first_item = next(item for item in first["unavailable"] if item["path"] == "opaque.bin")
        second_item = next(item for item in second["unavailable"] if item["path"] == "opaque.bin")
        self.assertNotEqual(first_item["sha256"], second_item["sha256"])

    def test_missing_or_symlinked_authority_fails_closed(self):
        runner = load_runner()
        root = self.make_repo()
        task = root / ".trellis/tasks/01-01-task"
        (root / "DECISIONS.md").unlink()
        with self.assertRaises(runner.PatrolError):
            runner.build_request(root, "transition", "finish", task)

        outside = Path(tempfile.mkdtemp(prefix="alignment-authority-outside-")) / "p.md"
        outside.write_text("external authority\n", encoding="utf-8")
        (root / "DECISIONS.md").symlink_to(outside)
        with self.assertRaises(runner.PatrolError):
            runner.build_request(root, "transition", "finish", task)

    def test_request_digest_changes_with_transition_and_diff(self):
        runner = load_runner()
        root = self.make_repo()
        task = root / ".trellis/tasks/01-01-task"
        first = runner.build_request(root, "worker-turn", "commit slice A", task)
        second = runner.build_request(root, "worker-turn", "commit slice B", task)
        self.assertNotEqual(first["request_digest"], second["request_digest"])

        (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        third = runner.build_request(root, "worker-turn", "commit slice A", task)
        self.assertNotEqual(first["request_digest"], third["request_digest"])

    def test_authority_uses_stock_task_json_not_private_task_markdown(self):
        runner = load_runner()
        root = self.make_repo()
        task = root / ".trellis/tasks/01-01-task"
        request = runner.build_request(root, "transition", "finish", task)
        self.assertIn(".trellis/tasks/01-01-task/task.json", request["authority"])
        self.assertNotIn(".trellis/tasks/01-01-task/task.md", request["authority"])

    def test_task_argument_only_asserts_canonical_active_task(self):
        runner = load_runner()
        root = self.make_repo()
        active = root / ".trellis/tasks/01-01-task"
        with mock.patch.object(runner, "_resolve_active_task", return_value=active):
            self.assertEqual(active, runner._resolve_checked_task(root, None))
            self.assertEqual(
                active,
                runner._resolve_checked_task(root, ".trellis/tasks/01-01-task"),
            )
            with self.assertRaises(runner.TaskAuthorityError):
                runner._resolve_checked_task(root, ".trellis/tasks/99-99-forged")

    def test_candidate_plan_is_subject_not_self_authorizing_task(self):
        runner = load_runner()
        root = self.make_repo()
        candidate = root / ".trellis/tasks/02-02-candidate"
        candidate.mkdir()
        (candidate / "task.json").write_text(
            json.dumps({"status": "planning", "title": "candidate"}) + "\n",
            encoding="utf-8",
        )
        (candidate / "prd.md").write_text(
            "# Candidate\n\nProposed implementation scope.\n", encoding="utf-8"
        )

        resolved = runner._resolve_candidate_task(
            root, ".trellis/tasks/02-02-candidate"
        )
        request = runner.build_request(
            root,
            "plan-document-write",
            "persist candidate plan",
            resolved,
            task_mode="candidate",
            candidate_task_assertion=".trellis/tasks/02-02-candidate",
        )

        self.assertEqual("candidate", request["task_mode"])
        self.assertIn("candidate_task_files", request["observed"])
        self.assertNotIn(".trellis/tasks/02-02-candidate/prd.md", request["authority"])
        self.assertIn(".trellis/tasks/02-02-candidate/prd.md", request["candidate_task"])

    def test_candidate_task_must_be_planning_and_inside_trellis_tasks(self):
        runner = load_runner()
        root = self.make_repo()
        candidate = root / ".trellis/tasks/02-02-candidate"
        candidate.mkdir()
        (candidate / "task.json").write_text(
            json.dumps({"status": "in_progress"}) + "\n", encoding="utf-8"
        )
        (candidate / "prd.md").write_text("scope\n", encoding="utf-8")

        with self.assertRaises(runner.CandidateTaskError):
            runner._resolve_candidate_task(root, candidate)
        with self.assertRaises(runner.CandidateTaskError):
            runner._resolve_candidate_task(root, root / "outside-task")

class TriggerAndWiringTests(unittest.TestCase):
    def test_compact_resume_and_fork_trigger_but_startup_does_not(self):
        runner = load_runner()
        for source in ("compact", "resume", "fork"):
            with self.subTest(source=source):
                self.assertTrue(runner.should_trigger_hook({"source": source}, {}))
        self.assertFalse(runner.should_trigger_hook({"source": "startup"}, {}))
        self.assertFalse(
            runner.should_trigger_hook(
                {"source": "compact"}, {"TRELLIS_ALIGNMENT_PATROL": "1"}
            )
        )

    def test_agent_contract_has_exactly_five_checks_and_no_write_authority(self):
        card = (REPO_ROOT / ".trellis/agents/alignment-patrol.md").read_text(encoding="utf-8")
        for check_id in ("F1", "F2", "F3", "F4", "F5"):
            self.assertIn(check_id, card)
        self.assertNotIn("F6", card)
        self.assertIn("Do not edit", card)
        self.assertIn("Do not spawn", card)
        self.assertIn("plan-document-write", card)
        self.assertIn("proposal, not authority", card)

    def test_platform_hooks_and_workflow_reference_shared_runner(self):
        claude = json.loads((REPO_ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        codex = json.loads((REPO_ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
        runner_name = "run_alignment_patrol.py"
        self.assertIn(runner_name, json.dumps(claude))
        self.assertIn(runner_name, json.dumps(codex))
        claude_groups = {
            group.get("matcher"): json.dumps(group)
            for group in claude["hooks"]["SessionStart"]
        }
        for source in ("compact", "resume", "fork"):
            self.assertIn(source, claude_groups)
            self.assertIn(runner_name, claude_groups[source])
        self.assertIn(runner_name, json.dumps(codex["hooks"]["SessionStart"]))
        patrol_commands = [
            hook["command"]
            for config in (claude, codex)
            for group in config["hooks"]["SessionStart"]
            for hook in group["hooks"]
            if runner_name in hook["command"]
        ]
        self.assertTrue(patrol_commands)
        self.assertTrue(
            all("git rev-parse --show-toplevel" in command for command in patrol_commands),
            patrol_commands,
        )
        patrol_timeouts = [
            hook["timeout"]
            for config in (claude, codex)
            for group in config["hooks"]["SessionStart"]
            for hook in group["hooks"]
            if runner_name in hook["command"]
        ]
        self.assertTrue(all(timeout <= 30 for timeout in patrol_timeouts), patrol_timeouts)
        workflow = (REPO_ROOT / ".trellis/workflow.md").read_text(encoding="utf-8")
        self.assertIn("alignment-patrol", workflow)
        self.assertIn("worker-turn", workflow)
        self.assertIn("transition", workflow)
        self.assertIn("diagnostic only", workflow)
        self.assertIn("&& <exact-transition-command>", workflow)
        opened = re.findall(r"(?m)^\[workflow-state:([a-z0-9_-]+)\]\s*$", workflow)
        closed = re.findall(r"(?m)^\[/workflow-state:([a-z0-9_-]+)\]\s*$", workflow)
        self.assertEqual(opened, closed)

    def test_effective_config_disables_auto_commit_and_enables_codex_subagent_dispatch(self):
        scripts_dir = REPO_ROOT / ".trellis/scripts"
        sys.path.insert(0, str(scripts_dir))
        try:
            from common import config as trellis_config

            self.assertFalse(trellis_config.get_session_auto_commit(REPO_ROOT))
            self.assertEqual("auto", trellis_config.get_codex_dispatch_mode(REPO_ROOT))
        finally:
            sys.path.pop(0)

    def test_registered_worker_is_killed_when_ready_check_fails(self):
        runner = load_runner()
        request = {"request_digest": "a" * 64}
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "{}", "")

        with tempfile.TemporaryDirectory(prefix="alignment-patrol-run-") as directory:
            repo = Path(directory)
            with (
                mock.patch.object(runner, "_run", side_effect=fake_run),
                mock.patch.object(
                    runner,
                    "_wait_for_worker_ready",
                    side_effect=runner.PatrolError("not ready"),
                ),
            ):
                with self.assertRaises(runner.PatrolError):
                    runner.run_patrol(repo, request, timeout="1s")

        self.assertTrue(
            any(command[:3] == ["trellis", "channel", "kill"] for command in calls),
            calls,
        )

    def test_ready_check_prefers_terminal_error_over_spawned_event(self):
        runner = load_runner()
        events = [
            {"kind": "spawned", "as": "patrol", "seq": 2},
            {"kind": "error", "by": "patrol", "message": "startup failed", "seq": 3},
        ]
        with mock.patch.object(runner, "_read_channel_events", return_value=events):
            with self.assertRaisesRegex(runner.PatrolError, "startup failed"):
                runner._wait_for_worker_ready(Path("."), "channel", {}, 0.1)

    def test_terminal_wait_reports_undeliverable_send_without_timeout(self):
        runner = load_runner()
        events = [
            {
                "kind": "undeliverable",
                "targetWorker": "patrol",
                "messageSeq": 4,
                "reason": "worker-terminal",
                "seq": 5,
            }
        ]
        with mock.patch.object(runner, "_read_channel_events", return_value=events):
            with self.assertRaisesRegex(runner.PatrolError, "undeliverable"):
                runner._wait_for_terminal(Path("."), "channel", {}, 4, 0.01)

    def test_context_reset_hook_is_neutral_and_does_not_dispatch_patrol(self):
        runner = load_runner()
        hook_input = io.StringIO(json.dumps({"source": "compact", "cwd": str(REPO_ROOT)}))
        stream = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", hook_input),
            mock.patch.object(runner, "_repo_root") as repo_root,
            mock.patch.object(runner, "run_patrol") as run_patrol,
            redirect_stdout(stream),
        ):
            code = runner._hook_command(SimpleNamespace(repo=None))

        self.assertEqual(0, code)
        repo_root.assert_not_called()
        run_patrol.assert_not_called()
        payload = json.loads(stream.getvalue())
        self.assertTrue(payload["continue"])
        self.assertNotIn("stopReason", payload)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Read-only discussion may continue", context)
        self.assertNotRegex(context, r"\b(?:ALLOW|BLOCK|ASK)\b")

    def test_missing_active_task_is_structured_ask_for_action_only(self):
        runner = load_runner()
        args = SimpleNamespace(
            repo=None,
            task=None,
            candidate_task=None,
            trigger="transition",
            transition="finish task",
            output_file=[],
            evidence_file=[],
            max_untracked_bytes=1024,
            collect_only=False,
            timeout="1s",
        )
        stream = io.StringIO()
        with (
            mock.patch.object(runner, "_repo_root", return_value=REPO_ROOT),
            mock.patch.object(
                runner,
                "_resolve_checked_task",
                side_effect=runner.NoActiveTaskError("none"),
            ),
            redirect_stdout(stream),
        ):
            code = runner._check_command(args)
        payload = json.loads(stream.getvalue())
        self.assertEqual(3, code)
        self.assertEqual("ASK", payload["decision"])
        self.assertEqual("NO_ACTIVE_TASK", payload["code"])

    def test_task_authority_mismatch_is_not_reported_as_model_failure(self):
        runner = load_runner()
        args = SimpleNamespace(
            repo=None,
            task=".trellis/tasks/forged",
            candidate_task=None,
            trigger="transition",
            transition="finish task",
            output_file=[],
            evidence_file=[],
            max_untracked_bytes=1024,
            collect_only=False,
            timeout="1s",
        )
        stream = io.StringIO()
        with (
            mock.patch.object(runner, "_repo_root", return_value=REPO_ROOT),
            mock.patch.object(
                runner,
                "_resolve_checked_task",
                side_effect=runner.TaskAuthorityError("mismatch"),
            ),
            redirect_stdout(stream),
        ):
            code = runner._check_command(args)
        payload = json.loads(stream.getvalue())
        self.assertEqual(3, code)
        self.assertEqual("TASK_AUTHORITY_MISMATCH", payload["code"])

    def test_plan_document_write_requires_explicit_candidate_not_active_task(self):
        runner = load_runner()
        args = SimpleNamespace(
            repo=None,
            task=None,
            candidate_task=None,
            trigger="plan-document-write",
            transition="persist candidate",
            output_file=[],
            evidence_file=[],
            max_untracked_bytes=1024,
            collect_only=False,
            timeout="1s",
        )
        stream = io.StringIO()
        with (
            mock.patch.object(runner, "_repo_root", return_value=REPO_ROOT),
            mock.patch.object(runner, "_resolve_active_task") as active_task,
            redirect_stdout(stream),
        ):
            code = runner._check_command(args)
        payload = json.loads(stream.getvalue())
        self.assertEqual(3, code)
        self.assertEqual("CANDIDATE_TASK_INVALID", payload["code"])
        active_task.assert_not_called()

    def test_unknown_check_trigger_is_rejected_before_authority_resolution(self):
        runner = load_runner()
        args = SimpleNamespace(
            repo=None,
            task=None,
            candidate_task=None,
            trigger="invented-trigger",
            transition="do something",
            output_file=[],
            evidence_file=[],
            max_untracked_bytes=1024,
            collect_only=False,
            timeout="1s",
        )
        stream = io.StringIO()
        with (
            mock.patch.object(runner, "_repo_root", return_value=REPO_ROOT),
            mock.patch.object(runner, "_resolve_active_task") as active_task,
            redirect_stdout(stream),
        ):
            code = runner._check_command(args)
        payload = json.loads(stream.getvalue())
        self.assertEqual(3, code)
        self.assertEqual("UNSUPPORTED_TRIGGER", payload["code"])
        active_task.assert_not_called()

    def test_project_contract_exempts_discussion_from_transition_gates(self):
        contract = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Discussion-only turns are not state transitions", contract)
        self.assertRegex(contract, r"do not dispatch a\s+worker")


if __name__ == "__main__":
    unittest.main()
