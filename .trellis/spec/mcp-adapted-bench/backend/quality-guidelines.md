# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

### Python Commands Use `uv`

Run Python tools through `uv` so dependency resolution and interpreter selection stay consistent with `pyproject.toml`.

Good:

```bash
uv run pytest tests/agent_world
uv run python -m agent_world.fixtures.support_desk_lite_cli --help
```

Bad:

```bash
pytest tests/agent_world
python -m agent_world.fixtures.support_desk_lite_cli --help
```

Use explicit cache locations for CI-like isolated runs when needed:

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
```

---

## Testing Requirements

<!-- What level of testing is expected -->

- Prefer targeted `uv run pytest <path>` checks for the changed feature or documentation claim.
- Run `uv run pytest tests/agent_world` before committing changes that affect project-wide behavior or documented release guarantees.

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
