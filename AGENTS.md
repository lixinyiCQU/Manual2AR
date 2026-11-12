# Agent entrypoint

> 2026-11-12工作区整理：数据统一在同级 `../Manual2AR-Data/`，Git公共库位于工作区根 `.git-store/`。保留main、lixin/u7-end-to-end、Dev；Dev已合并U7。日常开发使用Manual2AR-Dev。旧交接包/原机路径描述仅为历史记录，不要据此移动数据或删除Git库。本次只有本地提交合并，无推送。

Read `README_AGENT.md`, then inspect `git status`, the relevant source and tests before editing. The snapshot describes a point in time; current code and explicit user instructions take precedence.

Use an independent branch/worktree and private runtime/cache/build paths for concurrent development. Never share a Unity Library, overwrite another worktree's local configuration, or clean another Agent's changes. Do not delete `../.git-store/`; both active worktrees depend on this shared Git store.

Preserve frame/session/hash checks, calibration, official evidence and the distinction between recognition, animation and verification. Keep credentials, captured images, generated builds and debug records outside tracked source. Do not claim real camera/GPU/AR validation from controlled tests.

Use the smallest complete change, reuse existing components, and run the checks appropriate to it. Update the Agent snapshot when changing entrypoints, contracts or validated behavior. Git commits, merges and pushes follow the user's requested scope; do not assume archived plans are new requirements.

Handoff copies have an independent `.git/`; see `docs/HANDOFF.md`. Preserve frozen experiment manifests and human labels. Desktop validation may only overwrite an empty directory or a directory already claimed by this worktree; never adopt another Unity source project as a temporary build.
