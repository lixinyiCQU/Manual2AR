# Manual2AR

当前工作树：`Manual2AR-Dev`，分支 `lixin/asset-library`。本轮已接入 U7 教学视觉资产，使用与扩展规范见 [视觉资产库](docs/VISUAL_ASSET_LIBRARY.md)。

前一阶段的主仓库和空间指导工作树已归档至 `Archive/`；当前位置、分支和恢复方式见 [工作区整理记录](docs/WORKSPACE_ORGANIZATION.md)。

一个 Unity 工程、一个业务后端、一个可独立部署的 GPU 推理服务，提供部件认知、操作指导和打印状态检查。

## 用户入口与功能边界

Unity 首先显示 **Manual2AR 资料库**：列出已导入的教学服务及其证据快照版本。选择 Bambu Lab A1 mini 后，进入该服务的教学首页，再选择部件认知、操作指导或打印状态检查。返回路径逐级进行：部件认知返回所选服务的教学首页；操作指导和打印检查的任务页先返回本模块任务列表，再返回教学首页；教学首页返回资料库。说明书 / Wiki 导入与语义分析暂未开发，入口明确标为“即将开放”。

服务入口由 `resources/services/catalog.json` 定义，快照版本读取对应来源清单。标题、简介、模块集合和服务地址均通过数据提供，不为每个服务复制 Unity 场景。新增同类操作任务仍通过模块任务目录登记；新的设备业务能力需要配置相应的后端与资料，不会仅因添加一个列表条目而自动实现。

三个模块的相机均支持 `1:1`、`16:9`、`9:16`、`3:4`、`4:3` 画幅，默认 `1:1`。画幅在旋转与镜像校正后，从画面中心裁切；预览与实际上传使用同一份像素结果，标注坐标也以裁切图为基准。切换画幅会清除旧标注，并关闭模块一、三的旧视觉会话，随后需要重新识别/检查。请确保所需部件或整块打印板仍完整入镜。

操作指导与打印检查入口共用同一套可滚动任务卡片，统一标题、字体、缩略图/图标、间距和未开放状态。

用户界面只提供摄像头学习、官方资料阅读、任务操作与检查纠正。部件认知保留启动/切换摄像头、识别、清除标注、整机介绍和唯一部件侧栏；云端分割跟踪不可用时自动使用本地 OpenCV。两种方案均依赖 VLM 做语义定位，VLM 故障不会被宣称为可离线识别。

输入源、图片测试、模型/引擎选择、刷新连接、保存学习画面、性能数据显示和原始诊断报表均不出现在用户界面。打印检查的“保存记录”、教程的完成标记和官方指南链接属于用户功能，继续保留。

## 启动

所有参数在 **`configs/app.local.json`** 中编辑，包括 VLM API Key、后端地址、模型和本地资料路径。新机器从 `configs/app.example.json` 复制，当前工作站的本地配置已迁移。GPU 连接文件单独保存在 `configs/inference.connection.local.json`。两个私有文件都被 Git 忽略。

```bash
bash run.sh setup     # 新机器：Python 3.12、依赖、离线阅读浏览器和本地包
bash run.sh start     # 同步公开资源，启动业务后端，默认 8010
```

浏览器访问 `http://127.0.0.1:8010/health`。Unity 2022.3.34f1 打开 **`apps/unity/Manual2AR`**，打开 `Assets/Manual2AR/Scenes/Welcome.unity` 后按 Play。

Windows 使用独立工程包时运行 `bash run.sh package`，解压生成的 `Manual2AR-Unity.zip` 后在 Unity Hub 添加文件夹。修改配置后运行 `bash run.sh sync` 更新源码工程，或重新 `package` 更新独立工程包。私钥与 GPU 令牌不会导出到 Unity。

## 目录

```text
apps/
  unity/Manual2AR/          Unity 客户端、四个场景、公共 UI
  backend/                 业务 API、三个教学模块、知识阅读、VLM/GPU 适配器
  inference/               GPU HTTP 服务、SAM3.1 初始化、Cutie 持续跟踪
packages/
  contracts/               图像身份、位置、掩码及 GPU 通信协议
  perception/              CPU 分割和跟踪算法
resources/
  catalog.json             资源逻辑名称与版本化文件路径
  devices/                 设备部件定义、原文知识卡选取规则
  tasks/                   任务、procedure、Prompt、参考图和证据
  modules/                 任务入口目录
  services/                已导入资料服务及教学首页配置
  sources/                 官方资料快照清单与校验值
  shared/                  共享字体及授权
  samples/                 静态测试样例
configs/                   公开配置模板、被忽略的本机私有配置
deploy/
  common/                  通用 GPU 环境准备、权重校验、启动与连接文件导出
  colab/                   唯一 GPU Notebook、运行时准备、Drive 缓存
  hpc/                     已分配 GPU 节点上的启动入口和 SSH 连接说明
  container/               GPU 容器构建入口
tools/
  build/                   Notebook、GPU 源码包的生成器
  resources/               资源及任务包校验
  evaluation/              通过产品 API 进行静态测试
tests/                     后端、视觉、推理部署、Unity 验证
docs/                      架构、迁移说明与来源记录
```

`apps/backend`、`apps/inference` 和两个公共包分别有自己的 `pyproject.toml`，采用 `src` 布局。后端本机依赖锁定在 `apps/backend/requirements.lock`；GPU 依赖在 `apps/inference/requirements-gpu.txt`，由 GPU 部署入口安装。

## 配置与项目外数据

| 配置                                                           | 用途                                                                                                           |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `backend.public_url`                                         | Windows Unity 可访问的业务后端地址                                                                             |
| `vlm.api_key`、`modules.*.model`                           | 本地填写凭据、分别选择模型                                                                                     |
| `vlm.proxy_mode`                                             | `auto`：绕过失效的本机代理；`system`：始终使用系统代理；`direct`：直连。只影响本项目，不修改系统网络设置 |
| `modules.*.settings`                                         | 模块高级设置覆盖；默认值由后端包管理                                                                           |
| `modules.learning.provider`、`modules.inspection.provider` | 开发测试默认值 / 打印检查供应商；部件认知的用户会话使用自动选择                                                |
| `gpu.connection_file`                                        | 同一 HTTP 协议的 GPU 服务连接文件                                                                              |
| `paths.resources`                                            | 教学资源根目录，默认 `resources`                                                                             |
| `paths.wiki_archive`                                         | 原始 Wiki 资料库 `runs/<快照>/archive.json`                                                                  |
| `paths.runtime`                                              | 会话日志、现场图像、检查证据、静态实验结果                                                                     |
| `paths.cache`                                                | 可删除后重建的 Wiki 阅读缓存                                                                                   |
| `paths.builds`                                               | Unity 工程包和 GPU 源码包                                                                                      |
| `paths.static_images`                                        | 模块一、三静态图片输入目录                                                                                     |
| `paths.renderer_python`                                      | 离线页面渲染使用的 Python 解释器                                                                               |

配置中的相对路径以仓库根目录为基准。使用 `load(显式配置文件路径)` 部署业务后端时，以配置文件上两级目录为基准，也可以使用绝对路径。

Projects 顶层仅保留 `Manual2AR-Li/`（代码与 Git 工作树）和 `Manual2AR-Data/`（项目数据）；旧别名及无关练习目录已移到 `/home/lixin/archives/`，恢复位置见 [迁移记录](docs/MIGRATION.md)。

当前工作站的数据归入相邻的 **`/home/lixin/projects/Manual2AR-Data/`**：

```text
sources/bambu-wiki/          不可变的官方快照、原始响应和资源对象
runs/integrated/             运行证据及实验输出
cache/integrated/            可重建缓存
builds/integrated/           可重新生成的交付包和验证产物
archives/                   重构前源码快照与迁移报告
```

携带离线资料时同时保留 `objects/` 和 `runs/`。快照身份及 SHA256 见 `resources/sources/bambu_wiki/manifest.json`。当前资料是固定版本的已收集页面，后端不在线抓取 Wiki。Wiki 缺失会禁用部件认知，其他模块继续可用。

## GPU 与静态测试

Colab：在 VS Code 的 WSL 窗口打开 **`Manual2AR.code-workspace`**，从任务菜单运行「Colab: 登录 Google」，再运行「Colab: 启动 GPU」。启动器自动部署、更新连接，并在就绪后持续监控；Ctrl+C 仅停止本地监控。已有运行时可单独运行「Colab: 持续监控」，异常时运行「Colab: 诊断连接与进程」。设置只修改 `configs/colab.local.json`，完整步骤见 [VS Code Colab 使用说明](docs/COLAB_VSCODE.md)。

原网页入口仍是 `deploy/colab/Manual2AR_GPU.ipynb`，模型固定 SAM3.1 + Cutie。

HPC：先执行 `bash run.sh inference-bundle`，使用生成包中的 [部署说明](deploy/hpc/README.md)。业务后端无需知道 GPU 运行在 Colab、SSH 节点还是容器上。

静态测试仅供后端调试，Unity 用户界面没有图片输入入口。使用与相机流程相同的产品 API，先启动业务后端：

```bash
.venv/bin/python -B -m tools.evaluation.static_test --module learning
.venv/bin/python -B -m tools.evaluation.static_test --module inspection
```

图片从配置指定的目录读取，结果和叠加图写到 `paths.runtime/static/`。

## 验证与维护

```bash
bash run.sh test              # 自动回归；不调用真实 VLM/GPU
bash run.sh resources         # 检查任务图片、Prompt、资源路径和快照 SHA
bash run.sh gpu-notebook      # 从规范源码重新生成唯一 Notebook
bash run.sh inference-bundle  # 导出独立推理源码包
```

既有 Python 回归覆盖空间几何、开箱阅读与扩展接口、Colab 部署及资料服务/自动回退；Unity 四场景实际 Play 验证运行时错误为 0，另通过 40 个画幅、旋转与镜像组合的图像检查。Unity 验证使用受控模型，未测试实物摄像头及真实 GPU 推理；HPC 和容器未做现场部署。

架构及扩展方式见 [ARCHITECTURE](docs/ARCHITECTURE.md)，分阶段迁移和回滚位置见 [MIGRATION](docs/MIGRATION.md)。整合基线分支 `lixin/integration-v1`，整合版 V1 标签为 `integration-v1.0.0`，原三个 V1 工作树已移入同级 `Archive/Module-V1/`，停止日常开发。

模块二下一阶段的动作与 AR 开发规格见 [模块二 V2 开发手册](docs/MODULE_TWO_V2_DEVELOPMENT.md)，包含官方开箱映射、空间契约、阶段交付及 Guided Reality 代码/资产复用审计。

U6/U7 Windows 摄像头空间指导已提供独立入口、相机标定、双视图作用点设置与自动循环示意；操作及代码边界见 [空间指导演示说明](docs/MODULE_TWO_SPATIAL_DEMO.md)。实机需要打印标记并完成界面内标定。

当前空间指导使用自动循环模型示意，支持两颗底座螺丝分别设置，操作标记与核验分离；右侧提供可放大的官方参考图及可选拍照反馈。当前使用说明见 [U7 实测说明](docs/U7_VISUAL_GUIDANCE.md)，历史审计见 [实测审计与阶段进展](docs/MODULE_TWO_SPATIAL_PROGRESS.md)。已有主位置数据保持兼容。

2026-11-03 已扩展开箱 U4/U5：四颗限制器螺丝、扎带、工具头左移、可选泡棉，以及热床三颗螺丝。U4—U7 共 10 个指导单元，支持章节/动作导航；见 [第二轮审查与开箱扩展](docs/UNBOXING_SPATIAL_EXTENSION.md)。热床锁紧使用人工确认。

模块二现提供整合版 Windows 开箱指导原型：13 章官方图文、U4—U7 空间动作、按分步骤进入、可选拍照找位置及统一学习记录。使用与接口见 [开箱原型说明](docs/MODULE_TWO_UNBOXING_PROTOTYPE.md)。

U7 已增加打印机工作坐标 O／XYZ 与声明式动作参数，支持分割高亮、二维代理和已定位的三维动画同屏。只需一次确认工作坐标，再按轴向、距离、周期和转角调整动作；详见 [打印机工作坐标与复测步骤](docs/PRINTER_WORK_COORDINATES.md)。该坐标仅供教学，不是设备固件机械零点，也不控制电机。

U7 的两个分步骤现按顺序开放：底座安装需通过独立 VLM 可见安装检查，之后才可进入安装料盘支架；图文页与空间页共享本次教程的核验结果，复检失败重新锁定。
