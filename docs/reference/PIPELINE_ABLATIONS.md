> 2026-11-11：新增第12项 visual_observation_contract。见[视觉观察契约](VISUAL_OBSERVATION_CONTRACT.md)。下文十/十一项说明为历史版本；当前以API features及冻结experiment.json为准。

# U7 基线与可选优化

2026-11-11。工作树 `Manual2AR-U7-Pipeline`，分支 `lixin/u7-end-to-end`。阅读本页前先核对当前源码和本地配置；不以历史构建代表当前版本。

## 范围与不变项

新增架构变体见 [现场驱动执行](SCENE_DRIVEN_EXECUTION.md)：`stateful_planning` 第11项，API v1.4，默认全关仍保留本文描述的旧基线。下文十项表及23组矩阵描述上一轮版本；最新工具矩阵为25组（11个单项及11个逐项删除）。

保留 `Wiki → 问题/照片 → 检索 → 编译 → U7 能力绑定 → 用户确认 → AR → 核验`。全部开关关闭为用户刚测试的 `baseline-v1.2` 路径；服务 API 升级为 `wiki-to-ar-v1.3`，运行接口仍为 `compiled-spatial-v2`。基线的源码 SHA 清单已保存在外部 `runs/u7-pipeline/baseline-video-audit/baseline-source/source-sha256.json`，不是把当前未提交改动误称为 HEAD 已包含。

照片/帧身份、官方出处、现场核验与参考图隔离、几何授权、步骤顺序及不确定不能放行，是始终启用的正确性约束，不作为性能消融开关。所有自动方法复用相同 U7 网格、动画模板、CPU/GPU 适配及相机标定，不能由模型猜米制深度。

本次验证数据与尚未解决的生成质量问题见 [验证记录](../history/PIPELINE_ABLATION_VALIDATION.md)。

## 用户入口

模块二 → **提问并生成 AR 指导** → 顶部 **实验：基线**。

- 基线：全部关闭。
- 启用全部优化：打开下表十项，保留当前照片，生成新的候选。
- 每项可独立选中；可单项加入基线，或从完整方法逐项删除。
- “应用开关”不立即调用模型；“应用并同图重跑”用原问题和照片创建新任务，不修改旧记录，不自动批准 AR。
- 选项随候选冻结；“继续上次任务”恢复原开关、照片和任务，不重复生成。要更改方法必须生成新候选。
- 进入 AR、人工测试并返回后，可在实验设置中“评价本轮结果”。四项分别选择未评价/通过/失败；未评价不计成功率。

## 实际实现的十项开关

以下是采用论文思想的工程模块，**不是对应论文的完整复现或相同实验设置**。

| ID | 开启后实际执行 | 关闭时 | 参照及边界 |
| --- | --- | --- | --- |
| `hierarchical_evidence` | 先按文档分组排序，再选任务章节；限定完整 heading 路径，补父级警告及本章节图片 | 原 BM25 章节候选 | HiKEY 的层级组织；未引入训练索引/向量库 |
| `image_enrichment` | VLM 为候选官方图生成检索描述；按资料哈希、模型和图片哈希缓存，明确标记模型派生身份 | 不生成图像描述 | MIDR；派生描述不变成官方要求 |
| `visual_reranking` | 章节选择调用直接看现场原图和候选官方图，比较对象与流程 | 只看 Scene 文本和候选原文 | Chain-of-Procedure 视觉流程匹配；不宣称训练了原论文模型 |
| `scene_alignment` | 检索后将官方图文与现场对应为部件 ID、二维框、关系、当前阶段和未知项；作为编译上下文及建议 | 原始 Scene 摘要 | CoP / CheckManual；状态是待核验建议，不能跳步 |
| `staged_compilation` | 动作证据提取 → 状态/依赖图 → 观察与核验条件 | Direct 一次编译 | main 分阶段思想及 CoP 动作拆解，输出仍是同一任务契约 |
| `semantic_review` | 原文/图片对照审核数量规格、方向、依赖、完成条件、视觉边界；最多一次重编译及复核 | 仅原契约校验 | PROC2PDDL 的结构化语义/校验启发；不是 PDDL 规划器，未训练新模型 |
| `region_alignment` | AR 识别时给 VLM 框及 OpenCV 轮廓候选编号，再用现场图及部件参考选区域和材料内点 | 原始 VLM 框 | CheckManual；区域提供者明确为 `vlm_boxes+opencv_contours`，不是 GroundingDINO |
| `mask_refinement` | 用现场原图+当前非空工作掩膜检查语义；keep/reject/替换 ROI 后至多重新分割一次 | 原分割初始化 | VASA 思想；GPU 与 CPU 都可用，空掩膜不伪称已审核，替换后仍校验几何 |
| `temporal_verification` | 同步骤/目标、4秒内三张不同照片逐一核验；一致通过才通过，混合结果为不确定 | 一张当前照片 | IndustReal 时序证据启发；不复现其训练模型，不证明隐藏锁止/扭矩 |
| `contextual_display` | 从生成任务产生五字段祈使句；复用现有图例网格/颜色，左上图例与目标旁指令一起渲染 | 基线候选文字 | Guided Reality / JARVIS；不复制人工 U7 验收条件补漏，不生成不存在的资产 |

语义审核被拒绝时保留 `compile/`，一次修正保存在 `compile-revised/`；`effective-compile.json` 指定实际绑定的版本。二次审核仍拒绝则停止，不能退回人工答案展示“成功”。

能力绑定仍要求底座固定、支架滑入两个主要状态按顺序存在。如果编译器增加了无法直接接入的独立状态，候选保留并标为 unsupported；本轮不将它暗中合并为人工两步。

多帧开关需摄像头持续送入不同近期帧；缺少三帧时提示稍后重试，不退回单帧。重复的同一照片不算三份证据。模型响应迟到或步骤变化仍按原身份检查拒绝。

## 对照与成绩隔离

1. `text_only`：规划移除现场照片，官方资料图和 AR 现场识别/核验不移除；与现场图文匹配、部件状态对齐互斥。用于检查照片对规划的实际贡献。
2. **人工 U7 对照**：单独打开原人工任务，记录同一问题/照片身份及人工教材版本，`counts_as_automatic_planning=false`；不作为自动生成失败回退，不并入自动任务成功率。返回后需重新生成或恢复自动任务才能给自动任务评分。
3. **人工几何对照**：可输入同问题、同照片的已批准任务 ID；其 AR 会话须已关闭且已配置作用点。只复制该候选的作用点/XYZ/动画微调到新候选，不能覆盖已有配置，仍需开始前确认。记录来源/哈希且 `counts_as_automatic_geometry=false`。默认留空，各方法独立配置。照片匹配不能证明现场没动，操作者仍必须保证打印机与标记相对固定。

本阶段没有自动原文 Ground Truth 提取/打分。审核模型的自评不是人工真值。既有 U7 人工 JSON、AR 配方和图例可用于盲审对照，但不注入自动编译器作为答案。

## 数据记录与 API

每个 `runtime/u7-pipeline/jobs/{id}/` 保留：

- `input.json` / `scene.jpg`：原问题、照片、开关及几何对照选择。
- `experiment.json`：方法、同图同问题 `comparison_group`、实现 SHA、模型参数、资料哈希、证据版本及人工几何标记。
- 原 Scene、检索候选/原文证据包、编译、审核、绑定；开启项增加自己的 JSON、Prompt、图像角色清单。
- `calls.jsonl` / `calls/{id}/`：逻辑调用的阶段、Schema、图片 SHA、输入、响应、耗时和失败类型；不写认证凭据，不保存 Base64 到文本日志。
- `human-reviews/*.json`：人工四维评分与评审耗时，追加保存，统计使用最新一次；不改变安装状态。
- AR 日志继续绑定 job、procedure/binding/source 哈希、session、frame；编号图/工作掩膜在对应部件任务目录。

接口：

- `GET /api/guidance/pipeline/experiments`：支持项、默认值与预设。
- `POST /jobs` 新增 `experiment` 对象及可选 `geometry_reference`；未知开关拒绝。
- `POST /jobs/{id}/repeat`：请求体为开关对象，服务端用原图/原问题创建新任务；默认清除人工几何对照。
- `POST /jobs/{id}/review`：`task_planning/component_binding/guidance/verification` 为 `unrated/pass/fail`，另有 notes、review_seconds。
- `GET /experiments/results`：逐任务数据、各方法统计、人工对照单独列出。

以上短路径均在 `/api/guidance/pipeline` 下。`ready` 只表示生成及绑定就绪，不是任务规划或实物安装正确。

## 配对批量实验

```bash
# 默认仅生成计划，不调用模型。输出放仓库外。
.venv/bin/python -B -m tools.evaluation.pipeline_ablation \
  --job <已生成任务ID> --output <仓库外实验目录>

# baseline/full/text_only 三组；明确 --run 才开始真实模型调用。
.venv/bin/python -B -m tools.evaluation.pipeline_ablation \
  --job <ID> --output <实验目录> --run

# 再加入十个单项和十个逐项删除，共23组；会显著增加模型调用。
.venv/bin/python -B -m tools.evaluation.pipeline_ablation \
  --job <ID> --output <新实验目录> --matrix --run
```

脚本顺序生成、不打开 AR、不自动审批或赋予“通过”，可重跑同命令恢复轮询。保存 `batch.json`、`results.json/csv`。导出包含服务上的全部记录，分析时须按 batch 中的 ID / comparison_group / 资料版本过滤；不把不同任务、人工几何对照、旧版记录混在一起。

优先报告：人工任务规划成功率（通过数/明确评价数，同时报告未评价数）、自动契约/绑定就绪率、现场指导及核验人工成绩、必要要求遗漏/无依据条件/不可见条件越界数量、评审修改时间、耗时、失败阶段和逻辑调用数。中断后只有输入、没有调用结果的记录计入 incomplete_calls，不伪称供应商失败或消失。调用数不是供应商内部重试次数；当前未返回的 Token/费用记 null，不估算。不用一次 U7 或文字哈希一致率证明泛化/稳定性。

## 后续扩展边界

原生 Wiki 证据适配器继续复用；没有为了本次消融安装 Docling、MinerU 或 Qdrant。PDF 适配、跨设备资产生成、学习式检索/时序模型和独立人工标注集未在本轮实现。要评价通用性，需增加未用于开发的任务/设备，固定原文标注和现场条件，重复运行并人工盲审。
