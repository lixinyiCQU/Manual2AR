# Manual2AR：Agent 交接快照

快照：2026-11-11。先读本文件和 `AGENTS.md`，再读源码、Git 历史及相关测试。本文记录当前实现与边界；历史计划不是开发授权，测试通过不是实物验收通过。

## 当前工作树与目标

- 本次开发工作树：`Manual2AR-U7-Pipeline`，分支 `lixin/u7-end-to-end`。当前提交用 `git rev-parse HEAD` 获取；不要依赖对话里的旧提交号。
- 源基线 `2634a05`：原 Dev 的手工 U7、自动空间初始化及三模块系统。本树在此基础上增加 Wiki→任务→U7 AR 纵向管线。
- `Manual2AR-Dev` 是另一工作树，不是本树别名；已归档主仓库 `../Archive/Manual2AR/.git` 是关联工作树的 Git 公共目录，不能删除。
- 当前研究：同一契约如何从官方资料可靠生成、对齐现场、绑定现有能力并核验。自动绑定仅覆盖 U7 的 `holder.base`、`holder.slide`，各最多一次；不是任意设备通用 AR 系统。

```bash
git status --short
git branch --show-current
git log --oneline --decorate -8
git worktree list
```

## 必读文档与源码

按任务选择，避免把历史审计当实时契约：

| 任务 | 文档 | 主要源码 |
| --- | --- | --- |
| Wiki→AR 管线 | [WIKI_TO_AR](docs/WIKI_TO_AR.md) | `guidance/pipeline.py`、`knowledge/retrieval.py` |
| 官方任务编译、出处 | 同上 | `knowledge/compilation/{compiler,models,prompts,source,binding}.py` |
| 实验开关／成本／人工评价 | [PIPELINE_ABLATIONS](docs/PIPELINE_ABLATIONS.md) | `guidance/experiments.py`、`enhancements.py`、`tools/evaluation/pipeline_ablation.py` |
| 现场状态与执行 | [SCENE_DRIVEN_EXECUTION](docs/SCENE_DRIVEN_EXECUTION.md) | `guidance/{scene_planning,stateful_spatial,pipeline_spatial}.py` |
| 严格观察与规则 | [VISUAL_OBSERVATION_CONTRACT](docs/VISUAL_OBSERVATION_CONTRACT.md) | `guidance/observations.py` |
| 人工 U7／坐标与自动配置 | [AUTOMATIC_U7_SETUP](docs/AUTOMATIC_U7_SETUP.md)、[PRINTER_WORK_COORDINATES](docs/PRINTER_WORK_COORDINATES.md) | `guidance/spatial/{automatic,automatic_vision,machine,placement,service}.py` |
| 公共 UI／图例／资产 | [UI_CONTRACT](docs/UI_CONTRACT.md)、[GUIDANCE_DISPLAY_CONTRACT](docs/GUIDANCE_DISPLAY_CONTRACT.md)、[VISUAL_ASSET_LIBRARY](docs/VISUAL_ASSET_LIBRARY.md) | Unity `Common/`、`Guidance/Spatial/`、`VisualGuidance/`；后端 `visuals/` |
| 应用／启动／构建 | [OPERATIONS](docs/OPERATIONS.md)、[ARCHITECTURE](docs/ARCHITECTURE.md) | `application/`、`tools/build/`、`deploy/windows/` |
| 本轮审查及遗留边界 | [REPOSITORY_AUDIT](docs/REPOSITORY_AUDIT.md) | 对照其中的修复与验证记录 |

后端路径前缀：`apps/backend/src/manual2ar/`。Unity 脚本前缀：`apps/unity/Manual2AR/Assets/Manual2AR/Scripts/`。

其他模块：`modules/learning/` 提供部件识别和跟踪；`modules/inspection/` 提供打印板异物／残料检查。独立 GPU 在 `apps/inference/`；CPU 几何／跟踪在 `packages/perception/`；共享模型在 `packages/contracts/`。新任务复用这些接口，不复制三模块或直接在业务进程加载 CUDA 模型。

## 当前链路与契约

`离线 Wiki → 检索证据 → procedure.json → 能力绑定 → 可选现场对齐／观察规范 → 用户审核 → 隔离 AR 会话 → 当前证据核验 → 推进`

- API `wiki-to-ar-v1.4`；旧候选运行契约 `compiled-spatial-v2`，现场驱动执行为 `compiled-spatial-v3`。
- 当前12项优化以 `GET /api/guidance/pipeline/experiments` 为准。默认全关保留对照方法；启用“严格视觉观察契约”才使用 Findings＋程序规则。各候选开关冻结，改开关需重新生成；不能假定旧候选启用了新逻辑。
- 用户声明、官方完整任务、初始观察、当前核验、会话执行状态独立保存。生成／识别／分割／动画播放都不授权完成。
- 严格观察：规范与 expected 分文件；VLM只返回现场事实，程序判定。当前支持可见性、实例计数、二维相对位置、标识读取。三维朝向／接触／到位没有通用执行器，缺少规范就明确拒绝，不能改用模糊问答或悄悄转人工。
- 编译规范、特征与规则仍是待审核候选；模型语义审核通过不保证忠实。真实实验已发现“二维上方”被用来代替“三维朝向”，新门控拒绝了它。U7 尚无完整可靠的朝向验收模板。
- 视觉、人工和混合核验分别执行。混合必须先通过视觉；纯人工须逐项明确确认；sensor 无适配器时拒绝。空条件不能自动完成。
- 现场驱动计划：operate/check/observe/complete。可能已安装先检查，不重复要求安装；未知要求补拍；每次推进后重新评估当前画面。
- `candidate-manifest.json` 持久保存候选文件指纹，新候选及重新批准的旧候选会封存。重启后不重新信任变动文件。封存前的历史文件无法追溯证明未变；旧批准至少检查记录的 procedure SHA。该清单用于完整性校验，不是抵御可同时篡改清单的文件系统攻击者。

## 不可删除的边界

1. 核验使用当前现场证据；参考图只用于语义／特征辨认，不能证明用户已操作。
2. session/job/action/target/frame、照片 SHA、epoch 和请求 token 必须一致；迟到结果不能覆盖新步骤。未知不放行，人工确认不绕过视觉失败。
3. 分割跟踪是二维结果，不提供真实深度／完整位姿。米制动画仍需标定、固定标记、有效空间配置和用户授权。
4. ArUco 工作板给出板坐标；板与打印机的轴向仍须实际对齐确认。扫描不会自动知道打印机坐标。
5. 新识别先建立候选跟踪，可用后再替换；核验／识别失败保留仍有效旧跟踪。切换动作、画幅、真实跟踪失败或退出需要清理。
6. 不能用人工 U7 的验收答案补自动候选；显式人工几何对照必须记录，不能算自动定位成功。
7. SAM3.1／Cutie 不可用可回退 CPU OpenCV，VLM 不可用不能伪装成离线语义理解。模拟帧和受控provider不能充当真实硬件证明。

## 运行与数据位置

Python 3.12、Unity 2022.3.34f1，Windows 客户端＋WSL 后端。只编辑被忽略的 `configs/app.local.json`／`configs/inference.connection.local.json`，不要打印或提交凭据。

```bash
bash run.sh setup       # 仅新环境；安装锁定依赖
bash run.sh start       # 同步公开资源并启动本工作树后端
bash run.sh resources
bash run.sh test        # 禁用宿主pytest插件，受控回归，不调用真实模型
```

公开模板默认8010；本工作树的本机配置为8011。实际端口和路径以本地配置为准，不要打印完整配置。当前外部数据在 `/home/lixin/projects/Manual2AR-Data/`：

| 路径 | 内容 |
| --- | --- |
| `sources/` | 官方 Wiki 原文、对象和快照；共享只读 |
| `runs/u7-pipeline/u7-pipeline/jobs/<id>/` | 输入、生成阶段、编译、调用、批准及人工评价 |
| `runs/u7-pipeline/compiled-u7/u7-pipeline/<id>/spatial/` | 候选隔离几何、会话、当前核验／观察证据 |
| `runs/u7-pipeline/stateful-validation/` | 既有受控／真实模型烟雾测试证据，含失败；不是正式成功率 |
| `builds/u7-pipeline/` | 交付包、Unity独立验证目录及来源证明 |
| `cache/u7-pipeline/` | 可重建缓存，不能拿它当已完成证据 |

```bash
.venv/bin/python -B -m tools.build.validate_desktop --unity <Unity.exe> --project <独立仓库外临时工程> --build
.venv/bin/python -B -m tools.build.spatial_delivery
```

`run.sh package` 仅导出工程，不编译EXE。Windows启动器按工作树路径及后端源码修订核对已运行进程；源码更新后需重启旧后端。它不会自动杀其他工作树服务。构建指纹不匹配不能手改证明；更改源码后重新验证、构建和交付。

## 验证记录与下一步

当前审查的最终测试、构建与未测范围见 [REPOSITORY_AUDIT](docs/REPOSITORY_AUDIT.md)。不要将较早文档中的425／508／410等数字写成当前结果，也不要把集合有重叠的测试数相加。

优先后续工作：用官方图片建立可辨识、可审核的 U7 特征与接口标准；对独立标注现场样例评价误放行率、未知率、补拍恢复及审核成本。扩大谓词能力时必须同时提供参数契约、实际观察适配器、确定性判定器和反例测试，不能只增加一个枚举值。

当前没有原生ARKit、真实深度、可靠空间遮挡、打印机控制或通用设备迁移验证。业务API以单用户受控实验为部署边界，开放网络／多用户前须单独设计访问控制与状态隔离。

## 并行 Agent 与历史恢复

```bash
git worktree add -b agent/<topic> ../Manual2AR-<topic> HEAD
```

每个Agent使用独立分支、工作树、venv、端口、runtime/cache/builds与Unity临时工程。不要共享Unity Library、覆写他人配置、清理他人修改或重启他人服务。验证器目前固定18010，必须排他运行。

可共享只读官方快照，GPU服务须明确会话归属。新工作树Git不带凭据、离线资料、现场图或构建；从公开模板配置自己的路径。合并前读共享契约、应用组合和资源目录的改动。

历史：`main=f48cdd3` 为原型，不是整合基线；`3747511` 为三模块整合V1，`3beb4ad` 图文UI，`654c9f3` Windows空间原型，`000e9ec` 空间里程碑，`7279152` U7资产与跟踪，`5522609` 源码整理，`312fd84` 公共UI，`2634a05` 自动空间配置。用 `git show`／`git log` 读取历史，不重复套用旧补丁。

旧开发资料在外部 `archives/dev-core-source-20261105/`，清单记录原路径和SHA；原快照补丁只适用其指定基线。交接必须报告HEAD、未提交改动、验证证据、真实模型调用及硬件边界。
