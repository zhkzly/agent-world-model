from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any


GENERATED_FILE_KINDS = {
    "runtime.py": "runtime_code",
    "seed_state.json": "seed_fixture",
    "verifier.py": "verifier_code",
    "surface_descriptor.json": "surface_descriptor",
    "check_replay.py": "test_or_check",
    "build_manifest.yaml": "build_manifest",
}


def main() -> int:
    workspace = Path(os.environ["AGENT_WORLD_CODE_AGENT_WORKSPACE"]).resolve()
    generated_dir = Path(os.environ["AGENT_WORLD_CODE_AGENT_GENERATED_DIR"]).resolve()
    output_dir = Path(os.environ["AGENT_WORLD_CODE_AGENT_OUTPUT_DIR"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(sys.stdin.read() or "{}")
    if "fail-before-manifest" in sys.argv:
        (output_dir / "self-check-log.jsonl").write_text(json.dumps({"forced_failure": True}) + "\n", encoding="utf-8")
        return 0
    _write_generated_files(generated_dir)
    completed = subprocess.run(
        [sys.executable, "check_replay.py"],
        cwd=generated_dir,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    with (output_dir / "self-check-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "command": [sys.executable, "check_replay.py"],
                    "cwd": str(generated_dir),
                    "exit_code": completed.returncode,
                    "stdout_preview": completed.stdout[-2000:],
                    "stderr_preview": completed.stderr[-2000:],
                },
                sort_keys=True,
            )
        )
        handle.write("\n")
    if completed.returncode != 0:
        return completed.returncode
    manifest = {
        "candidate_dir": "generated",
        "bundle_id": "bundle-project-board-lite-agent-generated",
        "environment_id": "project-board-lite",
        "generated_files": [
            {
                "path": filename,
                "kind": kind,
                "sha256": _sha256(generated_dir / filename),
                "source_refs": payload.get("input_artifact_ids") or ["runner://workspace-packet"],
            }
            for filename, kind in GENERATED_FILE_KINDS.items()
        ],
        "runtime_entrypoint": "runtime.ProjectBoardLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in ["pb-task-1", "pb-task-2", "pb-task-3"]],
    }
    (output_dir / "candidate_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "pass", "workspace": str(workspace), "manifest": "agent-output/candidate_manifest.json"}, sort_keys=True))
    return 0


def _write_generated_files(root: Path) -> None:
    (root / "runtime.py").write_text(_runtime_py(), encoding="utf-8")
    (root / "seed_state.json").write_text(json.dumps(_seed_state(), sort_keys=True), encoding="utf-8")
    (root / "verifier.py").write_text(_verifier_py(), encoding="utf-8")
    (root / "surface_descriptor.json").write_text(json.dumps(_surface_descriptor(), sort_keys=True), encoding="utf-8")
    (root / "check_replay.py").write_text(_check_replay_py(), encoding="utf-8")
    build_manifest = {
        "bundle_id": "bundle-project-board-lite-agent-generated",
        "environment_id": "project-board-lite",
        "generated_files": list(GENERATED_FILE_KINDS),
        "runtime_entrypoint": "runtime.ProjectBoardLite",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in ["pb-task-1", "pb-task-2", "pb-task-3"]],
    }
    (root / "build_manifest.yaml").write_text(json.dumps(build_manifest, sort_keys=True), encoding="utf-8")


def _runtime_py() -> str:
    return textwrap.dedent(
        '''
        from __future__ import annotations

        import copy
        import json
        from pathlib import Path
        from typing import Any


        def load_seed_state(seed_path: Path) -> dict[str, Any]:
            return json.loads(Path(seed_path).read_text(encoding="utf-8"))


        def reset_environment(seed_state: dict[str, Any]) -> dict[str, Any]:
            return copy.deepcopy(seed_state)


        class ProjectBoardLite:
            def __init__(self, state: dict[str, Any], *, trace_path: Path | None = None, task_id: str | None = None, call_group: str | None = None):
                self.state = state
                self.trace_path = Path(trace_path) if trace_path else None
                self.task_id = task_id or ""
                self.call_group = call_group or self.task_id or "ad-hoc"

            def card_list(self, *, status: str | None = None, assignee: str | None = None, priority: str | None = None) -> list[dict[str, Any]]:
                cards = [
                    copy.deepcopy(card)
                    for card in self.state["card"]
                    if (status is None or card["status"] == status)
                    and (assignee is None or card["assignee"] == assignee)
                    and (priority is None or card["priority"] == priority)
                ]
                self._trace("card_list", {"status": status, "assignee": assignee, "priority": priority}, {"count": len(cards)})
                return cards

            def card_get(self, card_id: str) -> dict[str, Any]:
                card = _card(self.state, card_id)
                self._trace("card_get", {"card_id": card_id}, {"card_id": card_id})
                return copy.deepcopy(card)

            def card_move(self, *, card_id: str, status: str, note: str) -> dict[str, Any]:
                _ensure_status(self.state, status)
                card = _card(self.state, card_id)
                old = card["status"]
                card["status"] = status
                _audit(self.state, card_id, "card_moved", "status", old, status, note)
                self._trace("card_move", {"card_id": card_id, "status": status, "note": note}, {"card_id": card_id, "status": status})
                return copy.deepcopy(card)

            def card_assign(self, *, card_id: str, assignee: str, note: str) -> dict[str, Any]:
                card = _card(self.state, card_id)
                old = card["assignee"]
                card["assignee"] = assignee
                _audit(self.state, card_id, "card_assigned", "assignee", old, assignee, note)
                self._trace("card_assign", {"card_id": card_id, "assignee": assignee, "note": note}, {"card_id": card_id, "assignee": assignee})
                return copy.deepcopy(card)

            def comment_add(self, *, card_id: str, body: str, visibility: str = "team") -> dict[str, Any]:
                _card(self.state, card_id)
                comment = {"id": f"comment-{len(self.state['comment']) + 1}", "card_id": card_id, "body": body, "visibility": visibility}
                self.state["comment"].append(comment)
                _audit(self.state, card_id, "comment_added", "comment", "", comment["id"], body)
                self._trace("comment_add", {"card_id": card_id, "body": body, "visibility": visibility}, {"comment_id": comment["id"]})
                return copy.deepcopy(comment)

            def _trace(self, tool: str, inputs: dict[str, Any], output: dict[str, Any]) -> None:
                if not self.trace_path:
                    return
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                with self.trace_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"task_id": self.task_id, "call_group": self.call_group, "tool": tool, "inputs": inputs, "output": output}, sort_keys=True))
                    handle.write("\\n")


        def _card(state: dict[str, Any], card_id: str) -> dict[str, Any]:
            for card in state["card"]:
                if card["id"] == card_id:
                    return card
            raise KeyError(card_id)


        def _ensure_status(state: dict[str, Any], status: str) -> None:
            statuses = state["board"][0]["workflow_statuses"]
            if status not in statuses:
                raise ValueError(status)


        def _audit(state: dict[str, Any], card_id: str, event_type: str, field: str, old: str, new: str, note: str) -> None:
            state["audit_event"].append({"card_id": card_id, "event_type": event_type, "field": field, "old_value": old, "new_value": new, "note": note})
        '''
    ).strip() + "\n"


def _verifier_py() -> str:
    return textwrap.dedent(
        '''
        from __future__ import annotations

        import json
        from pathlib import Path
        from typing import Any


        def verify_task_completion(
            task_id: str,
            before_state: dict[str, Any],
            after_state: dict[str, Any],
            *,
            final_answer: Any = None,
            surface_trace_path: Path | None = None,
            expected_dependency_path: list[str] | None = None,
            trace_call_group: str | None = None,
        ) -> dict[str, Any]:
            checks: list[dict[str, Any]] = []

            def add(name: str, passed: bool, detail: Any) -> None:
                checks.append({"name": name, "passed": bool(passed), "detail": detail})

            expected_dependency_path = expected_dependency_path or _expected_dependency_path(task_id)
            add(
                "dependency_path_trace_matches",
                _trace_tools(surface_trace_path, task_id, trace_call_group) == expected_dependency_path,
                {"expected": expected_dependency_path},
            )
            if task_id == "pb-task-1":
                add("target_card_moved", _card(after_state, "C-11").get("status") == "in_review", _card(after_state, "C-11"))
                add("audit_written", _has_audit(after_state, "C-11", "card_moved", "status", "in_review"), after_state["audit_event"])
                add("non_target_cards_preserved", _non_target_cards_preserved(before_state, after_state, {"C-11"}), "")
            elif task_id == "pb-task-2":
                add("target_card_assigned", _card(after_state, "C-10").get("assignee") == "sam", _card(after_state, "C-10"))
                add("target_comment_added", any(comment["card_id"] == "C-10" and "triage" in comment["body"].lower() for comment in after_state["comment"]), after_state["comment"])
                add("audit_written", _has_audit(after_state, "C-10", "card_assigned", "assignee", "sam"), after_state["audit_event"])
                add("non_target_cards_preserved", _non_target_cards_preserved(before_state, after_state, {"C-10"}), "")
            elif task_id == "pb-task-3":
                expected = {"status": "in_progress", "assignee": "eve", "card_count": 1, "highest_priority": "medium"}
                add("answer_matches", final_answer == expected, {"expected": expected, "actual": final_answer})
                add("state_unchanged", before_state == after_state, "")
            else:
                add("known_task", False, task_id)
            return {"success": all(check["passed"] for check in checks), "checks": checks}


        def _card(state: dict[str, Any], card_id: str) -> dict[str, Any]:
            for card in state["card"]:
                if card["id"] == card_id:
                    return card
            return {}


        def _has_audit(state: dict[str, Any], card_id: str, event_type: str, field: str, new_value: str) -> bool:
            return any(
                event["card_id"] == card_id
                and event["event_type"] == event_type
                and event["field"] == field
                and event["new_value"] == new_value
                for event in state["audit_event"]
            )


        def _non_target_cards_preserved(initial: dict[str, Any], final: dict[str, Any], target_ids: set[str]) -> bool:
            initial_cards = {card["id"]: card for card in initial["card"] if card["id"] not in target_ids}
            final_cards = {card["id"]: card for card in final["card"] if card["id"] not in target_ids}
            return initial_cards == final_cards


        def _expected_dependency_path(task_id: str) -> list[str]:
            return {
                "pb-task-1": ["card_list", "card_get", "card_move"],
                "pb-task-2": ["card_list", "card_assign", "comment_add"],
                "pb-task-3": ["card_list"],
            }.get(task_id, [])


        def _trace_tools(path: Path | None, task_id: str, call_group: str | None) -> list[str]:
            if not path or not Path(path).exists():
                return []
            tools = []
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("task_id") != task_id:
                    continue
                if call_group is not None and record.get("call_group") != call_group:
                    continue
                tools.append(record["tool"])
            return tools
        '''
    ).strip() + "\n"


def _check_replay_py() -> str:
    return textwrap.dedent(
        '''
        from __future__ import annotations

        import argparse
        import json
        from pathlib import Path
        import sys
        import tempfile

        from runtime import ProjectBoardLite, load_seed_state, reset_environment
        from verifier import verify_task_completion


        TASK_IDS = ["pb-task-1", "pb-task-2", "pb-task-3"]


        def main(argv: list[str] | None = None) -> int:
            parser = argparse.ArgumentParser()
            parser.add_argument("--task", choices=TASK_IDS)
            args = parser.parse_args(argv)
            root = Path(__file__).resolve().parent
            seed = load_seed_state(root / "seed_state.json")
            task_ids = [args.task] if args.task else TASK_IDS
            with tempfile.TemporaryDirectory() as td:
                results = [run_task(seed, task_id, Path(td)) for task_id in task_ids]
            result = {
                "success": all(item["success"] for item in results),
                "task_results": results,
                "positive_verifier_result": results[0]["positive_verifier_result"] if results else {},
                "negative_verifier_result": results[0]["negative_verifier_result"] if results else {},
            }
            print(json.dumps(result, sort_keys=True))
            return 0 if result["success"] else 1


        def run_task(seed: dict, task_id: str, root: Path) -> dict:
            trace = root / f"{task_id}-trace.jsonl"
            state = reset_environment(seed)
            env = ProjectBoardLite(state, trace_path=trace, task_id=task_id, call_group="positive")
            answer = execute_positive(env, task_id)
            positive = verify_task_completion(task_id, seed, state, final_answer=answer, surface_trace_path=trace, trace_call_group="positive")
            negative_state = reset_environment(seed)
            negative_answer = {"status": "in_progress", "assignee": "eve", "card_count": 0, "highest_priority": "none"} if task_id == "pb-task-3" else None
            negative = verify_task_completion(task_id, seed, negative_state, final_answer=negative_answer, surface_trace_path=root / f"{task_id}-missing.jsonl", trace_call_group="negative")
            return {"task_id": task_id, "success": positive["success"] is True and negative["success"] is False, "positive_verifier_result": positive, "negative_verifier_result": negative}


        def execute_positive(env: ProjectBoardLite, task_id: str):
            if task_id == "pb-task-1":
                env.card_list(status="blocked", priority="urgent")
                env.card_get("C-11")
                env.card_move(card_id="C-11", status="in_review", note="Escalated payment outage into engineering review.")
                return None
            if task_id == "pb-task-2":
                env.card_list(priority="high")
                env.card_assign(card_id="C-10", assignee="sam", note="Sam is taking triage.")
                env.comment_add(card_id="C-10", body="Triage comment added for Sam.")
                return None
            cards = env.card_list(status="in_progress", assignee="eve")
            return {"status": "in_progress", "assignee": "eve", "card_count": len(cards), "highest_priority": "medium" if cards else "none"}


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    ).strip() + "\n"


def _seed_state() -> dict[str, Any]:
    return {
        "board": [{"id": "board-alpha", "name": "Launch Board", "workflow_statuses": ["todo", "in_progress", "blocked", "in_review", "done"]}],
        "card": [
            {"id": "C-10", "board_id": "board-alpha", "title": "Checkout bug", "status": "todo", "priority": "high", "assignee": "unassigned"},
            {"id": "C-11", "board_id": "board-alpha", "title": "Payment API failing", "status": "blocked", "priority": "urgent", "assignee": "mei"},
            {"id": "C-12", "board_id": "board-alpha", "title": "Settings page polish", "status": "in_progress", "priority": "medium", "assignee": "eve"},
        ],
        "comment": [],
        "audit_event": [],
    }


def _surface_descriptor() -> dict[str, Any]:
    return {
        "environment_id": "project-board-lite",
        "implemented_surfaces": {
            "python": {"status": "implemented", "entrypoint": "runtime.ProjectBoardLite", "verified_by": "check_replay.py"},
            "cli": {"status": "deferred", "reason": "CLI help is source evidence only for this runner fixture."},
            "http": {"status": "deferred"},
            "mcp": {"status": "deferred"},
        },
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
