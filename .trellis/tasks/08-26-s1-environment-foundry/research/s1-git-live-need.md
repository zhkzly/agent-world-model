Create a resettable synthetic software-repository maintenance environment using
real files and a real local Git repository beneath the assigned instance
directory.

Provide a meaningful reproducible default repository with source files, tests,
commit history, and observable clean or dirty state.

Support structured, chainable tools for discovering files and Git status,
reading and editing files, running the repository's declared checks, creating a
commit, and inspecting diffs and history.

Refuse path traversal, writes to protected repository metadata, and commits when
the declared checks fail, without prohibited filesystem or Git mutation.

Remain fully local and do not contact network remotes.
