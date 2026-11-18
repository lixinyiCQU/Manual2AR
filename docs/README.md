# Manual2AR 文档导航

## 运行和交接

| 你要做什么 | 从这里开始 |
| --- | --- |
| 在新电脑运行 Dev，验收演示 | [资料清单、启动与验收步骤](ACCEPTANCE.md) |
| 演示打印机开箱或单独演示 U7 | [两种开箱路线、AR 动作与验证范围](UNBOXING_AR.md) · [U7 问答与拍照演示](../baseline/U7_DEMO.md) |
| 使用摄像头、标记或空间标定 | [现场操作说明](OPERATIONS.md) |
| 接手源码，区分源码、实验数据和构建 | [当前工作区](WORKSPACE_LAYOUT.md) · [GitHub 交接](GITHUB_HANDOFF.md) · [Agent 接手说明](../README_AGENT.md) |
| 决定演示或交付前先修什么 | [当前仓库风险审计 · 2026-11-18](REPOSITORY_AUDIT.md) |
| 恢复 11 月 12 日的封存包 | [原包验真与恢复说明](HANDOFF.md) |

## 开发参考

| 主题 | 文档 |
| --- | --- |
| 当前系统和任务基线 | [模块、接口与数据边界](ARCHITECTURE.md) · [GT、状态核验、编译与评价入口](../baseline/README.md) |
| Unity 界面与资产 | [公共 UI 契约](reference/UI_CONTRACT.md) · [空间指导画面契约](reference/GUIDANCE_DISPLAY_CONTRACT.md) · [U7 视觉资产库](reference/VISUAL_ASSET_LIBRARY.md) |
| 原 U7 空间标定路径 | [工作坐标](reference/PRINTER_WORK_COORDINATES.md) · [双视角配置](reference/AUTOMATIC_U7_SETUP.md) |
| GPU 服务 | [Colab 部署与诊断](reference/COLAB_VSCODE.md) |
| 用于方法对照的 Wiki→AR 管线 | [资料到指导](reference/WIKI_TO_AR.md) · [现场驱动执行](reference/SCENE_DRIVEN_EXECUTION.md) · [视觉观察契约](reference/VISUAL_OBSERVATION_CONTRACT.md) · [消融试验开关](reference/PIPELINE_ABLATIONS.md) |

## 历史证据

这些记录保留试验当时的版本、范围和结论。复查某一轮时，请使用该轮记录指向的运行目录。

- **U7 方法验证**　[早期视频与日志复盘](history/BASELINE_VIDEO_AUDIT.md) · [可选优化与验证](history/PIPELINE_ABLATION_VALIDATION.md)
- **11 月 11–12 日**　[仓库审计](history/REPOSITORY_AUDIT_20261111.md) · [交接审计](history/HANDOFF_AUDIT.md) · [Agent 快照](history/AGENT_SNAPSHOT_20261112.md)
- **11 月 16 日**　[U7 演示交互](history/U7_DEMO_UPDATE_20261116.md) · [前端复评](history/U7_FRONTEND_UPDATE_20261116.md) · [真实相机试验](history/U7_LIVE_TRIAL_20261116.md)

后续新增文档时，日常入口和验收指南放在本目录，接口、资产和部署参考放入 `reference/`，已结束的试验或交接记录放入 `history/`。正式实验数据及人工标签保存在独立数据目录，定位方式见 [工作区布局](WORKSPACE_LAYOUT.md)。
