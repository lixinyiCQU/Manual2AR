# 未见任务与设备评价

本阶段评价现有基线的迁移结果，不根据评价样本调优检索器、提示或模型。允许重复生成失败；固定次数全部执行，保存每次失败、修复、模型调用和人工意见。

[首轮任务集](evaluation/transfer-v1.json) 含 6 个任务：U7 已见对照；A1 mini 的 U8、工具头前盖、切刀完整安装；A1 擦嘴套件和 P1 霍尔开关板安装单步。每项固定 3 次，共 18 次生成尝试。来源已做预检，不宣称盲测；“未见”指新基线尚未针对它适配，不指整个旧项目或模型训练集从未涉及。U8 属同页邻接任务，A1 属同家族设备，P1 也只覆盖指定单步，不能据此声称跨制造商通用性。

期望 URL、章节和范围是检索评价标签，**不指定检索结果，不进入模型提示**。错误章节、局部冒充完整任务或资料缺失均计入完整管线分母，不把错误材料继续交给编译器。另报告正确资料进入模型后的编译比例。

## 固定方法与计数

`eval-plan` 只读取资料，不调用模型。它保存任务集、实际检索结果、能力目录、全部基线源码快照、代码与原始资料 SHA、公开模型参数、Python/Pydantic/Pillow 版本及完整排程。凭据不导出、不计算指纹。`eval-run` 使用同一现有配置模型，检查输入、代码和参数未变；新增模型或模块版本必须建新计划。运行器适用于当前 Linux/WSL 后端，使用进程文件锁防止两个运行器同时消费排程。

一次尝试包含至多两次编译调用（初次＋一次明确修复），随后至多两次同模型复核调用。修复不增加尝试分母。成功也继续剩余次数，没有“成功即停”、隐藏重试或 GT 回退。进程中断的已启动试次标为 interrupted，不重新消费；保留临时记录。未运行的排程不当作失败，未跑完整组时主成功率为 null。

| 指标 | 分子与分母 | 解释 |
| --- | --- | --- |
| 检索选择正确 | 正确设备/章节范围 ÷ 固定任务数 | 与编译能力分别统计 |
| VLM 编译成功 | 提案通过任务/观察契约 ÷ 全部排程 | 包含检索失败；不代表语义正确 |
| 正确输入后的编译成功 | 契约通过 ÷ 实际启动模型的试次 | 与上一指标同时报告 |
| 首次回复契约通过 | 无编译修复的契约通过 ÷ 排程 | 不把修复算成新的成功样本 |
| 方法支持 | 无方法/ROI缺口 ÷ 排程 | 与 AR 目录覆盖分开 |
| AR 目录覆盖 | 全节点均有合法目录绑定 ÷ 排程 | 不代表宿主作用点容量、几何或实物执行通过 |
| 同模型语义复核 | faithful=true ÷ 契约通过 | 不是独立审核或准确率 |
| 可试用候选 | experimental_ready ÷ 排程 | 保留生产门控，仍需审阅和现场核验 |
| 人工审核覆盖 | 已审核 ÷ 已封存且可审阅的契约通过候选 | pending 单列，不算拒绝 |
| 人工审核通过 | approved ÷ 已审核 | 没有人工标签时为 null |
| 人工通过占完整排程 | approved ÷ 排程 | 尚未审全候选时 rate 为 null |

此外按 seen_control / unseen_task / unseen_device 和每个任务分别统计，报告完整跑完 K 次后“至少一次契约通过”的任务比例。总体比例不替代未见分组结果；重复共享相同任务和来源，不当作更多独立设备样本。模型服务报告的 tokens 与已返回用量的调用数同时保留，缺失用量不假装是零成本。

任务提案在后续语义复核前先封存检查点。因此复核超时可以同时记为“任务契约通过、整次流程失败”；只有原有严格门控全部满足的候选才能进入 AR。新增评价记录不放宽执行条件。

## 运行与人工审核

从仓库根目录运行，计划和报告用仓库外的新目录：

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline eval-plan \
  --suite baseline/evaluation/transfer-v1.json \
  --archive /home/lixin/projects/Manual2AR-Data/sources/bambu-wiki/runs/20261024T145623Z_e2655a/archive.json \
  --manifest resources/sources/bambu_wiki/manifest.json \
  --config configs/app.local.json --model qwen3.8-flash --repeats 3 \
  --output /tmp/manual2ar-transfer-new

PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline eval-run \
  --plan /tmp/manual2ar-transfer-new --config configs/app.local.json --model qwen3.8-flash
```

`eval-run` 会真实调用模型并产生服务费用。全部结束后生成 `report/REPORT.md`、逐次 `report/review/*.md`、`results.json` 和空白 `human-labels.json`。审核页给出原文、官方图片、生成要求、操作依赖和核验规则；失败原始回复保留在 `trials/<id>/compilation/`。

用户已选择亲自审核。复制标签文件，逐次填写四项 task_scope / requirements / dependencies / verification，各取 pending/pass/fail，再填 decision（pending/approved/rejected）、reviewer、note。批准必须四项都 pass；拒绝至少一项 fail。不能替用户填通过，也不能只挑一次成功而省略其他可审核候选。

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline eval-report \
  --plan /tmp/manual2ar-transfer-new --labels /tmp/my-reviewed-labels.json \
  --output /tmp/manual2ar-transfer-human-report-new
```

标签绑定计划、试次、任务和完整编译 manifest SHA；跨试次、候选被修改或混用版本会拒绝。评价报告只读原始产物，不激活任务或修改 GT。源码升级后，请使用该计划 `inputs/implementation/` 内保存的源码作为 PYTHONPATH 和相同 Python/依赖版本重新出报告，避免用新判定逻辑解释旧结果。

后续模型对比复用同一 suite、来源、重复次数及参数策略，分别建立新计划；模块消融也保存各自源码和能力目录，注明实际改变项。首轮诊断与后续开发使用过的任务不再当作新的盲测集。真正的扩大留出评价需要新任务/设备；现场视觉和 AR 泛化还需独立照片、标签、设备几何与实际验收，本阶段不替代这些工作。

## 首轮实测

真实模型沿用 `qwen3.8-flash`，18 次固定排程全部结束，12 次实际进入编译模型。契约通过 **7/12（58.3%）**；包含检索范围失败的全管线为 **7/18（38.9%）**。已见 U7 为 2/3；未见任务组为 3/9，未见设备组为 2/6。排除 U7 后，未见合并为5/15，实际启动模型的未见试次为5/9。3/6个任务至少一次契约通过，其中包含已见U7。

27 次真实调用、254692 tokens；失败、修复和能力缺口均保留。U7 两次候选可试用；U8 三次和 P1 两次通过任务契约，但无匹配AR资产，P1其中一次另有ROI缺口。7份人工审核尚未评价，不把同模型7次复核通过当人工通过率。

本轮相关 Python 回归372项通过；未新增Unity构建或新设备现场验证。[结果和7份人工审核入口](/home/lixin/projects/Manual2AR-Data/runs/baseline/transfer-20261111-v1/START_HERE.md)。
