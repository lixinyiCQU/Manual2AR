# Manual2AR：AI Agent 接手快照

快照日期：2026-11-06。先读本文和 `AGENTS.md`，再核对源码、`git status`、相关测试和 Git 历史。本文不是实时服务状态；用户最新要求和实际源码优先。历史规划不等于已实现功能。

## 1. 当前版本与运行边界

面向 Bambu Lab A1 mini 的单用户教学原型：Windows Unity 客户端、WSL 业务后端、可独立部署的 GPU 服务。

| 模块 | 已实现 | 尚未实现／限制 |
| --- | --- | --- |
| 一：部件认知 | 摄像头／静态图片、多部件识别、分割跟踪、知识详情、内嵌离线 Wiki | 二维结果不提供真实深度或完整六自由度位姿 |
| 二：操作指导 | 官方开箱章节与分步骤、外挂料盘／AMS lite 教材、首次打印、外挂进退料；U4–U7 Windows 空间示意 | 资产与自动配置重点是 U7；不是所有任务都已提供空间指导 |
| 三：打印状态检查 | 板面异物／残料、分割跟踪、移出板面判定、复检、默认打印头遮挡的人工确认 | 其他检查任务占位；照片通过不等于整机或成品质量通过 |

当前没有原生 ARKit、真实深度、可靠空间遮挡、打印机电机控制或通用 Agent 自动生成指导。五类视觉配方契约可扩展，不能因此宣称五类资产均已交付。

- 活跃工作树：`/home/lixin/projects/Manual2AR-Li/Manual2AR-Dev`。
- 分支：`lixin/asset-library`；目录改名没有改分支名。
- 本次快照提交前基线：`312fd84`（公共 UI），此前 `5522609`（源码整理）、`7279152`（U7 资产和稳健跟踪）。
- 本次提交纳入此前未提交的 U7 自动初始化、滑入方向补全、Windows 后端启动器与对应测试；此次审查仅更新接手文档，没有另外修改业务算法。
- 当前提交号以 `git rev-parse HEAD` 为准，不把快照写成会自引用的固定提交号。
- `main` 为 `f48cdd3`，不是三模块整合基线。整合 V1 为 `3747511`，Windows 空间原型为 `654c9f3`，图文 UI 为 `3beb4ad`，空间里程碑为 `000e9ec`。

```bash
git status --short
git log --oneline --decorate -12
git show --stat HEAD
git worktree list
```

主仓库在 `../Archive/Manual2AR/`，其 `.git` 为所有工作树共用，不能删除。历史空间工作树在 `../Archive/Manual2AR-Spatial-Guidance/`；模块 V1 在 `../Archive/Module-V1/`，已锁定归档。可通过 `integration-v1.0.0`、`module-*-v1.0.0`、`spatial-guidance-v1.0.0` 标签追溯。

## 2. 代码地图与依赖方向

| 工作 | 源码入口 |
| --- | --- |
| 应用组合、配置、启动、公开配置导出 | `apps/backend/src/manual2ar/application/{server,config,manage,services}.py` |
| 模块一识别、批量跟踪、知识 | `apps/backend/src/manual2ar/modules/learning/{server,recognition,frame_pipeline,knowledge}.py` |
| 模块二任务与教学状态 | `apps/backend/src/manual2ar/modules/guidance/{registry,service,engine,tutorial,experience}.py` |
| U7 前置条件与验收 | `.../guidance/u7_sequence.py` |
| 空间会话、相机、手动双视角和机器坐标 | `.../guidance/spatial/{service,machine,router}.py` |
| U7 自动坐标／两次照片／备份重置 | `.../guidance/spatial/{automatic,automatic_vision,printing}.py` |
| 缺少导向边时的滑入示意 | `.../guidance/spatial/placement.py` |
| VLM 部件识别、候选替换及 CPU 回退 | `.../guidance/spatial/{u7_vision,part_tracking}.py`、`.../integrations/perception/cpu_client.py` |
| 图例和目标旁指令 | `.../guidance/spatial/display.py`、`packages/contracts/src/manual2ar_contracts/guidance_display.py` |
| 模块三判定与板面范围 | `apps/backend/src/manual2ar/modules/inspection/{service,rules,plate_scope}.py` |
| 外部模型／HTTP 适配 | `apps/backend/src/manual2ar/integrations/` |
| 独立 GPU 服务 | `apps/inference/src/manual2ar_inference/app.py`、`engines/` |
| CPU 算法和几何 | `packages/perception/src/manual2ar_perception/` |
| 帧身份、GPU、机器坐标、自动配方和资产契约 | `packages/contracts/src/manual2ar_contracts/` |
| 公共 UI／导航／相机裁切 | `apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/` |
| 公共页面、按钮组、相机栏、弹窗、中文正文 | `Scripts/Common/{AppWorkspace,AppActionBar,AppCameraBar,AppDialog,AppContent,AppReadableText}.cs` |
| 三模块前端 | `Scripts/Learning/`、`Scripts/Guidance/`、`Scripts/Inspection/` |
| 空间状态、自动设置、分割、分步骤 | `Scripts/Guidance/Spatial/`，尤其 `SpatialGuidanceController`、`SpatialAutomaticSetup`、`SpatialPartWorkflow`、`SpatialStepFlow` |
| 动画采样及 Windows／世界渲染适配 | `Scripts/VisualGuidance/`、后端 `manual2ar/visuals/library.py` |
| 教材、任务、Prompt、官方图片 | `resources/catalog.json`、`resources/tasks/`、`resources/modules/` |
| 当前开箱章节／空间配方 | `resources/tasks/bambu_a1_mini/unboxing/v2/`、`spatial/v1/` |
| 资产目录与生成源码 | `resources/visuals/v1/`、`tools/assets/` |
| Windows 验证、来源证明、交付 | `tools/build/{validate_desktop,desktop_provenance,spatial_delivery}.py` |
| Windows 启动 | `deploy/windows/{Start-Desktop,Start-Backend}.ps1` |

表中 `...` 指 `apps/backend/src/manual2ar/` 对应路径；`Scripts/` 指上述 Unity 脚本根目录。共享契约不反向依赖业务模块，CPU 包不依赖 GPU 服务；业务模块不直接加载 CUDA 模型。新任务复用现有注册、相机、视觉客户端和采样器，不复制整套模块。

## 3. 必须保留的数据和用户流程

### 视觉、空间与验收分开

- 输入是旋转／镜像校正及裁切后的图像；二维框／点为左上角原点的 0..1000。
- session、job、当前动作、帧号、源图 SHA256 必须匹配。迟到结果不能覆盖新步骤；旧掩码不能贴在不匹配的新照片上。
- VLM 提供语义、框、前景点；GPU 为 SAM3.1 首帧分割＋Cutie 跟踪，失联时回退 OpenCV GrabCut／LK。VLM 失联不能伪装为离线语义识别。
- 图像代理只有二维位置／主轴；米制锚点来自标定相机、固定标记和双视角重建。标记与打印机需相对固定。
- 识别、分割、动画就绪、用户执行和可见安装验收是不同状态。相机看不到螺丝扭矩，不向设备发 G-code。
- “检查安装”失败不停止仍有效跟踪；重新识别先建候选，可用后替换，失败保留旧跟踪。实际跟踪失败、切换动作／画幅、退出或重设位置仍终止旧链路。

### U7 自动初始化

详见 [自动配置说明](docs/AUTOMATIC_U7_SETUP.md)。

1. 初次相机内参仍需棋盘标定。打印 80 mm ArUco ID 23 工作坐标板，平放并由用户按打印机轴向对齐、确认；扫描不自动知道打印机朝向。
2. 每个视角先 VLM 定位灰色底座，再裁剪识别两颗螺丝和可见竖直轮廓角点。两次取景经几何校验，源帧预览后由用户确认保存；不用 VLM 猜三维深度。
3. 已有手动位置优先；显式“备份并重新配置”才重置作用点／机器坐标／动作微调，保留内参和教学进度。失败或配置变动后的迟到结果不写入配置。
4. 只有两颗有效且已授权螺丝时，`placement.py` 可实时生成底座中点的滑入方向示意，不写入旧缓存，不代表隐藏插槽、卡扣或实际行程。失效源点、机器坐标不一致或不合理几何均拒绝。
5. `placement_method/placement_note` 区分实测和示意；高亮不等于动画定位。缺位置显示补充定位入口。等价的 VLM 部件键值返回格式经规范化后仍严格校验身份、置信度和坐标。

### U7 教学与 UI

- 底座：相机预检 → 用户确认沿用缓存 → 官方说明 → 自动识别底座 → 有效分割后播放动画。
- 底座可见安装核验通过后仍由用户确认，才进入滑入支架分步骤。
- 支架：先看图文，提示底座和支架同时入镜；用户手动点“识别部件”，不自动拍照。
- 图文章节可手动完成，空间指导完成勾选来自视觉核验；浏览和模拟回放不算通过。
- 公共布局遵守 `docs/UI_CONTRACT.md`。章节页顶部总览／返回任务列表，底部左侧 AR／拍照核验，右侧等宽导航；空间配置栏默认收起，仅显式配置时展开。
- 核验失败在右栏红底缓慢闪烁三次后保持；通过用紧凑弹窗，不跳过确认。
- 场景文字只保留左上角固定图例和目标旁祈使句。无有效指导内容时隐藏图例，同一部件颜色一致，验收状态在侧栏／弹窗。

## 4. 运行、验证和交付

Python 3.12、Unity 2022.3.34f1。前端入口 `Welcome`，健康检查默认 `http://127.0.0.1:8010/health`。

```bash
bash run.sh setup       # 仅新环境；安装固定依赖及浏览器
bash run.sh start
bash run.sh resources
bash run.sh test        # 自动隔离宿主 ROS 等 pytest 插件
```

完整说明：[OPERATIONS](docs/OPERATIONS.md)、[ARCHITECTURE](docs/ARCHITECTURE.md)、[UI_CONTRACT](docs/UI_CONTRACT.md)。本机只编辑 `configs/app.local.json`；GPU 连接放 `configs/inference.connection.local.json`。不输出或提交私钥、令牌、捕获图片。

本机数据根在仓库外 `Manual2AR-Data/`，实际以本工作树配置为准：

| 目录 | 内容 |
| --- | --- |
| `sources/` | 不可变官方 Wiki、原文对象、第三方参考资料 |
| `runs/asset-library/` | 运行事件、现场图、`guidance-spatial/profiles/` 标定与作用点；不可清空 |
| `builds/asset-library/` | Unity 工程、Windows EXE、生成 Notebook、验证证据 |
| `cache/asset-library/` | 可重建缓存 |
| `assets/` | Blender／FBX 源和预览；运行 JSON 网格在仓库 `resources/visuals/` |

公开模板仍使用 `integrated` 输出名，不要据此猜实际路径。缺离线 Wiki 可禁用模块一，不因此删其余模块。Windows 启动器运行时枚举 WSL 并验证源码 `run.sh`，`backend.launch.json` 由交付工具生成；更新 Python 源码后已有后端不会热更新，需显式重启，随后重开前端以重建内存会话。

```bash
.venv/bin/python -B -m tools.build.validate_desktop --unity <Unity.exe> --project <仓库外独立临时工程> --build
.venv/bin/python -B -m tools.build.spatial_delivery
```

`bash run.sh package` 仅导出 Unity 工程，不编译 EXE。`desktop-build.json` 绑定 Unity 输入和运行文件；打包须重新校验，禁止手改指纹绕过。改契约后从源码重建 Colab Notebook，不手改内嵌 Base64。诊断 Notebook 用 `bash run.sh diagnostics-notebook` 按需导出。

## 5. 2026-11-06 ponytail 审查：待办及边界

审查假设为单用户桌面实验，重点追踪应用组合、模块一批量跟踪、模块三板面判定、模块二自动配置／保存／跟踪／显示、Windows 启动与构建来源，以及相关测试。不是逐行穷尽全仓库，也未做渗透测试。以下是已核对源码的待办，此次只记录，不额外改业务代码。

1. **优先：启动器的版本识别过粗。** `deploy/windows/Start-Backend.ps1:29` 仅检查 `automatic_configuration=true`。早期自动配置后端和本次滑入修复后端均为 true，更新源码后旧进程仍会被当成兼容版本复用。最小修复为前后端／启动描述符共享明确能力修订号；不自动杀掉其他工作树的服务。当前更新需手动重启后端。
2. **应修：目标移出画面被误判为缺少定位。** `SpatialPartWorkflow.cs:90,96` 将有标记但 `target_ready=false` 一律导向“补充动画定位”，而空间后端还会返回 `target_outside_view`（`spatial/service.py:263`）。已有作用点只是不在视野内时会诱导用户重新配置。应先按状态提示调整取景，仅缺几何才展示补充入口，并补受控测试。
3. **应优化：每次跟踪后固定等待 150 ms。** `SpatialPartWorkflow.cs:78` 在网络／推理耗时之外再次等待，零请求耗时的理论上限也只有约 6.7 次／秒，实际更低。先按目标周期扣除已耗时并用现有延迟指标复测；空间定位请求和跟踪有先后数据依赖，不能直接取消帧身份检查或盲目并发。
4. **原生 AR 接入前修：世界渲染器残留旧对象。** `VisualWorldRenderer.cs:15–27` 仅增建对象；同一 presentation ID 的实例从三项减为一项时，后两项没有隐藏。最小修复是禁用余下对象，测试同一 ID 的缩减情况。当前 Windows 图像投影用另一适配器，此项不是本次动画消失的原因。
5. **联网部署前修：业务 API 没有访问认证。** `configs/app.example.json` 默认监听 `0.0.0.0`，`application/server.py` 未提供访问令牌边界；可访问端口的第三方可创建模型任务并消耗额度。单机先限制监听／防火墙，开放 LAN／移动端前再加入认证；独立 GPU 服务已有 Bearer 验证，不能误认为业务 API 也受其保护。

另外，`RefreshAsset` 每帧刷新文字，U7 部件集合仍固定，`SetBriefAdvice/vlmBrief/LabelRects` 有遗留路径。它们不是本轮已修复功能，不为此新增微服务、Agent 平台或通用工厂。未测性能前不承诺删除数量或帧率收益。

## 6. 验证证据与真实性

- 2026-11-06 重新运行完整 Python 回归：425 项通过、1 项上游 Starlette 弃用提示（95.76 秒）；日志 `runs/asset-library/repository-audit-20261106-tests.log`。
- 同日资源校验：14 项资源、6 个任务变体，官方 Wiki 与记录 SHA256 一致；日志 `repository-audit-20261106-resources.log`。
- 当前 Windows 构建沿用并重新核对 2026-11-05 四场景受控验证：`builds/asset-library/validation-spatial-20261105-182048/`；0 个运行时错误，绑定 329 个 Unity 输入和 252 个运行文件。
- 该受控验证包含自动初始化／候选确认／取消、仅螺丝缓存的滑入示意、缺定位反馈、核验失败保留跟踪、U7 顺序、公共 UI 和模块三显示。
- 本次没有重新编译未变化的 Unity 源码，没有调用真实 VLM／GPU，也未测试真实相机精度、Windows 全部 DPI、LiDAR／ARKit 或多人部署。受控测试通过不等于实物贴合验收。
- 本机已有真实实验日志只作为诊断证据，不自动外发图像，也不把历史 GPU 成功当作当前远端在线证明。

## 7. 多 Agent 开发与归档恢复

独立分支、工作树、运行目录和 Unity 临时工程是必须的。不能清理其他 Agent 的修改，不能共享 Unity `Library`、覆盖主配置或重启他人 GPU。

```bash
git worktree add -b agent/<topic> ../Manual2AR-<topic> HEAD
```

新工作树需独立环境和私有配置；Git 不携带 `.venv`、离线 Wiki、私密连接、现场图和构建。先确认 HEAD 包含所需功能，再创建分支。

| 配置／资源 | 并行要求 |
| --- | --- |
| `backend.port/public_url` | 独立端口，URL 指向自己的服务 |
| `paths.runtime/cache/builds` | 独立仓库外路径，不能复用主树 `asset-library` 输出 |
| `paths.wiki_archive` | 可共享只读资料，重新核对路径 |
| `paths.renderer_python` | 当前工作树环境，不复用带旧绝对路径的 venv |
| GPU | 明确会话归属；健康检查不表示独占 |
| Unity 验证 | 独立临时工程；验证器默认使用 18010，需要排他运行 |

`application/`、共享契约、公共 UI、资源目录和构建工具容易冲突，修改前明确归属。提交／合并／推送必须按用户授权，不由旧规划推断。

旧审计、迁移过程与调试文档在 `/home/lixin/projects/Manual2AR-Data/archives/dev-core-source-20261105/`，源码只保留有效说明。`archive-manifest.json` 记录原路径和 SHA256；`before/`、`before-working-tree.patch` 为当时备份；`handoff/snapshot.json` 和 `working-tree.patch` 仅用于其指定历史基线，不代表本次快照，禁止重复应用到当前分支。可用 `git show <旧提交>:<路径>` 导出历史资料到临时目录阅读，不覆盖当前实现。

交接时报告 HEAD、修改范围、验证命令／证据、是否调用真实模型及未验证硬件。不要把已归档计划作为下一次开发的自动授权。
