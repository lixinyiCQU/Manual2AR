# Agent entrypoint

Start in the Dev worktree. Inspect `git status --short --branch`, the relevant source and its tests. Read the [Agent handoff](README_AGENT.md), [current acceptance procedure](docs/ACCEPTANCE.md), and [repository audit](docs/REPOSITORY_AUDIT.md). The [document index](docs/README.md) lists the operating guides, technical references and historical records.

On the original machine, `../Manual2AR-Data/` holds datasets, builds and caches. The local bare Git store is `../.git-store/`. U7 development now lives on Dev. Current code and explicit user instructions take precedence over archived plans.

Use an independent branch/worktree and private runtime/cache/build paths for concurrent development. Never share a Unity Library, overwrite another worktree's local configuration, or clean another Agent's changes. Do not delete `../.git-store/`; the active Dev worktree depends on this shared Git store.

Preserve frame/session/hash checks, calibration, official evidence and the distinction between recognition, animation and verification. Keep credentials, captured images, generated builds and debug records outside tracked source. Do not claim real camera/GPU/AR validation from controlled tests.

Use the smallest complete change, reuse existing components, and run the checks appropriate to it. Update the Agent snapshot when changing entrypoints, contracts or validated behavior. Git commits, merges and pushes follow the user's requested scope; do not assume archived plans are new requirements.

The November 12 handoff package has an independent Git copy and a separate [restore procedure](docs/HANDOFF.md). Preserve frozen experiment manifests and human labels. Desktop validation may only overwrite an empty directory or a directory already claimed by this worktree; never adopt another Unity source project as a temporary build.
