# Manual2AR：Agent 接手入口

当前开发布局见 [WORKSPACE_LAYOUT](docs/WORKSPACE_LAYOUT.md)，本机目录与分支以此为准。

> 2026-11-12工作区整理：数据统一在同级 `../Manual2AR-Data/`，Git公共库位于工作区根 `.git-store/`。保留main、lixin/u7-end-to-end、Dev；Dev已合并U7。日常开发使用Manual2AR-Dev。旧交接包/原机路径描述仅为历史记录，不要据此移动数据或删除Git库。本次只有本地提交合并，无推送。

状态：2026-11-12，交接整理版。先读本文件、`AGENTS.md`、[交接说明](docs/HANDOFF.md)，再查当前源码和 Git；不要把历史计划视为新授权。完整旧快照保存在 [历史快照](docs/history/AGENT_SNAPSHOT_20261112.md)，本文件只保留当前事实。

## 项目目标与当前范围

研究问题：把官方操作资料编译为具有层级与依赖的任务库，再结合自然语言目标和不完整现场证据，确定目标范围、当前进度和剩余最细步骤，按契约接入 AR 资产。研究蓝图在交接包 `References/Manual2AR_研究蓝图_v0.1.md`；师兄原版在 `legacy-docs/research_blueprint_v0_2.md`。

当前仅 U7 两步具有已审核 GT 和可用演示资产：`install_base` 安装底座 → `install_holder` 滑入支架。系统尚无通用自动建模、通用三维验收或可靠跨设备规划结论。

当前模块二展示五个入口：U7“提问及拍摄现场生成AR指导”、打印机开箱、首次打印、进料、退料。后四个沿用原教材和配置，不可因 U7 演示再隐藏。候选审核、自动编译、旧 Wiki→AR 对照代码与 API 仍保留，研究入口在菜单隐藏。

## 先复现的流程

1. 按 `docs/HANDOFF.md` 验包、配置、重建环境和重定位启动器。默认后端 `127.0.0.1:8011`，公开模板仍为8010；实际以本机配置为准。
2. 读 [U7 Demo](baseline/U7_DEMO.md)：默认历史照片＋预设观察，不调用模型。用户已明确授权保留另一条实时拍摄＋真实模型路径。
3. 输入“安装料盘支架”，选择“底座已装，支架待滑入”，生成计划；看视觉结果后在同一窗口明确勾选底座全部人工项，进入支架滑入动画，再用已装支架照片核验、确认方向直至完成。
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
| 旧 Wiki→AR 管线与方法对照 | `guidance/{pipeline,pipeline_spatial,stateful_spatial,observations}.py`、`docs/WIKI_TO_AR.md` |
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
- 保存失败不推进状态：U7 先准备副本、持久化、再提交；photo 的 busy 必须 finally 释放。照片事件需结合对应 `acceptance.json` 判定是否接受，不能只看中间记录。
- 旧三维路径保留相机标定、标记、工作坐标与用户实际确认。二维跟踪不是深度；Demo 照片平面动画不能冒称自动定位。
- 真实 VLM 质量有误认与不确定性。用户本轮优先软件架构鲁棒；没有重新授权时不为改善数字反复追加模型试验。

## 数据、恢复与研究证据

包布局为 `workspace/Manual2AR-U7-Pipeline/` 与 `Manual2AR-Data/`。Wiki、运行记录、缓存、构建不进源码 Git；本机凭据不随包。

- 正式评价：`Manual2AR-Data/runs/baseline/transfer-20261111-v1/`，389项冻结文件；manifest SHA `e11f726dfc2a9c059ea6fe6efd19739a4dddab12fc861b9c090b90d7938390d3`。不要修改或用新方法重算覆盖。
- 首轮6任务×3次，共18排程，12实际编译，7契约通过；U7两份 AR-ready。7/12与7/18是不同分母，不能称视觉准确率或泛化成功率。同模型审核与人工审核不是同一指标。
- 人工审核现状读 `runs/u7-pipeline/baseline-review/transfer-20261111-v1/current.json`，不要照旧归档中的 pending 数量覆盖，也不能替用户补标签。
- 真实图像、失败回复、诊断和现场核验在 `runs/u7-pipeline/`；GT 定义在 `baseline/ground_truth/u7/v1/state-validation/`。GT其他候选版本和协议也是来源记录，保留。
- U7 Demo 素材在 `runs/u7-pipeline/u7-demo/assets-v1/`，两图的字节和脚本清单均保留。
- 标定在 `guidance-spatial/profiles/`、`baseline-ar/**/profiles/`；更换硬件须重新校准，不能删除后假装从未配置。
- 文件恢复不恢复内存会话。自动编译 job 列表也不是全部可重启恢复；固定U7候选可从登记归档重新导入。
- 历史文件内原机绝对路径属于出处，不批量替换、不修改哈希清单。移机只生成本机配置和独立 `Launch/` 启动副本。

## 验证与待办

本轮审计和实际验证见 [HANDOFF_AUDIT](docs/HANDOFF_AUDIT.md) 及外部 `runs/u7-pipeline/handoff-20261112-v1/`；旧Unity四场景证明在 `builds/u7-pipeline/validation-spatial-20261112-160037/`。本轮未改 C#；复用前端须核对构建指纹，不把它说成新编译。

```bash
bash run.sh setup
bash run.sh resources
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest tests baseline/tests -q -p no:cacheprovider
```

`bash run.sh test`只覆盖宿主 `tests/`，独立核心还需 `baseline/tests/`。受控测试不调用真实 VLM/GPU，不代表物理相机或 AR 精度验收。

待办优先级：失联 Demo 会话回收（64上限）、离线文章渲染失败的明确重试；再推进可审核任务层级库、目标歧义澄清、独立标注进度样例与规划评价。不要交接时重写已验证的三个教学模块。

Unity验证只用全新空目录或当前工作树已认领的验证目录；旧未标记临时工程需换新目录，工具不再自动覆盖。端口18010固定，验证排他执行。

## Git 与并行工作

原开发树基于 `8bbfd0d`，本次不提交、不重置原工作树。交接副本拥有独立 `.git/`、所有原分支/标签/其他refs，并在 `handoff/u7-20261112` 创建一次本地交接提交；完整提交号读包的 `manifests/handoff.json`。该提交只存在交接副本，不是推送或合并。

`history/` 保存原refs、原未提交状态、已跟踪补丁、未跟踪列表和含交接提交的 `all-history.bundle`。GitHub只推确认的源码分支；实验与缓存通过整个交接目录另传。新分支不要默认接到旧 `main` 原型。

多个Agent各用独立分支/工作树、venv、端口、runtime/cache/builds和Unity验证工程；共享官方资料只读。不要清理他人修改、杀其他服务或删除旧主仓库 `.git`。先报告真实HEAD和status，再执行新任务。
