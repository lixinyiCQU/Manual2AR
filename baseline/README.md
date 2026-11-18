# Manual2AR 新基线

本目录保存独立任务核心、冻结的 U7 定义和实验方法。启动当前系统、复现演示和核对已知风险请使用 Dev 文档。[项目文档](../docs/README.md) · [启动与验收](../docs/ACCEPTANCE.md) · [仓库审计](../docs/REPOSITORY_AUDIT.md)

模块二同时提供 U7 演示、打印机开箱、首次打印、进料和退料。U7 可选择历史照片预设或实时模型，演示记录独立于研究评价。自动编译、GT 对照及人工审核保留研究代码和 API。开箱两版的照片 AR 指引由原教程入口启动。[U7 演示](U7_DEMO.md) · [开箱 AR](../docs/UNBOXING_AR.md)

当前相机交互见 [U7 评估、操作核验与人工确认](UI_FLOW.md)：主动评估、阶段主按钮、视觉结果展示和人工条件批量确认。

当前现场流程增加[不同颗粒度目标与现场指导](GOAL_FLOW.md)：同一官方完整任务支持整体或叶操作目标；核实底座后可进入支架 AR 指导，完成验收仍单独执行。

以官方资料定义任务、现场证据决定进度、程序选择下一步、AR 表达指导。当前已实现 **GT 对照、状态／调度验证、照片观察、U7 AR 闭环和自动官方资料编译入口**。本目录是独立 Python 包，不导入旧应用或空间服务；应用宿主复用原有 U7 资产、标定和展示。自动任务的输入来自原官方归档，GT 仅作独立对照。

## 当前产物

- [当前 U7 定义](ground_truth/u7/v1/state-validation/REVIEW.md)：两个操作节点、八个条件、十九项来源要求；已完成本阶段方法审核。
- [状态与调度设计、审核结论和运行说明](STATE_VALIDATION.md)：方向采用明确人工确认；遮挡保留有条件的有效历史证据，新会话未知则补拍。
- [真实照片接口、螺丝 ROI 检查与待标注审核包](VISION.md)：整图定位后裁剪放大检查，上下螺丝仍联合判定；真实模型已试跑，尚无独立现场标注。
- [U7 AR 闭环接入与使用](AR_LOOP.md)：独立入口复用原资产；视觉、人工确认和下一步由新基线决定。
- [自动官方资料编译](COMPILATION.md)：完整章节检索、任务／协议生成、候选预览和生成任务 AR；不读取 GT 答案，不把语义复核当人工批准。
- [未见任务与设备评价](EVALUATION.md)：固定任务集和重复排程，分别统计契约成功、能力缺口、同模型复核及用户人工审核；保留全部失败。
- [Unity 人工审核与两次 U7 现场试验](REVIEW_UI.md)：在原前端审核7份候选，保存四项意见，分别选用第2次与第3次自动生成的 U7 进入相机及 AR。
- [历史候选方案](ground_truth/u7/v1/REVIEW_OPTIONS.md)：保留方法取舍，不代表仍待用户选择。
- [已采纳的人工意见](ground_truth/u7/v1/human-review.json)：保留两个操作节点、螺丝联合检查、规格仅作选材要求；绑定原审核任务与新任务指纹。
- [任务契约](src/manual2ar_baseline/gt.py)：对象、来源要求、条件、节点依赖、前置条件、目标及审核问题。
- [来源选择](ground_truth/u7/v1/selection.json)：用户已确认选用手工 U7 教材、空间动作和核验定义。
- [来源快照](ground_truth/u7/v1/sources.json)：原文、JSON 指针／Python 字符串常量位置、文件和文本 SHA256、官方图片身份。
- [规范化映射](ground_truth/u7/v1/mapping.json)：显式、可审核的转换数据；这份人工映射不是自动编译算法。
- `state-validation/`：当前冻结输入，`review.status=approved_for_state_validation`；`candidate/` 和 `candidate-v2/` 保留历史。
- [状态引擎](src/manual2ar_baseline/state.py) 与 [32 个受控符号场景](validation/u7/state-cases.json)：校验程序在给定事实后的行为，不是现场图片标签或模型准确率。

**批准范围明确分开。** 当前来源已由用户确认，方向／遮挡方案由用户委托审核，任务仅获准用于 `controlled_facts_only` 状态验证。结构校验、方案审核和受控测试不代表真实视觉标准已实现或实物安装正确。

## 运行

在仓库根目录可使用已有解释器验证，无需启动业务后端：

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline validate \
  baseline/ground_truth/u7/v1/state-validation --reference-root .

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest baseline/tests -q
```

独立安装时，在本目录创建自己的 Python 3.12+ 环境，运行 `python -m pip install -e . pytest`，然后执行 `python -m manual2ar_baseline`。运行依赖为 Pydantic 和 Pillow；pytest 仅用于开发。

重新捕获来源和生成候选时必须使用**不存在的新输出路径**：

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline snapshot \
  --selection baseline/ground_truth/u7/v1/selection.json --reference-root . \
  --output /tmp/u7-sources-new.json

PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline normalize \
  --sources /tmp/u7-sources-new.json \
  --mapping baseline/ground_truth/u7/v1/mapping.json \
  --review-decisions baseline/ground_truth/u7/v1/human-review.json --output /tmp/u7-gt-new
```

使用 JSON 指针和 AST 字符串读取来源，不执行参考 Python 文件。图片只保留官方身份、引用路径与指纹，不复制大型资源，不将其当作现场照片。

## 契约与边界

- 来源区分 `official`、手工指导定义、手工核验定义及原教程上下文；手工策略不会改标为官方原文。
- 每个要求保留来源原话；需要核验的规格和结果要求必须有条件映射，操作和选材要求必须有节点映射。按你的审核，M3-8 属于选材要求。检查映射是否存在，不把它宣传为自动证明语义蕴含或原文提取完整。
- 节点 ID 与操作文字分离；支持任意节点数量、重复操作文字和无环依赖。前置条件不必作为最终目标，例如尚未使用的耗材可能会被操作消耗。
- 条件明确区分视觉、人工与渠道待定；非视觉确认不能使用视觉渠道。冻结任务中的视觉条件仍是 `needs_visual_standard`；本轮实验观察协议单独版本化，不把接口试跑改标为视觉标准已验证。
- 按你的审核，上下螺丝保留联合检查，取消规格的独立人工确认；后续按用户委托审核将两个方向条件定义为人工确认。变更仅进入新版本，历史提案及审核记录保留。
- 任务 GT、现场标签和空间标签独立。这份 GT 定义未附独立的逐图或空间标注，实际操作完成状态记录在各自的运行会话中。
- 本目录 `ground_truth/` 的候选属于人工 GT 对照资产；自动编译器只读取原始官方资料和能力目录，不读取这些任务答案或审核映射。
- 指纹用于发现文件变化，不是身份签名。受委托审核记录绑定原任务、新任务及授权原话；完成审核后只生成 `approved_for_state_validation`，不产生真实视觉运行的批准状态。

## 开发顺序

1. 已完成本阶段来源选择、GT 结构化、逐项映射与方法审核，冻结状态验证版本。
2. 已用受控符号事实验证条件状态与下一步调度；它们不替代实际照片标注。
3. 真实视觉接口和待标注审核包已实现；仍需补充独立标注与正反样例，评价图片到事实的误差。
4. 已接入现有 U7 AR 表达和闭环；受控验收与真实相机联合现场验收分开记录。
5. 自动编译研究入口从官方资料生成候选，以 GT 为评价对照。当前 U7 精选演示使用已审核的 U7 定义。
6. 未见任务与设备评价已冻结首轮六任务、每任务三次的排程，并生成用户审核包。契约通过、人工审核及现场识别分别统计。[评价说明](EVALUATION.md)

11 月 16 日 U7 使用真实相机通过后端检查了底座、支架和遮挡。原会话在安装后退回未知，修订后从底座已核实的检查点分支重放，并用新照片复核完成状态。11 月 18 日开箱 AR 又完成两版教程的受控遍历与部分 Unity 交互。跨设备实物验收、独立标注的视觉准确率和实体 AR 对准误差仍待验证。[U7 实拍记录](../docs/history/U7_LIVE_TRIAL_20261116.md) · [开箱 AR 试验](../docs/UNBOXING_AR.md)
