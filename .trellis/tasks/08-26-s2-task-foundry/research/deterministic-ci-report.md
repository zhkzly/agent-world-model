# Deterministic S2 CI report

Commit tested: `acd987e35c9514c306087fa2011eae4afb4078fe`

| Gate | Exit status |
| --- | ---: |
| uv sync --frozen --all-groups | 0 |
| ruff check src tests | 0 |
| ruff format --check src tests | 0 |
| mypy src | 1 |
| pytest -q | 0 |

This report contains no model/provider execution. A nonzero status is a real deterministic failure, not a skipped live-model test.

## sync

```text
Using CPython 3.12.3 interpreter at: /usr/bin/python3.12
Creating virtual environment at: .venv
   Building agent-env-foundry @ file:///home/runner/work/agent-world-model/agent-world-model
Downloading scipy (33.7MiB)
Downloading numpy (15.9MiB)
Downloading pillow (6.6MiB)
Downloading tokenizers (3.2MiB)
Downloading shapely (3.0MiB)
Downloading aiohttp (1.7MiB)
Downloading chardet (1.4MiB)
Downloading ast-serialize (1.2MiB)
Downloading pygments (1.2MiB)
Downloading tiktoken (1.1MiB)
Downloading unclecode-litellm (17.2MiB)
Downloading brotli (1.4MiB)
Downloading openai (1.6MiB)
Downloading pydantic-core (2.0MiB)
Downloading cryptography (4.5MiB)
Downloading playwright (45.5MiB)
Downloading mypy (14.6MiB)
Downloading lxml (5.0MiB)
Downloading networkx (2.0MiB)
Downloading patchright (45.5MiB)
Downloading ruff (9.8MiB)
Downloading hf-xet (4.3MiB)
Downloading openai-codex-cli-bin (114.4MiB)
Downloading nltk (1.7MiB)
 Downloaded ast-serialize
 Downloaded tiktoken
 Downloaded brotli
 Downloaded chardet
 Downloaded aiohttp
 Downloaded pygments
 Downloaded pydantic-core
 Downloaded shapely
 Downloaded networkx
 Downloaded tokenizers
 Downloaded nltk
      Built agent-env-foundry @ file:///home/runner/work/agent-world-model/agent-world-model
 Downloaded hf-xet
 Downloaded cryptography
 Downloaded lxml
 Downloaded pillow
 Downloaded ruff
 Downloaded openai
 Downloaded numpy
 Downloaded scipy
 Downloaded patchright
 Downloaded playwright
 Downloaded openai-codex-cli-bin
 Downloaded mypy
 Downloaded unclecode-litellm
Prepared 107 packages in 5.21s
Installed 107 packages in 960ms
 + agent-env-foundry==0.1.0 (from file:///home/runner/work/agent-world-model/agent-world-model)
 + aiofiles==25.1.0
 + aiohappyeyeballs==2.7.1
 + aiohttp==3.14.3
 + aiosignal==1.4.0
 + aiosqlite==0.22.1
 + alphashape==1.3.1
 + annotated-types==0.8.0
 + anyio==4.14.2
 + ast-serialize==0.8.0
 + attrs==26.1.0
 + beautifulsoup4==4.15.0
 + brotli==1.2.0
 + certifi==2026.7.22
 + cffi==2.1.1
 + chardet==7.6.0
 + charset-normalizer==3.5.1
 + click==8.5.0
 + click-log==0.4.0
 + crawl4ai==0.9.2
 + cryptography==50.0.1
 + cssselect==1.5.0
 + defusedxml==0.7.1
 + fake-useragent==2.2.0
 + fastuuid==0.14.0
 + filelock==3.32.4
 + frozenlist==1.8.0
 + fsspec==2026.7.0
 + greenlet==3.5.5
 + h11==0.16.0
 + h2==4.4.1
 + hf-xet==1.6.0
 + hpack==4.2.0
 + httpcore==1.0.9
 + httpcore2==2.12.0
 + httpx==0.28.1
 + httpx2==2.12.0
 + huggingface-hub==1.28.0
 + humanize==4.16.0
 + hyperframe==6.1.0
 + idna==3.19
 + importlib-metadata==9.0.0
 + iniconfig==2.3.0
 + jinja2==3.1.6
 + jiter==0.16.0
 + joblib==1.5.3
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + lark==1.3.1
 + librt==0.15.0
 + lxml==6.1.2
 + markdown-it-py==4.2.0
 + markupsafe==3.0.3
 + mdurl==0.1.2
 + multidict==6.7.1
 + mypy==2.3.1
 + mypy-extensions==1.1.0
 + networkx==3.6.1
 + nltk==3.10.3
 + numpy==2.5.2
 + openai==3.3.1
 + openai-codex==0.147.0
 + openai-codex-cli-bin==0.147.0
 + packaging==26.3
 + patchright==1.62.1
 + pathspec==1.1.1
 + pillow==12.3.0
 + playwright==1.62.0
 + playwright-stealth==2.0.3
 + pluggy==1.6.0
 + propcache==0.5.2
 + psutil==7.2.2
 + pycparser==3.0
 + pydantic==2.13.4
 + pydantic-core==2.46.4
 + pyee==13.0.1
 + pygments==2.21.0
 + pyopenssl==26.4.0
 + pytest==9.1.1
 + python-dotenv==1.2.3
 + pyyaml==6.0.3
 + rank-bm25==0.2.2
 + referencing==0.37.0
 + regex==2026.7.19
 + requests==2.34.2
 + rfc8785==0.1.4
 + rich==15.0.0
 + rpds-py==2026.6.3
 + rtree==1.4.1
 + ruff==0.16.4
 + scipy==1.18.1
 + shapely==2.1.2
 + sniffio==1.3.1
 + snowballstemmer==2.2.0
 + soupsieve==2.9.2
 + tiktoken==0.14.0
 + tokenizers==0.23.1
 + tqdm==4.70.0
 + trimesh==5.0.0
 + truststore==0.10.4
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
 + unclecode-litellm==1.81.13
 + urllib3==2.7.0
 + xxhash==3.8.1
 + yarl==1.24.5
 + zipp==4.1.0
```

## ruff-check

```text
All checks passed!
```

## ruff-format

```text
45 files already formatted
```

## mypy

```text
src/agent_task_foundry/compiler.py:315: error: Value of type variable "SupportsRichComparisonT" of "min" cannot be "int | float | str | list[JSONValue] | dict[str, JSONValue] | None"  [type-var]
src/agent_task_foundry/compiler.py:315: error: Value of type variable "SupportsRichComparisonT" of "max" cannot be "int | float | str | list[JSONValue] | dict[str, JSONValue] | None"  [type-var]
src/agent_task_foundry/compiler.py:327: error: Unsupported operand types for < ("int" and "str")  [operator]
src/agent_task_foundry/compiler.py:327: error: Unsupported operand types for < ("float" and "str")  [operator]
src/agent_task_foundry/compiler.py:327: error: Unsupported operand types for < ("str" and "int")  [operator]
src/agent_task_foundry/compiler.py:327: error: Unsupported operand types for < ("str" and "float")  [operator]
src/agent_task_foundry/compiler.py:327: note: Both left and right operands are unions
src/agent_task_foundry/compiler.py:328: error: Unsupported operand types for <= ("int" and "str")  [operator]
src/agent_task_foundry/compiler.py:328: error: Unsupported operand types for <= ("float" and "str")  [operator]
src/agent_task_foundry/compiler.py:328: error: Unsupported operand types for <= ("str" and "int")  [operator]
src/agent_task_foundry/compiler.py:328: error: Unsupported operand types for <= ("str" and "float")  [operator]
src/agent_task_foundry/compiler.py:328: note: Both left and right operands are unions
src/agent_task_foundry/compiler.py:329: error: Unsupported operand types for > ("int" and "str")  [operator]
src/agent_task_foundry/compiler.py:329: error: Unsupported operand types for > ("float" and "str")  [operator]
src/agent_task_foundry/compiler.py:329: error: Unsupported operand types for > ("str" and "int")  [operator]
src/agent_task_foundry/compiler.py:329: error: Unsupported operand types for > ("str" and "float")  [operator]
src/agent_task_foundry/compiler.py:329: note: Both left and right operands are unions
src/agent_task_foundry/compiler.py:330: error: Unsupported operand types for >= ("int" and "str")  [operator]
src/agent_task_foundry/compiler.py:330: error: Unsupported operand types for >= ("float" and "str")  [operator]
src/agent_task_foundry/compiler.py:330: error: Unsupported operand types for >= ("str" and "int")  [operator]
src/agent_task_foundry/compiler.py:330: error: Unsupported operand types for >= ("str" and "float")  [operator]
src/agent_task_foundry/compiler.py:330: note: Both left and right operands are unions
src/agent_task_foundry/compiler.py:374: error: Incompatible types in assignment (expression has type "AtomGoal | AllGoal | IfGoal | ForEachGoal | None", variable has type "AtomGoal | AllGoal | IfGoal | ForEachGoal")  [assignment]
src/agent_task_foundry/foundry.py:402: error: Value of type variable "SupportsRichComparisonT" of "max" cannot be "int | float | str | list[JSONValue] | dict[str, JSONValue] | None"  [type-var]
src/agent_task_foundry/foundry.py:402: error: Value of type variable "SupportsRichComparisonT" of "min" cannot be "int | float | str | list[JSONValue] | dict[str, JSONValue] | None"  [type-var]
src/agent_task_foundry/runner.py:200: error: No overload variant of "create" of "Responses" matches argument types "str", "list[Any]", "list[dict[str, Any]]", "str", "bool", "bool"  [call-overload]
src/agent_task_foundry/runner.py:200: note: Possible overload variants:
src/agent_task_foundry/runner.py:200: note:     def create(self, *, background: bool | Omit | None = ..., context_management: Iterable[ContextManagement] | Omit | None = ..., conversation: str | ResponseConversationParamParam | Omit | None = ..., include: list[Literal['file_search_call.results', 'web_search_call.results', 'web_search_call.action.sources', 'message.input_image.image_url', 'computer_call_output.output.image_url', 'code_interpreter_call.outputs', 'reasoning.encrypted_content', 'message.output_text.logprobs']] | Omit | None = ..., input: str | list[EasyInputMessageParam | Message | ResponseOutputMessageParam | ResponseFileSearchToolCallParam | ResponseComputerToolCallParam | <27 more items>] | Omit = ..., instructions: str | Omit | None = ..., max_output_tokens: int | Omit | None = ..., max_tool_calls: int | Omit | None = ..., metadata: dict[str, str] | Omit | None = ..., model: Literal['o1-pro', 'o1-pro-2025-03-19', 'o3-pro', 'o3-pro-2025-06-10', 'o3-deep-research', 'o3-deep-research-2025-06-26', 'o4-mini-deep-research', 'o4-mini-deep-research-2025-06-26', 'computer-use-preview', 'computer-use-preview-2025-03-11', 'gpt-5.5-pro', 'gpt-5.5-pro-2026-04-23', 'gpt-5-codex', 'gpt-5-pro', 'gpt-5-pro-2025-10-06', 'gpt-5.1-codex-max', 'gpt-daybreak-blue-latest', 'gpt-daybreak-red-latest', 'gpt-5.6-cyber'] | str | Literal['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.5-2026-04-23', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.4-mini-2026-03-17', 'gpt-5.4-nano-2026-03-17', 'gpt-5.3-chat-latest', 'gpt-5.2', 'gpt-5.2-2025-12-11', 'gpt-5.2-chat-latest', 'gpt-5.2-pro', 'gpt-5.2-pro-2025-12-11', 'gpt-5.1', 'gpt-5.1-2025-11-13', 'gpt-5.1-codex', 'gpt-5.1-mini', 'gpt-5.1-chat-latest', 'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-5-2025-08-07', 'gpt-5-mini-2025-08-07', 'gpt-5-nano-2025-08-07', 'gpt-5-chat-latest', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4.1-2025-04-14', 'gpt-4.1-mini-2025-04-14', 'gpt-4.1-nano-2025-04-14', 'o4-mini', 'o4-mini-2025-04-16', 'o3', 'o3-2025-04-16', 'o3-mini', 'o3-mini-2025-01-31', 'o1', 'o1-2024-12-17', 'o1-preview', 'o1-preview-2024-09-12', 'o1-mini', 'o1-mini-2024-09-12', 'gpt-4o', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06', 'gpt-4o-2024-05-13', 'gpt-4o-audio-preview', 'gpt-4o-audio-preview-2024-10-01', 'gpt-4o-audio-preview-2024-12-17', 'gpt-4o-audio-preview-2025-06-03', 'gpt-4o-mini-audio-preview', 'gpt-4o-mini-audio-preview-2024-12-17', 'gpt-4o-search-preview', 'gpt-4o-mini-search-preview', 'gpt-4o-search-preview-2025-03-11', 'gpt-4o-mini-search-preview-2025-03-11', 'chatgpt-4o-latest', 'codex-mini-latest', 'gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'gpt-4-turbo', 'gpt-4-turbo-2024-04-09', 'gpt-4-0125-preview', 'gpt-4-turbo-preview', 'gpt-4-1106-preview', 'gpt-4-vision-preview', 'gpt-4', 'gpt-4-0314', 'gpt-4-0613', 'gpt-4-32k', 'gpt-4-32k-0314', 'gpt-4-32k-0613', 'gpt-3.5-turbo', 'gpt-3.5-turbo-16k', 'gpt-3.5-turbo-0301', 'gpt-3.5-turbo-0613', 'gpt-3.5-turbo-1106', 'gpt-3.5-turbo-0125', 'gpt-3.5-turbo-16k-0613'] | Omit = ..., moderation: Moderation | Omit | None = ..., parallel_tool_calls: bool | Omit | None = ..., previous_response_id: str | Omit | None = ..., prompt: ResponsePromptParam | Omit | None = ..., prompt_cache_key: str | Omit | None = ..., prompt_cache_options: PromptCacheOptions | Omit = ..., prompt_cache_retention: Literal['in_memory', '24h'] | Omit | None = ..., reasoning: Reasoning | Omit | None = ..., safety_identifier: str | Omit | None = ..., service_tier: Literal['auto', 'default', 'flex', 'scale', 'priority', 'fast', 'ultrafast'] | None | Omit | None = ..., store: bool | Omit | None = ..., stream: Literal[False] | Omit | None = ..., stream_options: StreamOptions | Omit | None = ..., temperature: float | Omit | None = ..., text: ResponseTextConfigParam | Omit = ..., tool_choice: Literal['none', 'auto', 'required'] | ToolChoiceAllowedParam | ToolChoiceTypesParam | ToolChoiceFunctionParam | ToolChoiceMcpParam | ToolChoiceCustomParam | ToolChoiceSpecificProgrammaticToolCallingParam | ToolChoiceApplyPatchParam | ToolChoiceShellParam | Omit = ..., tools: Iterable[FunctionToolParam | FileSearchToolParam | ComputerToolParam | ComputerUsePreviewToolParam | WebSearchToolParam | <11 more items>] | Omit = ..., top_logprobs: int | Omit | None = ..., top_p: float | Omit | None = ..., truncation: Literal['auto', 'disabled'] | Omit | None = ..., user: str | Omit = ..., extra_headers: Mapping[str, str | Omit] | None = ..., extra_query: Mapping[str, object] | None = ..., extra_body: object | None = ..., timeout: float | Timeout | NotGiven | None = ...) -> Response
src/agent_task_foundry/runner.py:200: note:     def create(self, *, stream: Literal[True], background: bool | Omit | None = ..., context_management: Iterable[ContextManagement] | Omit | None = ..., conversation: str | ResponseConversationParamParam | Omit | None = ..., include: list[Literal['file_search_call.results', 'web_search_call.results', 'web_search_call.action.sources', 'message.input_image.image_url', 'computer_call_output.output.image_url', 'code_interpreter_call.outputs', 'reasoning.encrypted_content', 'message.output_text.logprobs']] | Omit | None = ..., input: str | list[EasyInputMessageParam | Message | ResponseOutputMessageParam | ResponseFileSearchToolCallParam | ResponseComputerToolCallParam | <27 more items>] | Omit = ..., instructions: str | Omit | None = ..., max_output_tokens: int | Omit | None = ..., max_tool_calls: int | Omit | None = ..., metadata: dict[str, str] | Omit | None = ..., model: Literal['o1-pro', 'o1-pro-2025-03-19', 'o3-pro', 'o3-pro-2025-06-10', 'o3-deep-research', 'o3-deep-research-2025-06-26', 'o4-mini-deep-research', 'o4-mini-deep-research-2025-06-26', 'computer-use-preview', 'computer-use-preview-2025-03-11', 'gpt-5.5-pro', 'gpt-5.5-pro-2026-04-23', 'gpt-5-codex', 'gpt-5-pro', 'gpt-5-pro-2025-10-06', 'gpt-5.1-codex-max', 'gpt-daybreak-blue-latest', 'gpt-daybreak-red-latest', 'gpt-5.6-cyber'] | str | Literal['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.5-2026-04-23', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.4-mini-2026-03-17', 'gpt-5.4-nano-2026-03-17', 'gpt-5.3-chat-latest', 'gpt-5.2', 'gpt-5.2-2025-12-11', 'gpt-5.2-chat-latest', 'gpt-5.2-pro', 'gpt-5.2-pro-2025-12-11', 'gpt-5.1', 'gpt-5.1-2025-11-13', 'gpt-5.1-codex', 'gpt-5.1-mini', 'gpt-5.1-chat-latest', 'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-5-2025-08-07', 'gpt-5-mini-2025-08-07', 'gpt-5-nano-2025-08-07', 'gpt-5-chat-latest', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4.1-2025-04-14', 'gpt-4.1-mini-2025-04-14', 'gpt-4.1-nano-2025-04-14', 'o4-mini', 'o4-mini-2025-04-16', 'o3', 'o3-2025-04-16', 'o3-mini', 'o3-mini-2025-01-31', 'o1', 'o1-2024-12-17', 'o1-preview', 'o1-preview-2024-09-12', 'o1-mini', 'o1-mini-2024-09-12', 'gpt-4o', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06', 'gpt-4o-2024-05-13', 'gpt-4o-audio-preview', 'gpt-4o-audio-preview-2024-10-01', 'gpt-4o-audio-preview-2024-12-17', 'gpt-4o-audio-preview-2025-06-03', 'gpt-4o-mini-audio-preview', 'gpt-4o-mini-audio-preview-2024-12-17', 'gpt-4o-search-preview', 'gpt-4o-mini-search-preview', 'gpt-4o-search-preview-2025-03-11', 'gpt-4o-mini-search-preview-2025-03-11', 'chatgpt-4o-latest', 'codex-mini-latest', 'gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'gpt-4-turbo', 'gpt-4-turbo-2024-04-09', 'gpt-4-0125-preview', 'gpt-4-turbo-preview', 'gpt-4-1106-preview', 'gpt-4-vision-preview', 'gpt-4', 'gpt-4-0314', 'gpt-4-0613', 'gpt-4-32k', 'gpt-4-32k-0314', 'gpt-4-32k-0613', 'gpt-3.5-turbo', 'gpt-3.5-turbo-16k', 'gpt-3.5-turbo-0301', 'gpt-3.5-turbo-0613', 'gpt-3.5-turbo-1106', 'gpt-3.5-turbo-0125', 'gpt-3.5-turbo-16k-0613'] | Omit = ..., moderation: Moderation | Omit | None = ..., parallel_tool_calls: bool | Omit | None = ..., previous_response_id: str | Omit | None = ..., prompt: ResponsePromptParam | Omit | None = ..., prompt_cache_key: str | Omit | None = ..., prompt_cache_options: PromptCacheOptions | Omit = ..., prompt_cache_retention: Literal['in_memory', '24h'] | Omit | None = ..., reasoning: Reasoning | Omit | None = ..., safety_identifier: str | Omit | None = ..., service_tier: Literal['auto', 'default', 'flex', 'scale', 'priority', 'fast', 'ultrafast'] | None | Omit | None = ..., store: bool | Omit | None = ..., stream_options: StreamOptions | Omit | None = ..., temperature: float | Omit | None = ..., text: ResponseTextConfigParam | Omit = ..., tool_choice: Literal['none', 'auto', 'required'] | ToolChoiceAllowedParam | ToolChoiceTypesParam | ToolChoiceFunctionParam | ToolChoiceMcpParam | ToolChoiceCustomParam | ToolChoiceSpecificProgrammaticToolCallingParam | ToolChoiceApplyPatchParam | ToolChoiceShellParam | Omit = ..., tools: Iterable[FunctionToolParam | FileSearchToolParam | ComputerToolParam | ComputerUsePreviewToolParam | WebSearchToolParam | <11 more items>] | Omit = ..., top_logprobs: int | Omit | None = ..., top_p: float | Omit | None = ..., truncation: Literal['auto', 'disabled'] | Omit | None = ..., user: str | Omit = ..., extra_headers: Mapping[str, str | Omit] | None = ..., extra_query: Mapping[str, object] | None = ..., extra_body: object | None = ..., timeout: float | Timeout | NotGiven | None = ...) -> Stream[ResponseAudioDeltaEvent | ResponseAudioDoneEvent | ResponseAudioTranscriptDeltaEvent | ResponseAudioTranscriptDoneEvent | ResponseCodeInterpreterCallCodeDeltaEvent | <53 more items>]
src/agent_task_foundry/runner.py:200: note:     def create(self, *, stream: bool, background: bool | Omit | None = ..., context_management: Iterable[ContextManagement] | Omit | None = ..., conversation: str | ResponseConversationParamParam | Omit | None = ..., include: list[Literal['file_search_call.results', 'web_search_call.results', 'web_search_call.action.sources', 'message.input_image.image_url', 'computer_call_output.output.image_url', 'code_interpreter_call.outputs', 'reasoning.encrypted_content', 'message.output_text.logprobs']] | Omit | None = ..., input: str | list[EasyInputMessageParam | Message | ResponseOutputMessageParam | ResponseFileSearchToolCallParam | ResponseComputerToolCallParam | <27 more items>] | Omit = ..., instructions: str | Omit | None = ..., max_output_tokens: int | Omit | None = ..., max_tool_calls: int | Omit | None = ..., metadata: dict[str, str] | Omit | None = ..., model: Literal['o1-pro', 'o1-pro-2025-03-19', 'o3-pro', 'o3-pro-2025-06-10', 'o3-deep-research', 'o3-deep-research-2025-06-26', 'o4-mini-deep-research', 'o4-mini-deep-research-2025-06-26', 'computer-use-preview', 'computer-use-preview-2025-03-11', 'gpt-5.5-pro', 'gpt-5.5-pro-2026-04-23', 'gpt-5-codex', 'gpt-5-pro', 'gpt-5-pro-2025-10-06', 'gpt-5.1-codex-max', 'gpt-daybreak-blue-latest', 'gpt-daybreak-red-latest', 'gpt-5.6-cyber'] | str | Literal['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.5-2026-04-23', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.4-mini-2026-03-17', 'gpt-5.4-nano-2026-03-17', 'gpt-5.3-chat-latest', 'gpt-5.2', 'gpt-5.2-2025-12-11', 'gpt-5.2-chat-latest', 'gpt-5.2-pro', 'gpt-5.2-pro-2025-12-11', 'gpt-5.1', 'gpt-5.1-2025-11-13', 'gpt-5.1-codex', 'gpt-5.1-mini', 'gpt-5.1-chat-latest', 'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-5-2025-08-07', 'gpt-5-mini-2025-08-07', 'gpt-5-nano-2025-08-07', 'gpt-5-chat-latest', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4.1-2025-04-14', 'gpt-4.1-mini-2025-04-14', 'gpt-4.1-nano-2025-04-14', 'o4-mini', 'o4-mini-2025-04-16', 'o3', 'o3-2025-04-16', 'o3-mini', 'o3-mini-2025-01-31', 'o1', 'o1-2024-12-17', 'o1-preview', 'o1-preview-2024-09-12', 'o1-mini', 'o1-mini-2024-09-12', 'gpt-4o', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06', 'gpt-4o-2024-05-13', 'gpt-4o-audio-preview', 'gpt-4o-audio-preview-2024-10-01', 'gpt-4o-audio-preview-2024-12-17', 'gpt-4o-audio-preview-2025-06-03', 'gpt-4o-mini-audio-preview', 'gpt-4o-mini-audio-preview-2024-12-17', 'gpt-4o-search-preview', 'gpt-4o-mini-search-preview', 'gpt-4o-search-preview-2025-03-11', 'gpt-4o-mini-search-preview-2025-03-11', 'chatgpt-4o-latest', 'codex-mini-latest', 'gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'gpt-4-turbo', 'gpt-4-turbo-2024-04-09', 'gpt-4-0125-preview', 'gpt-4-turbo-preview', 'gpt-4-1106-preview', 'gpt-4-vision-preview', 'gpt-4', 'gpt-4-0314', 'gpt-4-0613', 'gpt-4-32k', 'gpt-4-32k-0314', 'gpt-4-32k-0613', 'gpt-3.5-turbo', 'gpt-3.5-turbo-16k', 'gpt-3.5-turbo-0301', 'gpt-3.5-turbo-0613', 'gpt-3.5-turbo-1106', 'gpt-3.5-turbo-0125', 'gpt-3.5-turbo-16k-0613'] | Omit = ..., moderation: Moderation | Omit | None = ..., parallel_tool_calls: bool | Omit | None = ..., previous_response_id: str | Omit | None = ..., prompt: ResponsePromptParam | Omit | None = ..., prompt_cache_key: str | Omit | None = ..., prompt_cache_options: PromptCacheOptions | Omit = ..., prompt_cache_retention: Literal['in_memory', '24h'] | Omit | None = ..., reasoning: Reasoning | Omit | None = ..., safety_identifier: str | Omit | None = ..., service_tier: Literal['auto', 'default', 'flex', 'scale', 'priority', 'fast', 'ultrafast'] | None | Omit | None = ..., store: bool | Omit | None = ..., stream_options: StreamOptions | Omit | None = ..., temperature: float | Omit | None = ..., text: ResponseTextConfigParam | Omit = ..., tool_choice: Literal['none', 'auto', 'required'] | ToolChoiceAllowedParam | ToolChoiceTypesParam | ToolChoiceFunctionParam | ToolChoiceMcpParam | ToolChoiceCustomParam | ToolChoiceSpecificProgrammaticToolCallingParam | ToolChoiceApplyPatchParam | ToolChoiceShellParam | Omit = ..., tools: Iterable[FunctionToolParam | FileSearchToolParam | ComputerToolParam | ComputerUsePreviewToolParam | WebSearchToolParam | <11 more items>] | Omit = ..., top_logprobs: int | Omit | None = ..., top_p: float | Omit | None = ..., truncation: Literal['auto', 'disabled'] | Omit | None = ..., user: str | Omit = ..., extra_headers: Mapping[str, str | Omit] | None = ..., extra_query: Mapping[str, object] | None = ..., extra_body: object | None = ..., timeout: float | Timeout | NotGiven | None = ...) -> Response | Stream[ResponseAudioDeltaEvent | ResponseAudioDoneEvent | ResponseAudioTranscriptDeltaEvent | ResponseAudioTranscriptDoneEvent | ResponseCodeInterpreterCallCodeDeltaEvent | <53 more items>]
Found 22 errors in 3 files (checked 21 source files)
```

## pytest

```text
................................................................. [ 18%]
........................................................................ [ 38%]
........................................................................ [ 58%]
........................................................................ [ 78%]
........................................................................ [ 98%]
....                                                                     [100%]
```
