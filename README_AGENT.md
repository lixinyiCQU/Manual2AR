# Manual2AR：AI Agent 接手快照

快照日期：2026-11-05。用途：让新的 Agent 不依赖聊天记忆即可定位源码、核对状态并开发。

**先读本文，再读实际代码、`git status`、相关测试及 Git 历史。** 本文是开发快照，不是实时服务状态；源码和用户最新要求优先。不要把历史规划、合成验证或旧测试记录当成已实现功能。

## 1. 项目在做什么

Bambu Lab A1 mini 教学原型，资料库入口下有三个模块：

| 模块 | 当前实际能力 | 主要边界 |
| --- | --- | --- |
| 一：部件认知 | 摄像头识别、多目标分割／跟踪、部件介绍、内嵌官方 Wiki | 二维识别不等于三维位姿；新设备不能只增加目录项就自动支持 |
| 二：操作指导 | 官方开箱图文章节、外挂料盘／AMS lite 教材、首次打印及外挂进退料；U4–U7 Windows 空间示意 | 重点在 U7 两个分步骤；原生 ARKit、真实深度和空间遮挡未接入 |
| 三：打印状态检查 | 打印板异物／残料检测、跟踪、移出板面判定、复检、默认打印头遮挡的专用人工确认 | 其他检查任务仅占位；照片通过不等于整机或成品质量通过 |

单用户 Windows 客户端＋WSL 业务后端是当前开发环境。GPU 可独立部署；没有在此快照中验证多人云端生产部署。

## 2. Git 基线与当前版本

- 当前工作树：`/home/lixin/projects/Manual2AR-Li/Manual2AR-Dev`。
- 当前分支：`lixin/asset-library`；目录改名没有改分支名。
- 整理前的里程碑：`7279152`，`feat(guidance): deliver U7 visual asset and resilient tracking milestone`。
- 本轮提交包含取消任务修复、Windows 构建指纹、文档归档及接手文档。用 `git rev-parse HEAD` 和 `git log` 查询实际版本；并行开发从包含本轮整理的提交创建工作树。
- 不假设本机差异都是自己的，不 reset、clean 或覆盖其他 Agent 的文件。

```bash
git status --short
git log --oneline --decorate -12
git show --stat 7279152
git diff --stat
git worktree list
```

历史入口：`3747511` 为整合 V1；`654c9f3` 为 Windows 空间原型快照；`3beb4ad` 为模块二图文 UI；`000e9ec` 为早期空间指导；`7279152` 为 U7 资产与跟踪里程碑。`main` 当前是 `f48cdd3`，不是当前三模块整合开发基线。可用 `integration-v1.0.0`、各 `module-*-v1.0.0` 和 `spatial-guidance-v1.0.0` 标签追溯。

归档主仓库位于 `../Archive/Manual2AR/`，其 `.git` 仍被所有工作树共用，不能删除或另建仓库覆盖它。旧空间工作树在 `../Archive/Manual2AR-Spatial-Guidance/`，三个模块 V1 在 `../Archive/Module-V1/`。

## 3. 从哪一处代码开始读

| 工作 | 入口 |
| --- | --- |
| 应用组合、配置、健康检查、公开资源导出 | `apps/backend/src/manual2ar/application/{server,config,manage,services}.py` |
| 模块一视觉与知识阅读 | `apps/backend/src/manual2ar/modules/learning/`，尤其 `server.py`、`frame_pipeline.py`、`knowledge.py` |
| 模块二任务与状态 | `apps/backend/src/manual2ar/modules/guidance/{registry,service,engine,tutorial,experience}.py` |
| U7 前置关系 | `apps/backend/src/manual2ar/modules/guidance/u7_sequence.py` |
| 空间会话、相机标定、双视角点、机器坐标 | `apps/backend/src/manual2ar/modules/guidance/spatial/{service,machine,router}.py` |
| U7 VLM、候选／旧跟踪切换、CPU 回退 | `.../guidance/spatial/{u7_vision,part_tracking}.py`，`.../integrations/perception/cpu_client.py` |
| 图例与操作指令组合 | `.../guidance/spatial/display.py`，`packages/contracts/src/manual2ar_contracts/guidance_display.py` |
| 模块三判定 | `apps/backend/src/manual2ar/modules/inspection/{service,rules,plate_scope}.py` |
| 模型／网络适配 | `apps/backend/src/manual2ar/integrations/`；业务模块不直接加载 CUDA 模型 |
| GPU 服务 | `apps/inference/src/manual2ar_inference/app.py` 及 `engines/` |
| CPU 算法与几何 | `packages/perception/src/manual2ar_perception/` |
| Unity 通用界面、导航、相机裁切 | `apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/` |
| 公共页面／相机工具栏／弹窗／中文正文 | `Scripts/Common/{AppWorkspace,AppActionBar,AppCameraBar,AppDialog,AppContent,AppReadableText}.cs`；规范见 `docs/UI_CONTRACT.md` |
| Unity 三个模块 | `Scripts/Learning/`、`Scripts/Guidance/`、`Scripts/Inspection/` |
| 空间交互状态、相机、分割结果、文字 | `Scripts/Guidance/Spatial/`，尤其 `SpatialGuidanceController`、`SpatialPartWorkflow`、`SpatialStepFlow` |
| 资产目录、统一动画采样、Windows／原生世界适配器 | `Scripts/VisualGuidance/`；后端 `manual2ar/visuals/library.py` |
| 任务／Prompt／官方图片 | `resources/catalog.json`、`resources/tasks/`、`resources/modules/` |
| U7 当前配置 | `resources/tasks/bambu_a1_mini/unboxing/spatial/v1/` |
| 开箱官方图文章节 | `resources/tasks/bambu_a1_mini/unboxing/v2/`；不要凭旧 U1–U10 手工摘要改回去 |
| 米制资产、配方与目录 | `resources/visuals/v1/`，生成器在 `tools/assets/` |
| Windows 编译、验证及可追溯交付 | `tools/build/{validate_desktop,desktop_provenance,spatial_delivery}.py` |

`packages/contracts` 不反向依赖业务模块；`packages/perception` 不依赖 GPU 服务。现有依赖方向有回归检查，不为新任务另复制一套服务、相机或采样器。

## 4. 必须保留的行为

### 视觉与空间

- 图像坐标基于旋转／镜像校正和裁切后的输入，二维框／点使用 0..1000。
- 帧号、源图 SHA256、session、job 和当前动作必须匹配；迟到结果不能覆盖新步骤或新帧。
- VLM 提供语义、框和前景点；SAM3.1 首帧分割、Cutie 后续跟踪。GPU 不可用时使用现有 OpenCV GrabCut／LK 链路。VLM 不可用不能伪装成离线识别。
- 掩码和图像代理只有二维位置／主轴，不含真实深度或完整六自由度位姿。米制锚点来自已标定相机、固定标记和显式双视角重建。
- 同屏高亮、代理和动画使用匹配画面及其位姿；不能为“更流畅”把旧掩码套在实时新图上。
- 标记与打印机必须保持相对固定；作用点和工作坐标是教学配置，不是固件零点，不发 G-code。

### U7 用户流程

- 底座步骤：相机预检查 → 用户确认缓存场景 → 官方说明 → 自动识别底座 → 有效分割就绪后播放动画。
- 核验底座可见安装通过后，用户确认才进入滑入支架步骤；不是看到动画就算通过。
- 支架步骤先展示图文，再提示底座与支架同时入镜；必须手动点“识别部件”，不自动拍照。
- 章节页和视觉工作区共用 `AppWorkspace`，按钮组使用 `AppActionBar`；不要复制布局坐标或恢复定时主题扫描。
- 章节页顶部显示总览／返回任务列表，底部左侧为 AR／拍照核验入口，右侧为等宽章节导航；空间配置栏默认收起，仅显式配置时展开。
- 安装核验未通过仅显示右栏反馈，红色底色缓慢闪烁三次后保持；通过使用紧凑弹窗，不能因 UI 精简跳过用户确认。
- “检查安装”不终止仍有效的跟踪。重新识别建立候选，新候选可用才替换旧跟踪；失败保留仍可用的旧跟踪。
- 实际跟踪失败、退出、切换动作／画幅或重设位置仍需终止旧链路，不保留伪实时掩码。
- 场景文字只保留固定左上角图例及目标旁的祈使式操作指令。图例无指导内容时隐藏，同一部件颜色一致；核验状态在侧栏／弹窗。
- 图文章节可手动完成；空间指导的完成勾选来自视觉核验。浏览、模拟回放、分割、动画、人工操作标记和验收是不同状态。

## 5. 运行、配置和数据

```bash
bash run.sh setup       # 仅新环境
bash run.sh start
bash run.sh resources
bash run.sh test
```

Python 3.12；Unity 2022.3.34f1；前端入口 `Welcome`。完整操作见 [OPERATIONS](docs/OPERATIONS.md)，边界见 [ARCHITECTURE](docs/ARCHITECTURE.md)。

只在本工作树的 `configs/app.local.json` 修改私有配置；GPU 连接另存 `configs/inference.connection.local.json`。不要在日志、文档、终端或补丁中输出令牌。

当前主工作树数据在仓库外：

- `Manual2AR-Data/sources/`：不可变官方 Wiki、原文对象和第三方参考来源。
- `Manual2AR-Data/runs/asset-library/`：实际运行、图像证据及 `guidance-spatial/profiles/` 标定／作用点；不要清空。
- `Manual2AR-Data/builds/asset-library/`：生成的 Unity 工程、EXE、Notebook 和验证结果。
- `Manual2AR-Data/cache/asset-library/`：可重建缓存。
- `Manual2AR-Data/assets/`：Blender／FBX 源文件及预览；运行时 JSON 网格仍在仓库内。

本机配置才是实际路径依据；公开模板仍可能使用 `integrated` 名称。不能按目录旧名字猜当前数据位置。缺少 Wiki 可能禁用模块一；不要因此删掉其余模块或跳过证据校验。

## 6. 当前修改与验证状态

本轮提交的修改包括：

1. 排队识别取消：保存 Future、取消尚未开始的任务，在 VLM／分割前检查；已发出的请求只丢弃迟到结果，不承诺撤回。
2. Windows 交付：`desktop-build.json` 绑定 Unity 输入、实际编译工程、运行文件和四场景结果；打包重新核对，旧 EXE 不再按当前源码补写虚假来源。Git 状态自动读取。
3. 本次归档／文档整理：移出旧过程文件，诊断 Notebook 改为按需生成到构建目录，测试不再改写源码 Notebook；业务教学逻辑不因文档整理改写。

验证记录必须区分版本：

- 上述 1、2 完成后：385 项后端／部署回归通过；Unity 四场景与 Windows 构建通过，0 个运行时错误。证据在 `runs/asset-library/stability-fixes-*` 和 `builds/asset-library/validation-spatial-20261105-031913/`。
- 本次归档后的检查与交付见下文“归档后验证”。不要把旧计数当作任意后续改动的验收。
- 自动验证使用受控模型和合成图，不代表真实摄像头、GPU 推理质量、空间精度或原生 AR 已验收。不要自动外发私有图像。

Windows 交付命令：

```bash
.venv/bin/python -B -m tools.build.validate_desktop --unity <Unity.exe> --project <仓库外独立临时工程> --build
.venv/bin/python -B -m tools.build.spatial_delivery
```

`bash run.sh package` 只导出 Unity 工程，不编译 EXE。缺少构建记录、Unity 输入变化或程序文件被改动时应重新编译，不手工改指纹绕过检查。诊断 Notebook 用 `bash run.sh diagnostics-notebook` 生成到 `paths.builds`；其生成器和部署源码保留。

## 7. 已确认但尚未修复的审查事项

按当前代码核对后再实施，不把这张清单当作修改许可之外的新需求：

- 跟踪每次响应后额外等待 150ms；空间帧和跟踪串行两次请求，尚未优化。
- `RefreshAsset` 每帧重做文字格式化／显示，尚未缓存。
- U7 目标集合仍固定为底座和支架，尚未推广成任意任务／组件配置。
- `VisualWorldRenderer` 同一 presentation 减少可见网格时可能遗留多余对象；原生 AR 接入前需修复并测试。
- 操作指令契约允许的长文本可能超出固定显示区域；未来 Agent 内容生成尚未接入。
- 业务后端默认监听 `0.0.0.0`，未加 GPU 服务同级的共享令牌验证；开放局域网／移动端前需明确访问边界。
- `vlmBrief`／`SetBriefAdvice` 和空 `LabelRects` 有旧显示遗留；勿误认为它们仍控制新契约。

没有扫描到 `shortcut:`／`ponytail:` 注释不代表无技术债。当前保持目录边界，不再为这些问题新建微服务或通用 Agent 平台。

## 8. 多 Agent／多分支协作

每个 Agent 使用自己的分支和工作树。不要让两个 Agent 同时修改本工作目录，也不要让两个 Unity 实例共享 `Library` 或临时工程。

从包含本轮整理的当前提交创建独立工作树：

```bash
git worktree add -b agent/<topic> ../Manual2AR-<topic> HEAD
```

将占位符替换为自己的任务名。先确认 HEAD 包含所需功能，再分支开发；不固定使用历史基线 `7279152`。

本机 `Manual2AR-Data/archives/dev-core-source-20261105/handoff/` 保留提交前冻结补丁及清单，仅用于从 `snapshot.json` 指定的历史基线恢复当时的工作快照。它不包含本次提交前最后更新的版本说明，不是当前提交的完整源码证明；已有本轮提交的工作树不要重复应用。

新工作树还需独立配置环境与运行目录；Git 和归档补丁不携带 `.venv`、私有配置、Wiki 档案或生成资源。可按 README 安装环境，在本机受控复制私有配置后修改：

| 设置 | 并行要求 |
| --- | --- |
| `backend.port/public_url` | 各自占用不同端口；公开 URL 指向自己的服务 |
| `paths.runtime/cache/builds` | 各自独立的仓库外目录，不能指向主工作树的 `asset-library` 输出 |
| `paths.wiki_archive` | 可共享只读官方资料；相对路径需按新位置重新核对 |
| `paths.renderer_python` | 指向本工作树环境，不复用带旧绝对路径的 venv |
| GPU 服务及连接 | 健康检查不等于独占；不要重启或释放其他 Agent 正在使用的远端运行时 |
| Unity 验证 | 临时工程与验证后端端口不能并发复用；当前验证器使用 18010，需排他运行 |

`apps/backend/src/manual2ar/application/`、`packages/contracts/`、公共 UI、`resources/catalog.json`、`tools/build/` 和 Notebook 生成物是容易冲突的共享区域，修改前在任务分工中明确归属。修改契约时同步实际调用方和测试；生成 Notebook 从规范源码重建，不手工编辑内嵌 Base64。

交接时报告基线、修改文件、通过／未通过的检查、真实模型是否调用，以及仍未验证的硬件条件。不要自动提交、合并或推送，除非本次用户任务要求。

## 9. 归档与恢复

本机历史资料：`/home/lixin/projects/Manual2AR-Data/archives/dev-core-source-20261105/`。

- `archive-manifest.json`：原路径、归档映射及 SHA256。
- `before/`：整理前的文档／诊断 Notebook 副本；`before-working-tree.patch` 保护此前未提交修改。
- `handoff/working-tree.patch`、`snapshot.json`：本次提交前冻结的可校验工作快照，版本说明见上一节。

历史文档描述过去的实现、测试或设想，不是当前规范。没有本机归档时可从旧 Git 提交读取原文件，例如 `git show 7279152:docs/U7_TEST_REVIEW.md`；本轮修复可从包含本轮整理的 Git 提交恢复，提交前状态另见冻结快照。恢复旧文档先导出到临时位置阅读，不覆盖当前实现。

## 10. 归档后验证

2026-11-05 本次整理后的实际检查：

- 后端／部署回归：386 项通过；有一个上游 Starlette 弃用提示。
- 资源校验：14 项资源、6 个任务变体及 Wiki SHA256 通过。
- 当前有效 Markdown 本地链接检查：0 个断链。
- 315 个 Unity 输入仍匹配上一轮已通过四场景验证的 Windows 构建记录；本次没有改动前端 C#／场景，不重复宣称做了新的实机测试。
- 诊断 Notebook 已实际导出到仓库外，源码目录未被重新写入生成副本。

本机日志：`runs/asset-library/core-cleanup-tests.log`、`core-cleanup-resources.log`、`core-cleanup-diagnostics-export.log`，均相对于配置的数据根目录。归档和冻结补丁的 SHA256／基线／源码清单记录于 `handoff/snapshot.json`。后续修改需重新核对，不沿用这组计数。

当前公共 UI 已接入资料首页、部件认知、图文教学、拍照核验、空间指导和打印检查。受控验证：四场景 0 个运行时错误；两种模板 × 三个尺寸的六张组件预览通过；U7 顺序、核验失败保留跟踪及模块三结果展示通过。证据：`builds/asset-library/validation-spatial-20261105-140551/`。构建绑定 327 个 Unity 输入和 252 个运行文件；12 项构建来源校验测试通过。没有调用真实 VLM／GPU，也没有进行摄像头硬件、Windows 全部 DPI 或移动端安全区域验收。
