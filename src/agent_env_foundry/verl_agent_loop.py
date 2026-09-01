"""Pinned veRL v0.9 Continuous Token bridge to the existing S3 Host."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.episode_runtime import (
    run_task_episode,
    write_episode_bundle,
)
from agent_env_foundry.episodes import DefectOwner, EpisodeDefect, PolicySpec, PublicEpisodeInput
from agent_env_foundry.preparation import prepare_release
from agent_env_foundry.public_agent import PUBLIC_AGENT_PROMPT_DIGEST, DriverDecision
from agent_env_foundry.release import canonical_bytes

_VERL_COMMIT = "483b8a009ba3a97563edee3a19887e4862b8094a"
_TARGET_KEYS = frozenset(
    "model_id revision tokenizer_id tokenizer_revision chat_template_source "
    "continuous_token_model_family tool_parser".split()
)

if TYPE_CHECKING:
    from collections.abc import Callable

    class _Metrics:
        def __init__(self, **kwargs: Any) -> None: ...

    class _Output:
        def __init__(self, **kwargs: Any) -> None: ...

    class _LoopBase:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        def __getattr__(self, name: str) -> Any: ...

    def _register(name: str) -> Callable[[type[_LoopBase]], type[_LoopBase]]: ...

    class _ParserFactory:
        @classmethod
        def get_tool_parser(cls, name: str, tokenizer: Any) -> Any: ...

else:
    from verl.experimental.agent_loop.agent_loop import AgentLoopBase as _LoopBase
    from verl.experimental.agent_loop.agent_loop import AgentLoopMetrics as _Metrics
    from verl.experimental.agent_loop.agent_loop import AgentLoopOutput as _Output
    from verl.experimental.agent_loop.agent_loop import register as _register
    from verl.experimental.agent_loop.tool_parser import ToolParser as _ParserFactory


class _PolicyDriver:
    def __init__(
        self,
        owner: FoundryS3AgentLoop,
        event_loop: asyncio.AbstractEventLoop,
        sampling_params: dict[str, Any],
        request_id: str,
    ) -> None:
        self.owner, self.event_loop = owner, event_loop
        self.sampling_params, self.request_id = dict(sampling_params), request_id
        self.started = self.closed = False
        self.messages: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self.prompt_ids: list[int] = []
        self.runtime_ids: list[int] = []
        self.response_mask: list[int] = []
        self.pending_call_ids: tuple[str, ...] = ()
        self.turn = 0

    @property
    def policy_spec(self) -> PolicySpec:
        return self.owner.policy_spec

    def start(self, public_input: PublicEpisodeInput) -> None:
        if self.started or self.closed:
            raise ValueError("veRL PolicyDriver is single-use")
        self.started = True
        asyncio.run_coroutine_threadsafe(self._start(public_input), self.event_loop).result()

    async def _start(self, public_input: PublicEpisodeInput) -> None:
        user = canonical_bytes(
            {
                "instruction": public_input.instruction,
                "reset_observation": public_input.reset_observation,
            }
        ).decode()
        self.messages = [
            {"role": "system", "content": public_input.system_prompt},
            {"role": "user", "content": user},
        ]
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["input_schema"],
                },
            }
            for spec in public_input.tool_specs
        ]
        self.prompt_ids = await self.owner.ct_build_initial_tokens(self.messages, tools=self.tools)
        self.runtime_ids = list(self.prompt_ids)

    def next_decision(
        self, prior_public_results: tuple[tuple[str, JSONObject], ...]
    ) -> DriverDecision:
        if not self.started or self.closed:
            raise ValueError("veRL PolicyDriver is not active")
        return asyncio.run_coroutine_threadsafe(
            self._next(prior_public_results), self.event_loop
        ).result()

    async def _next(
        self, prior_public_results: tuple[tuple[str, JSONObject], ...]
    ) -> DriverDecision:
        if prior_public_results:
            if tuple(item[0] for item in prior_public_results) != self.pending_call_ids:
                return DriverDecision(
                    defect=EpisodeDefect(
                        "evidence", "tool_result_binding_mismatch", "continuous_token_merge"
                    )
                )
            previous = list(self.messages)
            self.messages.extend(
                {"role": "tool", "content": canonical_bytes(observation).decode()}
                for _call_id, observation in prior_public_results
            )
            try:
                merged, mask, _ = await self.owner.ct_merge_non_assistant_msg(
                    previous,
                    self.messages,
                    self.runtime_ids,
                    self.response_mask,
                    tools=self.tools,
                )
            except Exception as exc:
                return _defect("evidence", exc, "continuous_token_observation")
            self.runtime_ids, self.response_mask = list(merged.token_ids), list(mask)
            self.pending_call_ids = ()
        try:
            generated = await self.owner.server_manager.generate(
                request_id=self.request_id,
                prompt_ids=self.runtime_ids,
                sampling_params=self.sampling_params,
            )
        except Exception as exc:
            return _defect("provider", exc, "verl_generate")
        exact_ids = list(generated.token_ids)
        try:
            merged, mask, _ = await self.owner.ct_merge_assistant_token(
                self.runtime_ids, exact_ids, self.response_mask
            )
        except Exception as exc:
            return _defect("evidence", exc, "continuous_token_assistant")
        self.runtime_ids, self.response_mask = list(merged.token_ids), list(mask)
        if len(self.response_mask) > self.owner.response_length:
            raise ValueError("continuous-token response exceeds veRL response_length")
        try:
            content, tool_calls = await self.owner.tool_parser.extract_tool_calls(exact_ids)
        except Exception as exc:
            return _defect("evidence", exc, "hermes_tool_parse")
        self.turn += 1
        assistant: dict[str, Any] = {"role": "assistant", "content": content or ""}
        calls = [
            (f"call-{self.turn}-{index}", call.name, call.arguments)
            for index, call in enumerate(tool_calls, 1)
        ]
        if calls:
            assistant["tool_calls"] = [
                {
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.loads(call.arguments)},
                }
                for call in tool_calls
            ]
            self.pending_call_ids = tuple(item[0] for item in calls)
        self.messages.append(assistant)
        if calls:
            return DriverDecision(calls=tuple(calls))
        terminal = content if isinstance(content, str) and content.strip() else None
        return DriverDecision(
            terminal_kind="final_answer" if terminal is not None else "none",
            raw_public_terminal=terminal,
        )

    def close(self) -> None:
        self.closed = True

    def output_tokens(self) -> tuple[list[int], list[int], list[int]]:
        length = len(self.response_mask)
        if not length:
            return list(self.runtime_ids), [], []
        return (
            list(self.runtime_ids[:-length]),
            list(self.runtime_ids[-length:]),
            list(self.response_mask),
        )


@_register("foundry_s3")
class FoundryS3AgentLoop(_LoopBase):
    """One adapter only; the unchanged S3 runtime owns actions and terminal truth."""

    def __init__(
        self,
        *args: Any,
        policy_model_id: str,
        max_provider_turns: int,
        target_model: Mapping[str, str],
        verl_commit: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        target = dict(target_model)
        valid_target = set(target) == _TARGET_KEYS and all(
            isinstance(value, str) and value for value in target.values()
        )
        if verl_commit != _VERL_COMMIT or not valid_target:
            raise ValueError("AgentLoop target identity differs from the frozen S4 pin")
        if target["continuous_token_model_family"] != "qwen" or target["tool_parser"] != "hermes":
            raise ValueError("AgentLoop requires the frozen qwen/hermes target")
        if not self.enable_continuous_token or self.processor is not None:
            raise ValueError("FoundryS3AgentLoop requires text-only Continuous Token")
        self.target_model, self.verl_commit = target, verl_commit
        self._policy_spec = PolicySpec(
            policy_model_id,
            "verl-agent-loop",
            "1",
            "verl:v0.9.0",
            PUBLIC_AGENT_PROMPT_DIGEST,
            max_provider_turns,
        )
        self.tool_parser = _ParserFactory.get_tool_parser("hermes", self.tokenizer)
        self.response_length = int(self.rollout_config.response_length)

    @property
    def policy_spec(self) -> PolicySpec:
        return self._policy_spec

    async def run(self, sampling_params: dict[str, Any], **kwargs: Any) -> _Output:
        event_loop = asyncio.get_running_loop()
        self.loop = event_loop
        uid = _required(kwargs, "uid")
        session_id = kwargs.get("session_id")
        if not isinstance(session_id, int) or session_id < 0:
            raise ValueError("session_id must be a nonnegative integer")
        expected_release_id = _required(kwargs, "expected_release_id")
        task_pack_id = _required(kwargs, "task_pack_id")
        release_path = Path(_required(kwargs, "release_path"))
        release_cache_root = Path(_required(kwargs, "release_cache_root"))
        task_pack_path = Path(_required(kwargs, "task_pack_path"))
        instance_root = Path(_required(kwargs, "instance_root"))
        output_root = Path(_required(kwargs, "episode_output_root"))
        instance_key = hashlib.sha256(f"{uid}\0{session_id}".encode()).hexdigest()
        driver = _PolicyDriver(self, event_loop, sampling_params, f"{uid}:{session_id}")

        def execute_s3() -> tuple[Any, Any]:
            prepared = prepare_release(release_path, release_cache_root)
            if prepared.identity.release_id != expected_release_id:
                raise ValueError("prepared Release differs from the rollout row")
            record = run_task_episode(
                prepared,
                task_pack_path,
                task_pack_id,
                policy_driver=driver,
                rollout_index=session_id + 1,
                instance_root=instance_root / instance_key,
            )
            return record, write_episode_bundle(output_root, record)

        record, cold = await asyncio.to_thread(execute_s3)
        prompt_ids, response_ids, response_mask = driver.output_tokens()
        if len(response_ids) != len(response_mask) or any(
            mask not in {0, 1} for mask in response_mask
        ):
            raise ValueError("Continuous Token output has an invalid response mask")
        if (
            cold.episode_id != record.episode_id
            or cold.request_id != record.request.request_id
            or cold.disposition != record.reward.disposition
            or cold.reward != record.reward.reward
        ):
            raise ValueError("cold Episode view differs from finalized S3 reward identity")
        receipt: JSONObject = {
            "format": "verl-rollout-binding/1",
            "episode_id": record.episode_id,
            "request_id": record.request.request_id,
            "release_id": record.request.release_id,
            "task_pack_id": record.request.task_pack_id,
            "policy_id": record.request.policy_id,
            "rollout_index": record.request.rollout_index,
            "group_id": uid,
            "response_ids": cast(list[JSONValue], response_ids),
            "response_mask": cast(list[JSONValue], response_mask),
            "disposition": cold.disposition,
            "reward": cold.reward,
            "verl_commit": self.verl_commit,
            "target_model": cast(JSONObject, self.target_model),
            "sampling_params": cast(JSONObject, dict(sampling_params)),
        }
        receipt_path = await asyncio.to_thread(_write_receipt, output_root, receipt)
        return _Output(
            prompt_ids=prompt_ids,
            response_ids=response_ids,
            response_mask=response_mask,
            reward_score=cold.reward,
            num_turns=len(record.capture.turns) + 1,
            metrics=_Metrics(),
            extra_fields={"episode_id": record.episode_id, "rollout_receipt": str(receipt_path)},
        )


def _defect(owner: DefectOwner, error: Exception, phase: str) -> DriverDecision:
    return DriverDecision(defect=EpisodeDefect(owner, f"verl_{type(error).__name__}", phase))


def _required(values: Mapping[str, Any], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _write_receipt(output_root: Path, receipt: JSONObject) -> Path:
    directory = Path(output_root) / "rollout-receipts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{receipt['episode_id']}.json"
    with path.open("xb") as handle:
        handle.write(canonical_bytes(receipt))
    return path
