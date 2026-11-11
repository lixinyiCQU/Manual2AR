# Manual2AR

面向 Bambu Lab A1 mini 的教学原型：Unity 前端、本地业务后端、可独立部署的 GPU 视觉服务。提供部件认知、操作指导、打印板异物／残料检查。

**AI Agent 从 [README_AGENT.md](README_AGENT.md) 开始。** 其中记录当前源码入口、Git 基线、未提交修改、验证边界及独立工作树开发方式，不依赖聊天记忆。

## 启动

环境：Python 3.12、Unity 2022.3.34f1；当前桌面端为 Windows，后端运行在 WSL。

```bash
bash run.sh setup       # 新机器安装依赖；已有环境不必重复执行
bash run.sh start       # 同步公开资源并启动业务后端
```

本机参数只编辑 `configs/app.local.json`，新机器从 `configs/app.example.json` 复制。GPU 连接只放在 `configs/inference.connection.local.json`；这些私有文件被 Git 忽略，不上传或打印其内容。

公开模板健康检查：`http://127.0.0.1:8010/health`；本 Pipeline 工作树本机配置为8011，实际以本地配置为准。Unity 打开 `apps/unity/Manual2AR` 的 `Welcome` 场景；Windows EXE 从当前交付包中的“启动教学系统.cmd”进入。

GPU 使用 SAM3.1 首帧分割与 Cutie 跟踪；不可用时可回退本机 OpenCV。语义识别仍依赖 VLM。原生 ARKit、真实深度及设备电机控制尚未接入。

## 目录

| 目录 | 职责 |
| --- | --- |
| `apps/unity/Manual2AR` | 四个场景、摄像头、交互及视觉显示 |
| `apps/backend` | API 组合、三个业务模块、离线 Wiki、外部服务适配 |
| `apps/inference` | 独立 GPU HTTP 服务及 SAM3.1／Cutie 引擎 |
| `packages/contracts` | 共享帧身份、GPU、空间及教学资产契约 |
| `packages/perception` | CPU 分割、跟踪及空间几何 |
| `resources` | 官方教材、任务、Prompt、参考图、字体及教学模型 |
| `configs` | 公开模板与被忽略的本机配置 |
| `deploy` | Colab、已分配 HPC 节点、容器及 Windows 启动入口 |
| `tools`、`tests` | 必要的构建、评估、校验与回归源码 |
| `docs` | 当前有效的使用说明、架构和契约 |

运行记录、构建、缓存及大型原始资料由配置指向仓库外的 `Manual2AR-Data/`。本树为 `Manual2AR-U7-Pipeline`（`lixin/u7-end-to-end`），基于 Dev 的 U7 能力开发 Wiki→AR 管线。`Manual2AR-Dev` 为另一工作树；同级 `Archive/` 中主仓库的 `.git` 仍被关联工作树使用，不能删除。

## 说明与验证

- [使用与交付](docs/OPERATIONS.md)
- [架构与模块边界](docs/ARCHITECTURE.md)
- [公共 UI 契约与组件](docs/UI_CONTRACT.md)
- [教学视觉资产](docs/VISUAL_ASSET_LIBRARY.md)
- [空间文字与图例契约](docs/GUIDANCE_DISPLAY_CONTRACT.md)
- [工作坐标及动作参数](docs/PRINTER_WORK_COORDINATES.md)
- [Colab 部署](docs/COLAB_VSCODE.md)

```bash
bash run.sh test         # 受控自动回归，不调用真实 VLM/GPU
bash run.sh resources    # 官方来源、资源、任务、Prompt 与资产校验
bash run.sh package      # 导出 Unity 工程包，不等于编译 Windows EXE
```

Windows EXE 必须先通过 `tools.build.validate_desktop --build`，再运行 `tools.build.spatial_delivery`。构建记录与源码／程序指纹不匹配时拒绝打包，具体命令见使用说明。

历史审计、测试记录、迁移过程、旧规划及诊断笔记本已归档到项目外 `Manual2AR-Data/archives/dev-core-source-20261105/`，不作为当前实现规范。来源清单和恢复方式见 Agent 快照；官方教材、必要部署工具和测试没有作为垃圾删除。
## U7 问题与照片到 AR 原型

本工作树新增模块二入口“提问并生成 AR 指导”：离线 Wiki 检索、任务编译、U7 能力绑定与独立 AR 核验。使用与边界见 [docs/WIKI_TO_AR.md](docs/WIKI_TO_AR.md)。

当前管线支持12项实验开关，包含现场驱动执行和严格视觉观察契约。实际能力、未定义验收标准及验证边界见 [Agent快照](README_AGENT.md) 和 [仓库审查](docs/REPOSITORY_AUDIT.md)。
