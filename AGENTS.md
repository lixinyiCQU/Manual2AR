# Agent entrypoint

Read `README_AGENT.md`, then inspect `git status`, the relevant source and tests before editing. The snapshot describes a point in time; current code and explicit user instructions take precedence.

Use an independent branch/worktree and private runtime/cache/build paths for concurrent development. Never share a Unity Library, overwrite another worktree's local configuration, or clean another Agent's changes. Do not delete the archived main repository's `.git`; all linked worktrees depend on it.

Preserve frame/session/hash checks, calibration, official evidence and the distinction between recognition, animation and verification. Keep credentials, captured images, generated builds and debug records outside tracked source. Do not claim real camera/GPU/AR validation from controlled tests.

Use the smallest complete change, reuse existing components, and run the checks appropriate to it. Update the Agent snapshot when changing entrypoints, contracts or validated behavior. Git commits, merges and pushes follow the user's requested scope; do not assume archived plans are new requirements.
