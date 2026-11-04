# 当前工作区与归档

2026-11-05：U7 教学资产和场景显示里程碑后，日常开发仅使用 `Manual2AR-Dev/`。

相对于 `/home/lixin/projects/Manual2AR-Li/`：

| 目录 | 分支 | 用途 |
| --- | --- | --- |
| `Manual2AR-Dev/` | `lixin/asset-library` | 当前开发工作树，原 `Manual2AR-Asset-Library` |
| `Archive/Manual2AR/` | `main` | 原始基线及所有工作树共享的 Git 元数据 |
| `Archive/Manual2AR-Spatial-Guidance/` | `lixin/integration-v1` | 三模块整合和初期 Windows 空间指导快照 |
| `Archive/Module-V1/Manual2AR-Module-One/` | `lixin/module-one` | 模块一 V1 |
| `Archive/Module-V1/Manual2AR-Module-Two/` | `lixin/module-two` | 模块二 V1 |
| `Archive/Module-V1/Manual2AR-Module-Three/` | `lixin/module-three` | 模块三 V1 |
| `References/` | 无 | 论文、录屏和项目参考材料 |

移动保留完整目录、分支和忽略文件，不删除资料。归档工作树不再日常开发。主仓库的 `.git` 仍是所有工作树的共同依赖，不可当作普通归档缓存删除；通过 `git worktree list` 查看注册路径。

运行数据和已保存标定继续位于项目外 `Manual2AR-Data/runs/asset-library/`，构建位于 `Manual2AR-Data/builds/asset-library/`，缓存位于 `Manual2AR-Data/cache/asset-library/`。本次仅重命名源码工作树，不重命名这些数据路径，避免失去现有用户配置。私有配置、环境、生成资源、第三方本地试验资产不进入 Git。

后端及 Windows 启动文件按新工作树重新生成。新位置启动方式：`cd Manual2AR-Dev && bash run.sh start`；桌面通过最新交付包中的“启动教学系统.cmd”进入。

恢复历史工作树需先解除 worktree 锁，再通过 `git worktree move` 移回。归档环境的绝对路径可能过期，恢复后按配置重新建立环境；不覆盖当前开发环境。
