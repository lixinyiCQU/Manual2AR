# 真实照片观察接口（实验阶段）

本阶段实现把历史实拍文件提交给真实 VLM，将观察转成条件状态，再由调度器给出补拍、操作或人工确认。本节 CLI 使用冻结 U7 对照任务，`--intent` 只记录用户原话，不把声明当证据。后续 [AR 闭环](AR_LOOP.md) 已接入相机帧和现有 U7 展示；[自动官方资料编译](COMPILATION.md) 另提供生成任务的主入口，复用相同观察与调度方法。

## 查阅原仓库后的实现

原方法在 [automatic_vision.py](../apps/backend/src/manual2ar/modules/guidance/spatial/automatic_vision.py)：整图和官方参考定位灰色底座，扩大边界后裁剪，将长边至少显示为 640 像素，再定位上下螺丝及导向点，映射回原图。它只定位真实可见点，不判断安装完成或推断深度。

[automatic.py](../apps/backend/src/manual2ar/modules/guidance/spatial/automatic.py) 接收两张不同角度的定位结果，结合相机标定和位姿三角化，生成 AR 空间候选。因此“不同角度”与“裁剪放大”是两个环节。

新基线独立实现了 **整图观察 → 目标 ROI 裁剪 → 局部螺丝观察 → 坐标回原图 → 规则判定 → 状态调度**，不导入旧运行时：

- [当前协议](ground_truth/u7/v1/visual-protocol-roi.json) 声明对象、参考图、查询、物理孔位、判定规则和裁剪策略；引擎不硬编码 U7 名称或两个孔位。
- 整图中目标身份、区域和接合关系明确才进入局部检查；裁剪不足 16 原生像素或找不到可靠区域时保持未知，不能使用整图的粗略螺丝结论代替。
- 局部再次核对部件身份；误认立柱开口等情况会使关联的整图结论退回未知。模型仍可能同时误认，两次调用不构成独立验证。
- 上下螺丝仍是一个联合条件：在完整可观察区域，两个不同实例处于各自孔位才通过；缺失则失败，遮挡、细节不足或身份不明则未知。没有单独的规格确认或视觉松紧推断。
- 裁剪来自同一照片，只改善模型关注区域，不增加原始细节、不增加独立帧。保存原生／提交尺寸、裁剪矩形、照片哈希与坐标变换。
- 补拍可以恢复同一会话；目前按各照片的观察更新条件，不做跨照片螺丝拼接、自动视角选择或三维重建。

`visual-protocol.json` 保留早期整图方案，`visual-protocol-roi-v2.json` 保留中间试跑协议，避免覆盖实验来源。日常使用当前 ROI 协议。

## 模型与程序各负责什么

模型只接收现场照片、官方身份参考及观察查询，不接收规则的 `expected`、人工条件答案或用户完成声明。参考图明确标为身份参考，不能作为现场证据。模型返回可观察性、覆盖范围、关系类别、实例框和说明；程序校验照片身份、查询覆盖、实例位置、重复实例、坐标和规则，再产生 true / false / unknown。

这些约束能够检查格式和内部一致性，不能证明模型看对了物体或螺丝。因此协议为 `experimental_requires_independent_labels`，不修改任务包原有的 `approved_for_state_validation / controlled_facts_only` 批准记录。照片会话单独标为 `experimental_photo_analysis`，禁止混入受控测试事件。

方向和实际紧固仍采用已审核的人工渠道；只有本节点的视觉条件及依赖通过才允许正向确认。首次看到已装支架而底座未知时会要求补拍。同一现场、此前完整核验的底座，后续仅正常遮挡时可以沿用有效证据；身份不明、细节不足、反证或现场改变则限制后续步骤。是否同一现场由操作者显式声明，目前没有自动设备身份检测。

## 运行

仓库根目录使用已有 `.venv`。独立安装需要 Python 3.12+、Pydantic 和 Pillow；运行时不依赖 Codex Skill、旧业务后端或 GPU 服务。

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline observe-photo \
  --bundle baseline/ground_truth/u7/v1/state-validation \
  --protocol baseline/ground_truth/u7/v1/visual-protocol-roi.json \
  --reference-root . --image /absolute/path/scene.jpg \
  --config configs/app.local.json --model qwen3.8-flash \
  --intent '我希望安装料盘支架' \
  --output /absolute/path/new-photo-run
```

这里复用了本机已经配置的模型，并非新增模型推荐。配置读取独立 JSON 或既有配置的 `vlm` 节，仅使用 endpoint、密钥、模型和请求参数；缺少模型时必须显式指定。密钥也可以由 `QIANWEN_API_KEY` 或 `DASHSCOPE_API_KEY` 提供。所有输出目录必须不存在且放在仓库外。

补拍时增加 `--resume-run /absolute/path/previous-success-run --same-context`，输出使用新目录；现场或部件实例改变则用 `--context-id new-physical-context` 代替 `--same-context`，清空旧证据。只有完整且哈希校验通过的成功记录可以恢复，协议也须一致。

当计划返回 `ask_manual`，由实际操作者逐项核实后执行，例如确认底座方向：

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline confirm-photo \
  --bundle baseline/ground_truth/u7/v1/state-validation \
  --protocol baseline/ground_truth/u7/v1/visual-protocol-roi.json \
  --resume-run /absolute/path/previous-success-run --same-context \
  --condition c.base.direction --statement '我已对照官方参考核实底座方向' \
  --output /absolute/path/new-confirmation-run
```

`c.base.secure` 是实际紧固确认，`c.holder.direction` 是支架方向确认；不要用命令示例代替现场核实。可以多次指定 `--condition`，但只提交本次确实核实的项目。

## 审核与标注

每次照片记录保留原始文件、实际提交图、参考图、查询、单独的判定规则、提示词、Schema、原始模型回答、请求参数与 token 用量、整图／局部观察、坐标变换、条件结果、会话事件和下一步。自动生成 `REVIEW.md`、候选框叠加图及全部为 `unrated` 的 `labels.template.json`，最后以 manifest 封存。

模型输出不符合契约时最多允许一次显式修复，保存两次调用；照片身份不符直接拒绝，不修复。没有 HTTP 自动重试或静默换模型。失败记录不可恢复；生成审核文件失败也不能提交会话进度。真实调用可能产生费用，运行记录保留实际用量。

审核者先看原图，再核对模型框和逐项说明。把模板复制到封存目录以外，填写 reviewer、是否独立审核，以及每项 true / false / unknown；没有审核的项目保留 unrated。不要在原始记录中改模板或补标签。

```bash
PYTHONPATH=baseline/src .venv/bin/python -B -m manual2ar_baseline score-photo \
  --run /absolute/path/photo-run --labels /absolute/path/reviewer-labels.json \
  --output /absolute/path/new-score
```

评分校验照片、任务、协议和条件集合，分别计数误放行、无依据放行、误拒绝、无依据拒绝和模型弃权。无人工标注时 rated=0，label_agreement=null；不报告准确率，不改变任务状态。对早期没有审核页的成功记录，可用 `review-photo --run ... --output ...` 生成独立派生审核包。

## 本次验证与限制

- 114 项基线测试通过，包括 ROI 坐标变换、局部身份不明、细小区域拒绝、正常遮挡沿用、上下文重置、人工门控、格式修复、失败原子性及标注绑定。受控 provider 测试不评价图像理解质量。
- 两张历史实拍提交给配置的真实 `qwen3.8-flash`：当前 ROI 方案将底座可见照片判为视觉条件通过，下一步要求人工确认方向；支架已装照片的底座身份仍未知，下一步要求补拍。未提交实物方向／紧固确认，未产生任务完成。
- 保留整图方案疑似底座误认、中间版本和一次审核页生成失败，不只保留成功结果。修复后端到端运行已成功；最后的遮挡原因传播修复仅以受控回归验证，真实试跑各自保存调用时的实现指纹。
- 实验索引：`/home/lixin/projects/Manual2AR-Data/runs/baseline/vision-20261111-d9b173b7/SUMMARY.md`。全部现场条件尚待独立标注；两张照片不能证明准确率提升或跨设备通用性。

接口依据官方的 [视觉理解输入说明](https://help.aliyun.com/zh/model-studio/vision/) 和 [结构化输出说明](https://help.aliyun.com/zh/model-studio/qwen-structured-output)，使用图片 data URI 与 JSON Object 返回，并在本地进行严格 Schema 校验。语义判定质量仍须用独立正反样例评价。
