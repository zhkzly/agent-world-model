"""Single-session Unix-socket server that owns all private rollout state."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import stat
import sys
from pathlib import Path
from typing import Any

from agent_world.app import open_consumption
from agent_world.config import load_foundry_config
from agent_world.consumer.service import LocalConsumerError, LocalEpisode
from agent_world.contracts import (
    LocalEnvRpcError,
    LocalEnvRpcRequest,
    LocalEnvRpcResponse,
    RolloutAction,
    canonical_json_bytes,
)

from .rpc import (
    LOCAL_ENV_RPC_AUTH_ENV,
    LOCAL_ENV_RPC_MAX_REQUEST_BYTES,
    LOCAL_ENV_RPC_MAX_RESPONSE_BYTES,
    _decode_json_object,
)

_STEP_TIMEOUT_SECONDS = 120.0


class _SingleSessionServer:
    def __init__(
        self,
        *,
        socket_path: Path,
        auth_token: str,
        snapshot_id: str,
        seed: int,
        config_path: Path,
    ) -> None:
        config = load_foundry_config(config_path)
        self._application = open_consumption(config)
        self._socket_path = socket_path
        self._auth_token = auth_token
        self._snapshot_id = snapshot_id
        self._seed = seed
        self._start_timeout_seconds = config.judge.clean_build_timeout_seconds + 60.0
        self._episode: LocalEpisode | None = None
        self._claimed = False
        self._closed = asyncio.Event()
        self._request_ids: set[str] = set()

    async def serve(self) -> None:
        parent = self._socket_path.parent.resolve(strict=True)
        mode = stat.S_IMODE(parent.stat(follow_symlinks=False).st_mode)
        if parent.is_symlink() or not parent.is_dir() or mode & 0o077:
            raise RuntimeError("service socket parent must be a private real directory")
        if self._socket_path.exists() or self._socket_path.is_symlink():
            raise RuntimeError("service socket path already exists")
        server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
            limit=LOCAL_ENV_RPC_MAX_REQUEST_BYTES + 1,
        )
        self._socket_path.chmod(0o600)
        try:
            async with server:
                await self._closed.wait()
        finally:
            server.close()
            await server.wait_closed()
            if self._episode is not None:
                await self._episode.close()
                self._episode = None
            try:
                if stat.S_ISSOCK(self._socket_path.lstat().st_mode):
                    self._socket_path.unlink()
            except FileNotFoundError:
                pass

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if self._claimed:
            writer.close()
            await writer.wait_closed()
            return
        self._claimed = True
        try:
            while True:
                try:
                    raw = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    await self._write_error(
                        writer,
                        request_id="rpc_invalid",
                        code="request_too_large",
                        message="local env RPC request exceeded its byte limit",
                    )
                    return
                if not raw:
                    return
                if len(raw) > LOCAL_ENV_RPC_MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                    await self._write_error(
                        writer,
                        request_id="rpc_invalid",
                        code="request_too_large",
                        message="local env RPC request exceeded its byte limit",
                    )
                    return
                try:
                    request = LocalEnvRpcRequest.model_validate_json(
                        canonical_json_bytes(_decode_json_object(raw[:-1]))
                    )
                except Exception:
                    await self._write_error(
                        writer,
                        request_id="rpc_invalid",
                        code="invalid_request",
                        message="local env RPC request violated its closed schema",
                    )
                    return
                if not secrets.compare_digest(request.auth_token, self._auth_token):
                    await self._write_error(
                        writer,
                        request_id=request.request_id,
                        code="unauthorized",
                        message="local env RPC authentication failed",
                    )
                    return
                if request.request_id in self._request_ids:
                    await self._write_error(
                        writer,
                        request_id=request.request_id,
                        code="duplicate_request",
                        message="local env RPC request id was already used",
                    )
                    return
                self._request_ids.add(request.request_id)
                response, should_close = await self._dispatch(request)
                await self._write_response(writer, response)
                if should_close:
                    return
        finally:
            if self._episode is not None:
                await self._episode.close()
                self._episode = None
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionError):
                pass
            self._closed.set()

    async def _dispatch(
        self,
        request: LocalEnvRpcRequest,
    ) -> tuple[LocalEnvRpcResponse, bool]:
        try:
            if request.operation == "start":
                if self._episode is not None:
                    raise LocalConsumerError(
                        "episode_already_started",
                        "this service session already owns an episode",
                    )
                self._episode = await asyncio.wait_for(
                    self._application.rollout.start(
                        self._snapshot_id,
                        seed=self._seed,
                    ),
                    timeout=self._start_timeout_seconds,
                )
                result: Any = self._episode.start_result().model_dump(mode="json")
            elif request.operation == "step":
                episode = self._require_episode()
                action = RolloutAction.model_validate_json(canonical_json_bytes(request.payload))
                result = (
                    await asyncio.wait_for(
                        episode.step(action),
                        timeout=_STEP_TIMEOUT_SECONDS,
                    )
                ).model_dump(mode="json")
            elif request.operation == "result":
                result = self._require_episode().result().model_dump(mode="json")
            else:
                if self._episode is not None:
                    await self._episode.close()
                    self._episode = None
                result = {"closed": True}
                return self._success(request.request_id, result), True
            return self._success(request.request_id, result), False
        except TimeoutError:
            return (
                self._failure(
                    request.request_id,
                    "service_timeout",
                    f"local env service timed out during {request.operation}",
                ),
                True,
            )
        except LocalConsumerError as exc:
            return self._failure(request.request_id, exc.code, str(exc)), True
        except Exception:
            return (
                self._failure(
                    request.request_id,
                    "service_operation_failed",
                    f"local env service failed during {request.operation}",
                ),
                True,
            )

    def _require_episode(self) -> LocalEpisode:
        if self._episode is None:
            raise LocalConsumerError(
                "episode_not_started",
                "start must complete before this operation",
            )
        return self._episode

    @staticmethod
    def _success(request_id: str, result: Any) -> LocalEnvRpcResponse:
        return LocalEnvRpcResponse(request_id=request_id, ok=True, result=result)

    @staticmethod
    def _failure(request_id: str, code: str, message: str) -> LocalEnvRpcResponse:
        return LocalEnvRpcResponse(
            request_id=request_id,
            ok=False,
            error=LocalEnvRpcError(code=code, message=message),
        )

    async def _write_error(
        self,
        writer: asyncio.StreamWriter,
        *,
        request_id: str,
        code: str,
        message: str,
    ) -> None:
        await self._write_response(writer, self._failure(request_id, code, message))

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        response: LocalEnvRpcResponse,
    ) -> None:
        encoded = response.stable_json_bytes() + b"\n"
        if len(encoded) > LOCAL_ENV_RPC_MAX_RESPONSE_BYTES:
            encoded = (
                self._failure(
                    response.request_id,
                    "response_too_large",
                    "local env RPC response exceeded its byte limit",
                ).stable_json_bytes()
                + b"\n"
            )
        writer.write(encoded)
        await writer.drain()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--seed", required=True, type=int)
    return parser


async def _run(argv: list[str] | None = None) -> None:
    arguments = _build_parser().parse_args(argv)
    auth_token = os.environ.pop(LOCAL_ENV_RPC_AUTH_ENV, None)
    if auth_token is None:
        raise RuntimeError("local env service authentication is not configured")
    server = _SingleSessionServer(
        socket_path=arguments.socket,
        auth_token=auth_token,
        snapshot_id=arguments.snapshot,
        seed=arguments.seed,
        config_path=arguments.config,
    )
    task = asyncio.create_task(server.serve(), name="local-env-service")
    loop = asyncio.get_running_loop()
    for signal_value in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_value, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        for signal_value in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signal_value)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    try:
        asyncio.run(_run(argv))
    except BaseException as exc:
        payload = {
            "error": {
                "code": "service_start_failed",
                "type": type(exc).__name__,
            }
        }
        sys.stderr.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        sys.stderr.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
