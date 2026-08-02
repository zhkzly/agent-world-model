# Python Project Delivery

## Keep authored semantics separate from generated state

Author project semantics in `candidate/pyproject.toml`; generate resolver state
with uv. Do not hand-write `uv.lock`, infer dependencies from an installed
environment, or use `pip freeze`.

- Copy `python_requires` from `inputs/implementation-contract.json` exactly to
  `[project].requires-python`.
- Keep a virtual non-installed project: omit `[build-system]` and set
  `[tool.uv] package = false`.
- Declare a non-empty project name and version. The sole virtual root in
  `uv.lock` must use that exact name.
- Treat the license as project semantics. Preserve the frozen or existing
  choice. A non-unknown expression, an existing license-file declaration, or
  a non-unknown text declaration is valid. When the required `LICENSE` file is
  the declaration, bind it with `license = { file = "LICENSE" }`.
  `license-files = ["LICENSE"]` is only a file inventory and does not replace
  `[project].license`. Never silently choose or rewrite a license.

## Generate and check the lock

Run from the supplied workspace root with the normal host `uv`:

```text
uv lock --offline --project candidate
```

Then check the final metadata and lock together:

```text
uv lock --check --offline --project candidate
```

The Candidate's Python version is declared by `pyproject.toml` and `uv.lock`.
Do not add interpreter-manager files such as `candidate/.python-version`: they
are not portable Candidate source and the final tree preflight will reject them.

The lock contains exactly one `{ virtual = "." }` root named
`[project].name`; every other package is a lock-pinned registry dependency.
Do not leave `candidate/.venv`, caches, links, or undeclared generated files in
the final tree.

After any final change to project metadata, license, or dependencies,
regenerate and recheck the lock. Read the real uv failure, repair its producing
declaration, and rerun the same command.

## Execute public tests from the delivered project

Declared public tests are direct Python programs, not an implicit `pytest`
session. The framework creates the frozen virtual environment and runs each
test with its `.venv/bin/python`; it does not install a test runner on the
Candidate's behalf. Prefer self-contained `assert`-based test programs. If a
test genuinely requires a third-party package, declare it in `pyproject.toml`,
regenerate `uv.lock`, and prove the frozen offline project can import it.

Before the final completion response, run every path you will declare as a
public test through the mounted execution preflight from the supplied
workspace:

```text
SKILL_DIR="$CODEX_HOME/skills/engineer-environment-codegen"
python "$SKILL_DIR/scripts/check_public_tests.py" \
  --workspace . --test tests/test_runtime.py --test tests/test_materializer.py
```

It makes a disposable clean copy, runs `uv sync --offline --frozen
--no-install-project`, then starts every test directly with the resulting
Python. It leaves no virtual environment or cache in `candidate/`; it is the
local engineering check for dependency/import mechanics, not an Integration or
release verdict.
