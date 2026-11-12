# Manual2AR

当前开发布局见 [WORKSPACE_LAYOUT](docs/WORKSPACE_LAYOUT.md)，本机目录与分支以此为准。

> 2026-11-12工作区整理：数据统一在同级 `../Manual2AR-Data/`，Git公共库位于工作区根 `.git-store/`。保留main、lixin/u7-end-to-end、Dev；Dev已合并U7。日常开发使用Manual2AR-Dev。旧交接包/原机路径描述仅为历史记录，不要据此移动数据或删除Git库。本次只有本地提交合并，无推送。

设备官方资料到 AR 操作指导的研究原型。Unity Windows 客户端连接本地 Python 后端，提供部件认知、操作指导和打印板检查。

**项目处于交接状态。** 人先读 [交接说明](docs/HANDOFF.md)，Agent先读 [README_AGENT.md](README_AGENT.md) 和 [AGENTS.md](AGENTS.md)。审查结果、已修复问题及保留待办见 [本轮审计](docs/HANDOFF_AUDIT.md)。

## 当前可以演示什么

模块二保留打印机开箱、首次打印、进料、退料，并提供“提问及拍摄现场生成AR指导”。U7 默认使用历史照片和明确标注的预设观察，串联目标匹配、进度判断、集中人工确认、AR动画与再次核验；也可切换实时相机和真实视觉模型。见 [三分钟演示路线](baseline/U7_DEMO.md)。

U7 最细操作为“安装底座→滑入支架”。支持完整目标、只装底座、滑入支架及明确组合问法。通过官方步骤可以先查看资料，不必先拍照或生成计划。未知不当作未安装，人工不能替代缺失的视觉证据，播放动画不代表完成。

当前Demo读取已审核GT，不现场自动编译。自动资料编译、候选人工审核和旧Wiki→AR管线仍保留用于研究与对照，但其菜单入口隐藏。Demo预设不作为模型识别或研究结果；照片平面动画不代表实机空间标定。

## 环境与启动

Python 3.12、Unity 2022.3.34f1，Windows客户端＋WSL/Linux后端。整个交接目录移机时先运行包根目录的 `handoff.py configure`，再安装；不要直接复制旧本机配置。

```bash
bash run.sh setup
bash run.sh start
```

本机配置为被Git忽略的 `configs/app.local.json`，GPU凭据另放 `configs/inference.connection.local.json`。交接工具默认本地8011；公开模板默认8010。真实视觉和语义识别需要接收方自己的API凭据，默认稳定Demo不需要。

## 目录与开发入口

| 路径 | 职责 |
| --- | --- |
| `baseline/` | 独立任务、状态、目标、视觉、编译和评价核心；[基线说明](baseline/README.md) |
| `apps/backend/` | 三模块API与资源、模型、GPU适配 |
| `apps/unity/Manual2AR/` | 四场景、摄像头、教学UI及AR展示 |
| `apps/inference/` | 可选独立GPU服务 |
| `packages/` | 共享契约、CPU感知及几何 |
| `resources/` | 官方教材、任务、Prompt、样例、字体与运行资产，须保留 |
| `tools/`、`tests/` | 构建、交接、评价和受控回归 |
| `docs/`、`configs/`、`deploy/` | 当前文档、配置模板与部署入口 |

外部 `Manual2AR-Data/` 保存离线资料、实验、人工审核、标定、缓存、编辑资产和构建；不能仅发送源码Git后声称交接完整。根目录开发进度及冻结证据均随交接包保留，具体清单见交接说明。

## 验证与说明

```bash
bash run.sh resources
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest tests baseline/tests -q -p no:cacheprovider
```

其他说明：[使用与空间标定](docs/OPERATIONS.md)、[系统架构](docs/ARCHITECTURE.md)、[任务目标](baseline/GOAL_FLOW.md)、[视觉核验](baseline/VISION.md)、[自动编译](baseline/COMPILATION.md)、[评价方案](baseline/EVALUATION.md)。旧文档的菜单和阶段描述属于对应实验版本，当前交接入口优先。

Windows构建必须通过 `tools.build.validate_desktop --build`，再由 `tools.build.spatial_delivery`核对指纹导出。验证工程必须是仓库外的新空目录或工具已认领目录。`run.sh package`只导出Unity工程，不编译EXE。

真实模型曾出现部件误认和螺丝细节未知；未完成实体相机、真实装配和AR精度联合验收。业务API按单用户本地实验设计，尚不具备公网多用户部署条件。
