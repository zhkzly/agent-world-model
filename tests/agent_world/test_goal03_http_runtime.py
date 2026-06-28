import json
import threading
import urllib.request

from agent_world.full_chain import run_support_desk_lite_full_chain
from agent_world.http_runtime import create_http_server


def test_goal03_http_runtime_starts_and_executes_online_session(tmp_path):
    package_dir = run_support_desk_lite_full_chain(tmp_path / "envpkg").workflow.package.package_dir
    server = create_http_server(package_dir, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        health = _get_json(f"{base_url}/health")
        assert health["status"] == "ok"
        assert health["started"] is True

        reset = _post_json(f"{base_url}/reset", {"task_id": "task-1", "run_id": "http-runtime-test"})
        session_id = reset["session_id"]
        assert reset["observation"]["task_id"] == "task-1"

        _post_json(
            f"{base_url}/step",
            {
                "session_id": session_id,
                "action": {
                    "action_id": "http-1",
                    "kind": "tool_call",
                    "tool_name": "search_tickets",
                    "arguments": {"status": "open", "customer_tier": "vip", "keyword": "refund"},
                },
            },
        )
        _post_json(
            f"{base_url}/step",
            {
                "session_id": session_id,
                "action": {
                    "action_id": "http-2",
                    "kind": "tool_call",
                    "tool_name": "get_ticket",
                    "arguments": {"ticket_id": "T-100"},
                },
            },
        )
        _post_json(
            f"{base_url}/step",
            {
                "session_id": session_id,
                "action": {
                    "action_id": "http-3",
                    "kind": "tool_call",
                    "tool_name": "add_ticket_note",
                    "arguments": {
                        "ticket_id": "T-100",
                        "visibility": "internal",
                        "body": "Refund follow-up queued with billing.",
                    },
                },
            },
        )
        final = _post_json(f"{base_url}/finalize", {"session_id": session_id})
        assert final["final"]["success"] is True
        assert final["final"]["reward"] == 1.0
        assert final["final"]["reward_source"] == "deterministic_verifier"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))
