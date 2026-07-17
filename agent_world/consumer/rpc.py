"""Authenticated client and trusted launcher for the local env service process."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from agent_world.contracts import (
    LocalEnvRpcRequest,
    LocalEnvRpcResponse,
    LocalEpisodeStart,
    LocalRolloutResult,
    RolloutAction,
    RolloutStep,
    canonical_json_bytes,
)

LOCAL_ENV_RPC_AUTH_ENV = "AGENT_WORLD_LOCAL_ENV_AUTH_TOKEN"
LOCAL_ENV_RPC_MAX_REQUEST_BYTES = 1024 * 1024
LOCAL_ENV_RPC_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_DEFAULT_START_TIMEOUT_SECONDS = 660.0
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
_MAX_SERVICE_STDERR_BYTES = 64 * 1024


class LocalEnvServiceError(RuntimeError):
    """The service boundary rejected or could not complete an operation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalEnvRpcClient:
    """Public-only client; it has no Registry, envpkg path, or private task object."""

    __slots__ = (
        "_auth_token",
        "_closed",
        "_finished",
        "_lock",
        "_reader",
        "_request_counter",
        "_request_timeout_seconds",
        "_start_timeout_seconds",
        "_started",
        "_writer",
    )

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        auth_token: str,
        *,
        start_timeout_seconds: float = _DEFAULT_START_TIMEOUT_SECONDS,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if start_timeout_seconds <= 0 or request_timeout_seconds <= 0:
            raise ValueError("local env RPC timeouts must be positive")
        self._reader = reader
        self._writer = writer
        self._auth_token = auth_token
        self._start_timeout_seconds = start_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._request_counter = 0
        self._lock = asyncio.Lock()
        self._started = False
        self._finished = False
        self._closed = False

    @classmethod
    async def connect(
        cls,
        socket_path: Path,
        auth_token: str,
        *,
        timeout_seconds: float,
        start_timeout_seconds: float = _DEFAULT_START_TIMEOUT_SECONDS,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> LocalEnvRpcClient:
        if os.name != "posix":
            raise LocalEnvServiceError(
                "unix_socket_unavailable",
                "local env service currently requires a POSIX Unix socket",
            )
        try:
            async with asyncio.timeout(timeout_seconds):
                reader, writer = await asyncio.open_unix_connection(
                    str(socket_path),
                    limit=LOCAL_ENV_RPC_MAX_RESPONSE_BYTES + 1,
                )
        except TimeoutError as exc:
            raise LocalEnvServiceError(
                "service_connect_timeout",
                "timed out connecting to the local env service",
            ) from exc
        return cls(
            reader,
            writer,
            auth_token,
            start_timeout_seconds=start_timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )

    async def start(self) -> LocalEpisodeStart:
        if self._started:
            raise LocalEnvServiceError("episode_already_started", "episode was already started")
        result = await self._request(
            "start",
            {},
            timeout_seconds=self._start_timeout_seconds,
        )
        try:
            started = LocalEpisodeStart.model_validate_json(canonical_json_bytes(result))
        except Exception as exc:
            await self.abort()
            raise LocalEnvServiceError(
                "invalid_service_response",
                "service returned an invalid public episode start",
            ) from exc
        self._started = True
        return started

    async def step(self, action: RolloutAction) -> RolloutStep:
        if not self._started:
            raise LocalEnvServiceError("episode_not_started", "episode must be started first")
        if self._finished:
            raise LocalEnvServiceError("episode_finished", "episode is already finished")
        result = await self._request(
            "step",
            action.model_dump(mode="json"),
            timeout_seconds=self._request_timeout_seconds,
        )
        try:
            step = RolloutStep.model_validate_json(canonical_json_bytes(result))
        except Exception as exc:
            await self.abort()
            raise LocalEnvServiceError(
                "invalid_service_response",
                "service returned an invalid public rollout step",
            ) from exc
        self._finished = step.terminated or step.truncated
        return step

    async def result(self) -> LocalRolloutResult:
        if not self._started:
            raise LocalEnvServiceError("episode_not_started", "episode must be started first")
        result = await self._request(
            "result",
            {},
            timeout_seconds=self._request_timeout_seconds,
        )
        try:
            return LocalRolloutResult.model_validate_json(canonical_json_bytes(result))
        except Exception as exc:
            await self.abort()
            raise LocalEnvServiceError(
                "invalid_service_response",
                "service returned an invalid public rollout result",
            ) from exc

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._request(
                "close",
                {},
                timeout_seconds=self._request_timeout_seconds,
            )
        finally:
            await self.abort()

    async def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (BrokenPipeError, ConnectionError):
            pass

    async def _request(
        self,
        operation: Literal["start", "step", "result", "close"],
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> Any:
        if self._closed:
            raise LocalEnvServiceError("service_closed", "local env service client is closed")
        async with self._lock:
            self._request_counter += 1
            request_id = f"rpc_{self._request_counter:016x}"
            request = LocalEnvRpcRequest(
                request_id=request_id,
                auth_token=self._auth_token,
                operation=operation,
                payload=payload,
            )
            encoded = request.stable_json_bytes() + b"\n"
            if len(encoded) > LOCAL_ENV_RPC_MAX_REQUEST_BYTES:
                raise LocalEnvServiceError(
                    "request_too_large",
                    "local env RPC request exceeds its byte limit",
                )
            try:
                async with asyncio.timeout(timeout_seconds):
                    self._writer.write(encoded)
                    await self._writer.drain()
                    raw = await self._reader.readline()
            except TimeoutError as exc:
                await self.abort()
                raise LocalEnvServiceError(
                    "service_timeout",
                    f"local env service timed out during {operation}",
                ) from exc
            except (BrokenPipeError, ConnectionError, ValueError) as exc:
                await self.abort()
                raise LocalEnvServiceError(
                    "service_transport",
                    "local env service transport failed",
                ) from exc
            if not raw:
                await self.abort()
                raise LocalEnvServiceError(
                    "service_disconnected",
                    "local env service disconnected without a response",
                )
            if len(raw) > LOCAL_ENV_RPC_MAX_RESPONSE_BYTES or not raw.endswith(b"\n"):
                await self.abort()
                raise LocalEnvServiceError(
                    "response_too_large",
                    "local env service response violated its byte limit",
                )
            try:
                response = LocalEnvRpcResponse.model_validate_json(
                    canonical_json_bytes(_decode_json_object(raw[:-1]))
                )
            except Exception as exc:
                await self.abort()
                raise LocalEnvServiceError(
                    "invalid_service_response",
                    "local env service returned an invalid response envelope",
                ) from exc
            if response.request_id != request_id:
                await self.abort()
                raise LocalEnvServiceError(
                    "response_mismatch",
                    "local env service response id did not match its request",
                )
            if not response.ok:
                assert response.error is not None
                raise LocalEnvServiceError(response.error.code, response.error.message)
            return response.result

    async def __aenter__(self) -> LocalEnvRpcClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


class LocalEnvServiceProcess:
    """Trusted process owner; hand only ``client`` to the training-side adapter."""

    __slots__ = ("_client", "_closed", "_process", "_stderr", "_stderr_task", "_temp")

    def __init__(
        self,
        *,
        process: asyncio.subprocess.Process,
        client: LocalEnvRpcClient,
        temp: tempfile.TemporaryDirectory[str],
        stderr_task: asyncio.Task[bytes],
    ) -> None:
        self._process = process
        self._client = client
        self._temp = temp
        self._stderr_task = stderr_task
        self._stderr = b""
        self._closed = False

    @property
    def client(self) -> LocalEnvRpcClient:
        return self._client

    @property
    def pid(self) -> int:
        assert self._process.pid is not None
        return self._process.pid

    @property
    def stderr(self) -> str:
        value = self._stderr
        if self._stderr_task.done() and not value:
            try:
                value = self._stderr_task.result()
            except BaseException:
                value = b""
        return value.decode("utf-8", errors="replace")

    @classmethod
    async def launch(
        cls,
        *,
        config_path: Path,
        snapshot_id: str,
        seed: int,
        startup_timeout_seconds: float = 30.0,
        start_timeout_seconds: float = _DEFAULT_START_TIMEOUT_SECONDS,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> LocalEnvServiceProcess:
        if os.name != "posix":
            raise LocalEnvServiceError(
                "unix_socket_unavailable",
                "local env service currently requires a POSIX Unix socket",
            )
        if startup_timeout_seconds <= 0:
            raise ValueError("service startup timeout must be positive")
        resolved_config, temp, socket_path = await asyncio.to_thread(
            _prepare_service_paths,
            config_path,
        )
        auth_token = secrets.token_urlsafe(32)
        environment = _service_environment(auth_token)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "agent_world.consumer.rpc_server",
            "--config",
            str(resolved_config),
            "--socket",
            str(socket_path),
            "--snapshot",
            snapshot_id,
            "--seed",
            str(seed),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        assert process.stderr is not None
        stderr_task = asyncio.create_task(
            _read_limited(process.stderr, _MAX_SERVICE_STDERR_BYTES),
            name=f"local-env-service-stderr-{process.pid}",
        )
        deadline = asyncio.get_running_loop().time() + startup_timeout_seconds
        try:
            while True:
                if process.returncode is not None:
                    stderr = await stderr_task
                    raise LocalEnvServiceError(
                        "service_start_failed",
                        _safe_start_failure(stderr),
                    )
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise LocalEnvServiceError(
                        "service_start_timeout",
                        "timed out starting the local env service process",
                    )
                try:
                    client = await LocalEnvRpcClient.connect(
                        socket_path,
                        auth_token,
                        timeout_seconds=min(remaining, 0.25),
                        start_timeout_seconds=start_timeout_seconds,
                        request_timeout_seconds=request_timeout_seconds,
                    )
                except (FileNotFoundError, ConnectionRefusedError, LocalEnvServiceError):
                    await asyncio.sleep(min(0.025, remaining))
                    continue
                return cls(
                    process=process,
                    client=client,
                    temp=temp,
                    stderr_task=stderr_task,
                )
        except BaseException:
            await _terminate_service_process(process)
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
            temp.cleanup()
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                await self._client.close()
            except LocalEnvServiceError:
                pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10.0)
            except TimeoutError:
                await _terminate_service_process(self._process)
            self._stderr = await self._stderr_task
        finally:
            self._temp.cleanup()

    async def __aenter__(self) -> LocalEnvServiceProcess:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


def _decode_json_object(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is prohibited: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    decoded = json.loads(
        raw,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(decoded, dict):
        raise ValueError("RPC message must be a JSON object")
    return decoded


def _service_environment(auth_token: str) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        LOCAL_ENV_RPC_AUTH_ENV: auth_token,
    }
    if "TMPDIR" in os.environ:
        environment["TMPDIR"] = os.environ["TMPDIR"]
    return environment


def _prepare_service_paths(
    config_path: Path,
) -> tuple[Path, tempfile.TemporaryDirectory[str], Path]:
    resolved_config = config_path.expanduser().resolve(strict=True)
    config_status = resolved_config.stat(follow_symlinks=False)
    if config_path.expanduser().is_symlink() or not stat.S_ISREG(config_status.st_mode):
        raise LocalEnvServiceError(
            "invalid_service_config",
            "local env service config must be a regular non-symlink file",
        )
    temp = tempfile.TemporaryDirectory(prefix="agent-world-local-env-service-")
    try:
        temp_root = Path(temp.name)
        temp_root.chmod(0o700)
        return resolved_config, temp, temp_root / "service.sock"
    except BaseException:
        temp.cleanup()
        raise


async def _read_limited(stream: asyncio.StreamReader, limit: int) -> bytes:
    captured = bytearray()
    while True:
        chunk = await stream.read(16 * 1024)
        if not chunk:
            return bytes(captured)
        remaining = limit - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])


async def _terminate_service_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    await process.wait()


def _safe_start_failure(stderr: bytes) -> str:
    try:
        value = _decode_json_object(stderr.strip())
    except Exception:
        return "local env service process failed during startup"
    error = value.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return f"local env service process failed during startup ({error['code']})"
    return "local env service process failed during startup"


__all__ = [
    "LOCAL_ENV_RPC_AUTH_ENV",
    "LOCAL_ENV_RPC_MAX_REQUEST_BYTES",
    "LOCAL_ENV_RPC_MAX_RESPONSE_BYTES",
    "LocalEnvRpcClient",
    "LocalEnvServiceError",
    "LocalEnvServiceProcess",
]
