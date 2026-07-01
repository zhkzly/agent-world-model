# Optional Research Agent Clones

This directory is reserved for optional local clones or submodules used while developing research-agent adapters.

Examples:

- `open_deep_research/`
- `ManuSearch/`
- `searxng/`

Hosted providers such as Jina Reader/Search are configured through env vars and do not need a local clone here.

Do not import these projects directly from pipeline core. Add adapters under `agent_world/research/adapters/`.
