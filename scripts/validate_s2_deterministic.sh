#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

uv sync --frozen --all-groups
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest -q
