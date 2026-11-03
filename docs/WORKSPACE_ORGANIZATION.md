# 工作区归档与空间指导阶段快照

整理日期：2026-11-03。本次整理不增加业务功能，不开发三维资产库。

## 工作树

相对于 `/home/lixin/projects/Manual2AR-Li/`：

| 目录 | 分支 | 用途 |
| --- | --- | --- |
| `Manual2AR/` | `main` | 原始基线，保持不变；同时保存所有工作树共用的 Git 元数据 |
| `Manual2AR-Spatial-Guidance/` | `lixin/integration-v1` | 原 Integrated；三模块整合与 Windows 开箱空间指导阶段快照 |
| `Manual2AR-Asset-Library/` | `lixin/asset-library` | 从本阶段提交建立的后续工作树，准备接入三维指导资产；尚未开发 |
| `Archive/Module-V1/Manual2AR-Module-One/` | `lixin/module-one` | 模块一 V1 归档 |
| `Archive/Module-V1/Manual2AR-Module-Two/` | `lixin/module-two` | 模块二 V1 归档 |
| `Archive/Module-V1/Manual2AR-Module-Three/` | `lixin/module-three` | 模块三 V1 归档 |

工作树使用 `git worktree move` 迁移，保留分支、完整文件及忽略文件。归档模块设置 Git worktree 锁，防止被意外清理；并非独立仓库，不能单独删除主仓库的 `.git`。
原 `Manual2AR-Integrated` 名称仅在历史文档和证据来源记录中保留。当前目录名概括已完成的阶段，原整合分支名称不变，方便追溯。

## 本次提交包含的既有成果

- U4／U7 工具、箭头及高亮示意，工作端、相机投影和动画独立于教程状态。
- 有效位置下自动循环动画，标记丢失时隐藏并在恢复后继续；保留双视角人工设点。
- 分步骤／作用点下拉菜单、右侧拍照反馈、官方参考图点击放大，以及空间锚点配置入口。
- VLM 同帧局部图与作用点消歧、位置冲突检查、结构化错误和阶段耗时记录。
- 对应回归测试和使用说明。此次提交保存这些此前未提交的工作，不代表新增自动三维重建、原生 ARKit 或完整资产库。

## 资料与调试产物

- 论文与系统蓝图位于同级 `References/`；旧根目录 Python 环境完整移入 `Archive/Legacy-Environments/`。
- 原始 Wiki、第三方参考仓库仍位于项目外 `Manual2AR-Data/sources/`。
- 调试视频审计、U7 审计和历次验证输出归入 `Manual2AR-Data/archives/workspace-organization-20261103/`。`manifest.json` 保存逐项迁移映射、整理前状态及标定校验值。
- 已保存的用户记录、运行证据、相机标定和作用点仍在 `Manual2AR-Data/runs/integrated/`，不清除，不作为源码提交。
- 最新 Windows／Unity 交付包仍在 `Manual2AR-Data/builds/integrated/`。构建流程仍使用的 `validation-camera-fix/hardware-proof.json` 保留原位；其他历次验证输出已归档。
- `configs/*.local.json`、虚拟环境、生成资源及本地参考 FBX 继续由 Git 忽略。后续工作树复制当前私有配置，但使用独立的 runtime／cache／builds 目录，避免污染本阶段证据。

## 恢复与后续工作

归档目录保留原样，不改写模块 V1 的代码或提交。需要恢复某一模块时，先执行 `git worktree unlock <目录>`，再用 `git worktree move` 移回；其中的历史虚拟环境可能需要按恢复位置重新安装。

之后使用 `Manual2AR-Asset-Library` 开发。两个可运行工作树默认均连接本机 8010 端口，应先停止旧后端再启动另一个；配置和运行数据相互独立，官方 Wiki 与已核验参考资产可共享。

## 整理验收

- 改名后完整 Python 回归：304 项通过（一个上游 Starlette 弃用提示）。
- 资源检查：13 项逻辑资源、6 个任务变体及官方 Wiki 快照校验通过。
- 最新既有 Unity 四场景验证：运行时错误为 0；验证目录 `validation-spatial-20261103-194724` 已归入本次外部 validation 档案。本次目录整理未重新编译 UI。
- 后端在新路径重新启动并通过健康与空间配置检查；三份已保存相机／作用点配置 SHA256 不变。
- 未调用真实 VLM／GPU，未新增模型生成或资产库业务功能，未推送远端。
