# Manual2AR：Agent 接手入口

日常开发使用 `Manual2AR-Dev/` 的 `Dev` 分支。先查看 `git status --short --branch`，再按验收说明启动系统，按仓库审计核对已知风险。[当前验收](docs/ACCEPTANCE.md) · [仓库审计](docs/REPOSITORY_AUDIT.md) · [文档导航](docs/README.md)

本机程序、运行记录和缓存集中在同级 `../Manual2AR-Data/`，公共 Git 库位于 `../.git-store/`。本机 `origin` 和 `personal` 对应不同仓库，接手其他克隆时须读取实际配置。[本机工作区](docs/WORKSPACE_LAYOUT.md) · [GitHub 交接](docs/GITHUB_HANDOFF.md)

U7 已接入来源目标候选、证据优先策略与条件剩余计划。2026-11-12 的封存包保留了当时的工作树和交接说明。[方法及缓存试验](baseline/ONLINE_PLANNING.md) · [历史 Agent 快照](docs/history/AGENT_SNAPSHOT_20261112.md)

前端已同步接入来源候选选择和具体补拍提示，移除与官方两步混淆的界面三步编号；见 [前端复评](docs/history/U7_FRONTEND_UPDATE_20261116.md)。`POST /api/guidance/u7-demo/goal-preview` 为只读接口；选目标后仍需主动评估。Unity 校验 remaining_plan 与 execution 的任务/会话/版本/节点，不用展示计划授权完成。只在接受照片回复后更新已提交标记；真实模式已接受旧图需重拍，网络未接受图仍可重试。

## 项目目标与当前范围

系统将官方操作资料编译为具有层级与依赖的任务库，结合自然语言目标和不完整现场证据，确定目标范围、已知进度和剩余的最细步骤，再按契约接入 AR 资产。本机的两份蓝图在源码之外。项目研究蓝图位于 `../References/history/Manual2AR_研究蓝图_v0.1.md`，师兄的原版位于 `../References/history/research_blueprint_v0_2.md`。

U7 两步具有已审核 GT：`install_base` 安装底座 → `install_holder` 滑入支架。系统尚无通用自动建模、通用三维验收或可靠跨设备规划结论。

当前模块二展示五个入口：U7“提问及拍摄现场生成AR指导”、打印机开箱、首次打印、进料、退料。打印机开箱两版增加了照片 AR 指引，其余沿用原教材和配置。候选审核、自动编译、旧 Wiki→AR 对照代码与 API 仍保留，研究入口在菜单隐藏。

开箱 AR 由现有教程 run 驱动。按 variant_id、state_id 与 selected_substep_id 定位动作；图库、动作 Prompt、API、覆盖与入口见 [开箱 AR 指引](docs/UNBOXING_AR.md)。新资产库与已审核 U7 库独立校验。

## 先复现的流程

1. 按 Dev 验收说明准备数据和本机配置，启动后端与对应的 Unity 客户端。本机验收地址为 `127.0.0.1:8011`，其他环境以实际配置为准。[启动与验收](docs/ACCEPTANCE.md)
2. 读 [U7 Demo](baseline/U7_DEMO.md)：默认历史照片＋预设观察，不调用模型。用户已明确授权保留另一条实时拍摄＋真实模型路径。
3. 输入“安装料盘支架”，选择“底座已装，支架待滑入”，点击“评估现场并生成计划”；先看现场结果与官方细步骤，再集中勾选底座全部人工项，自动进入支架滑入动画，用已装支架照片核验、确认方向直至完成。失败核验保持当前步；重播是独立操作，不改变进度。
4. 新会话直接选择已装支架照片时，底座被挡仍未知，不能假装完成。动画是照片平面示意，可点选调整；不是实机空间配准。相机启动不得自动核验。

预设观察不是原 VLM 回复，也不是独立人工图像标签。所有 `u7-demo` 记录（包括实时模式）均排除研究评价。新会话不继承上一会话的完成状态。

## 源码地图

| 职责 | 入口 |
| --- | --- |
| 组合应用、配置、启动、资源同步 | `apps/backend/src/manual2ar/application/{server,config,manage}.py`、`run.sh` |
| 现用 U7 Demo 接口 | `apps/backend/src/manual2ar/modules/guidance/u7_demo.py` |
| 现用 U7 Demo UI、原任务菜单 | Unity `Scripts/Guidance/{U7DemoView,PrinterGuidanceController}.cs` |
| 独立核心：任务契约、三值状态、依赖、目标 | `baseline/src/manual2ar_baseline/{gt,state,goals}.py` |
| 照片观察、ROI、来源、编译、评价 | 同包 `{photos,vision,sources,compiler,evaluation}.py` |
| GT 视觉/人工/AR 宿主 | `guidance/baseline_spatial.py`、Unity `Guidance/Spatial/SpatialBaseline.cs` |
| 自动资料编译宿主 | `guidance/official_compiler.py`、Unity `OfficialCompileView.cs` |
| 固定试次人审 | `guidance/baseline_review.py`、Unity `BaselineReviewView.cs`、`resources/evaluation/v1/catalog.json` |
| 旧 Wiki→AR 管线与方法对照 | `guidance/{pipeline,pipeline_spatial,stateful_spatial,observations}.py`、[方法说明](docs/reference/WIKI_TO_AR.md) |
| 原教材、图文、任务变体 | `guidance/{registry,tutorial,lesson}.py`、`resources/modules/guidance.json` |
| 资产契约、绑定、显示 | `resources/visuals/v1`、后端 `visuals/`、Unity `VisualGuidance/` |
| 实体相机/标定/跟踪的原实现 | `guidance/spatial/`、Unity `Guidance/Spatial/`、`packages/perception/` |
| 部件认知、打印板检查、GPU | `modules/learning/`、`modules/inspection/`、`apps/inference/` |
| 打包与交接 | `tools/build/{validate_desktop,spatial_delivery,handoff}.py`、`tools/handoff_restore.py` |

后端 `guidance/` 前缀为 `apps/backend/src/manual2ar/modules/guidance/`；Unity `Scripts/` 前缀为 `apps/unity/Manual2AR/Assets/Manual2AR/Scripts/`。

## 不可放宽的边界

- 用户说“已安装”不是证据；官方参考图不是现场事实；识别、分割、动画都不能授权任务完成。
- 视觉三值为通过／不通过／未知。当前全部视觉和人工条件满足且依赖成立才完成；人工不能越过视觉失败或未知。底座螺丝联合检查；M3-8 仅为官方选材要求。
- `session_id/task_sha256/epoch/revision`、照片 SHA、action/frame/request token 必须匹配。迟到结果不得覆盖新任务，切换相机／目标要清旧上下文。
- 同会话已核实底座可在普通遮挡后保留；明确反证会失效。新会话遮挡不能靠预设跳过。
- U7 Demo `reply.demo_flow` 仅提供简短展示：阶段、目标、现场结果、下一步和细步骤状态；既有 `execution` 仍决定放行。每次真实照片检查全部必要视觉条件，避免漏掉前置被拆等反证。相机取景不能提交旧图，拍摄后冻结；切图/目标变化清旧叠加，迟到响应不改新窗口。
- U7默认 `evidence_guided`：部分正证据但仍缺细节时先核实；原strict/scene_guided保留。`remaining_plan` 是只读条件分支与来源/资产关联，分支仍要求当前运行时授权，不写完成事实。目标使用已有别名及有限规范化，歧义候选不授权执行。两个实验开关是use_aliases/normalize_language，不是校准概率。
- 保存失败不推进状态：U7 先准备副本、持久化、再提交；photo 的 busy 必须 finally 释放。照片事件需结合对应 `acceptance.json` 判定是否接受，不能只看中间记录。
- 旧三维路径保留相机标定、标记、工作坐标与用户实际确认。二维跟踪不是深度；Demo 照片平面动画不能冒称自动定位。
- 真实 VLM 质量有误认与不确定性。用户本轮优先软件架构鲁棒；没有重新授权时不为改善数字反复追加模型试验。
- 照片粗查与局部检查均携带任务已审核策略的来源原文，包括观察边界；提示词区分已辨认物体遮挡与身份不明，隐藏事实仍为未知。2026-11-16真实相机发现并修复策略上下文遗漏；[实拍记录](docs/history/U7_LIVE_TRIAL_20261116.md)。历史核实沿用时，demo_flow会明确说明来源，不声称本帧看见隐藏螺丝。

## 数据、恢复与研究证据

本机日常验收使用同级 `../Manual2AR-Data/runs/dev/`。以下以 `runs/` 开头的路径均相对于 `../Manual2AR-Data/`。设备 Wiki、运行记录、缓存、构建和凭据分别管理。

- 正式评价：`runs/baseline/transfer-20261111-v1/`，389项冻结文件；manifest SHA `e11f726dfc2a9c059ea6fe6efd19739a4dddab12fc861b9c090b90d7938390d3`。不要修改或用新方法重算覆盖。
- 首轮6任务×3次，共18排程，12实际编译，7契约通过；U7两份 AR-ready。7/12与7/18是不同分母，不能称视觉准确率或泛化成功率。同模型审核与人工审核不是同一指标。
- 人审状态读取当前 runtime 下的 `baseline-review/transfer-20261111-v1/current.json`。本机 Dev 使用 `runs/dev/`，11 月 11 日旧试验保存于 `runs/u7-pipeline/`。更新人工标签须有审核人意见。
- 真实图像、失败回复、诊断和现场核验在 `runs/u7-pipeline/`；GT 定义在 `baseline/ground_truth/u7/v1/state-validation/`。GT其他候选版本和协议也是来源记录，保留。
- Dev 演示从 `runs/dev/u7-demo/assets-v1/` 读取两张历史照片与清单，原试验素材保存在 `runs/u7-pipeline/u7-demo/assets-v1/`。
- 标定在 `guidance-spatial/profiles/`、`baseline-ar/**/profiles/`；更换硬件须重新校准，不能删除后假装从未配置。
- 文件恢复不恢复内存会话。自动编译 job 列表也不是全部可重启恢复；固定U7候选可从登记归档重新导入。
- 历史文件内的原机路径记录来源，原始哈希清单随证据保留。收到 11 月 12 日封存包时，按包内布局生成本机配置和独立启动副本。[封存包恢复](docs/HANDOFF.md)

## 验证与待办

11 月 12 日交接审计对应 `runs/u7-pipeline/handoff-20261112-v1/`，11 月 16 日更新记录对应当时的 U7 和共享相机。验收当前工作树时核对 Windows 程序和资产指纹。[封存包审计](docs/history/HANDOFF_AUDIT.md) · [11 月 16 日 U7 更新](docs/history/U7_DEMO_UPDATE_20261116.md)

```bash
bash run.sh setup
bash run.sh resources
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest tests baseline/tests -q -p no:cacheprovider
```

`bash run.sh test`只覆盖宿主 `tests/`，独立核心还需 `baseline/tests/`。受控测试不调用真实 VLM/GPU，不代表物理相机或 AR 精度验收。

Demo失联会话已有30分钟闲置回收（64上限、忙碌请求保留），照片/资料失败可重试且处理中能返回。后续优先独立标注现场样例、实体相机与AR联合验收，再推进可审核任务层级库、目标歧义澄清与规划评价。不要因U7修改已验证的其他教学模块。

本轮新增缓存实验入口 `tools.evaluation.online_planning`，最终记录在Data的 `runs/dev/online-planning-20261116/experiment-v8/`。48真实请求/31图像字节SHA，40已接受快照来自14历史会话（正式GT仅2），无独立视觉标签；27条开发目标和758软件控制状态不能冒充实拍样本或留出集。原389个冻结项校验匹配，人审当前1 approved/6 pending；新报告不写回旧报告或标签。该缓存实验完成时前端未变；随后本轮界面修改需新构建，不能继续用旧程序代替。

随后真实相机工程试验位于 Data `runs/dev/live-u7-20261116-193508/`：4次观察、3份不同图像字节、6次真实模型HTTP调用。原HTTP会话安装后因遮挡归因错误退回未知，失败记录保留。候选从底座已核实的历史检查点建立本地比较分支，补齐上下文后同图进入支架方向人工确认，再拍新图保持完成；不是将原服务器revision3覆盖成成功。`SUMMARY.json`和分支sidecar区分重复的会话/帧编号。正式评价仍排除此工程演示，不据此报视觉准确率。该次专项回归 126 项通过。

11 月 18 日开箱 AR 更新了前端与资产，受控接口遍历覆盖单机 28 个动作位置、AMS lite 38 个动作位置。真实模型另用两张历史照片试验，逐动作实机验收仍待完成。[开箱 AR 试验记录](docs/UNBOXING_AR.md)

Unity验证只用全新空目录或当前工作树已认领的验证目录；旧未标记临时工程需换新目录，工具不再自动覆盖。端口18010固定，验证排他执行。

## Git 与并行工作

当前只保留 main 和 Dev，日常开发目录为 Manual2AR-Dev。U7的全部提交已在Dev中，原lixin/u7-end-to-end分支和Manual2AR-U7-Pipeline工作树已移除。共享Git库在根目录.git-store，不要删除。读取实际HEAD与status，不使用旧交接包快照推断当前状态。

旧分支的完整bundle在Data/archives/workspace-cleanup-20261112；旧工作树压缩归档已精简，跟踪源码按archive-compaction.json中的commit从Git恢复，仅保留独有资料。新清理清单在Data/archives/slim-workspace-20261112。该次清理未推送远程。

原始实验、模型回复、人审、标定与Wiki保留。旧UI截图只保留各渠道最新一组，旧控制台日志和重复程序已删除，结果JSON保留。浏览器和Dev Python环境为现用依赖，保留；pip安装缓存、退休U7环境与旧归档模型缓存已删除。

后续并行开发使用各自分支/工作树、端口、runtime/cache和Unity验证工程，不覆写他人配置。Dev 供独立验收，发布、合并或创建 PR 以用户当次指令为准。
