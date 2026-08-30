# Manual2AR 论文图与视频采集协议

## 证据原则

每个 panel 只绑定一个窄 claim。原图、系统真实 overlay、结构化判断和跟踪日志分别保存；排版脚本只做布局，不补画模型没有输出的轮廓。失败结果进入 `failure_cases`，不得删除后只保留成功案例。

文件命名：`FIGURE_RUN_PHASE_REVISION`，例如 `B_R03_overlay_001.png`。每次运行在采集接口中填写 `figure_id`、`run_id`、模型、prompt、说明书和编译版本，以及是否允许论文使用。

## 六张图

### (a) Component recognition and labeling

- 总览中只标注 toolhead assembly、build plate、touchscreen、AMS Lite spool holder、filament inlet、PTFE tube。
- 只用细轮廓、引线与标签，不展示调试框。
- Claim：说明书部件术语被映射到这一台真实设备的可见区域。

### (b) Guided spool placement

- 总览确认空槽；候选集合中优先 3 号，用户仍需确认。
- 保存空轴原图、SAM 可见表面、世界锚定虚拟料盘、推入和旋转箭头、10 秒跟踪日志。
- Claim：viewpoint-adaptive resegmentation with world-anchored guidance。不能声称隐藏背面已被完整 3D 分割。

### (c) Spatial guidance for filament insertion

- 从侧下方约 45 度拍同槽送料模块、料头和可见 PTFE 路径。
- 孔洞不可见时只高亮正确送料模块并提示“从模块下方平直插入”。
- 黄色释放按钮标为禁止操作，不作为正常上料目标。

### (d) Verification of successful loading

- Before：料盘已安装，料头未进入送料模块。
- After：同槽送料模块已捕获料头，正确 PTFE 路径出现连续耗材证据。
- 必须保存五项必要谓词及 `safe_to_advance`。仅装上料盘不能完成任务。

### (e) Pre-print build plate inspection

- 正确组：平台存在、对齐、表面清洁、无残留。
- 错误组：仅放置安全、明显、可移除的残留物；不启动设备运动。
- Claim 仅限可见安装和表面状态，不涉及温度或打印可执行性。

### (f) Error detection and corrective guidance

- 构造耗材靠近错误送料模块但不强插的安全错误。
- 红色错误证据、`safe_to_advance=false`、当前步骤不变；青色纠正指向正确送料模块。
- 保存纠正前、纠正后及两次结构化判断。

## 三段视频

1. **空间附着**：空轴保持在画面内，手机小幅移动 10 秒；记录漂移和重定位次数。
2. **双手闭环**：记录操作前画面，放下手机操作，再按指定视角拍 after 并验证。
3. **错误恢复**：错误路径被拒绝，按青色纠正后再验证通过。

## 接受与停止条件

- 已占用槽不进入候选；遮罩跨相邻槽、过大、漏掉目标点或不稳定时不显示。
- 10 秒漂移超过画面对角线 5% 时暂停并重定位。
- 缺少任何必要谓词时输出“不确定”或补拍，绝不完成。
- 48 小时内若大视角跟踪不稳定，演示和论文都改用“视角自适应重分割与世界锚定指引”的表述。

## 导出

图 (a) 与图 (e) 可以先从 iPhone 导出的原始照片运行静态、可追溯评估。必须在
已经配置 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL` 和 `DASHSCOPE_MODEL` 的终端执行：

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/evaluate_paper_static.py a \
  /ABSOLUTE/PATH/TO/overview.jpg \
  --run-id A_R01

PYTHONPATH=. .venv/bin/python scripts/evaluate_paper_static.py e \
  /ABSOLUTE/PATH/TO/build_plate.jpg \
  --run-id E_R01
```

图 (a) 默认调用本机 `http://127.0.0.1:8020` 的 SAM2 服务细化六个部件轮廓；
质量门不通过时保留千问原始紧框并记录原因，不人工补轮廓。图 (e) 由四个必要
可见谓词和确定性门计算 `safe_to_advance`。每次输出均包含
`raw_model_result.json`、`result.json`、`evidence.json` 和 `provenance.json`。

得到记录后可生成干净 overlay：

```bash
PYTHONPATH=. .venv/bin/python scripts/render_recorded_overlay.py \
  /ABSOLUTE/PATH/TO/raw.jpg \
  output/paper_static/A_R01/evidence.json \
  output/paper_static/A_R01/overlay.png
```

这里生成的 overlay 只使用记录下来的 polygon、mask 或 bbox；不会让排版脚本
重新预测或修补证据。

用真实证据填写 `docs/paper_evidence_spec.template.json` 的副本。`evidence_json`
必须包含运行时保存的 polygon、mask 或 bbox；脚本只改变透明度、轮廓颜色和标签，
不会补画模型没有输出的几何。然后运行一键管线：

```bash
cd backend
.venv/bin/python scripts/prepare_paper_package.py \
  ../docs/paper_evidence_spec.json \
  ../output/paper_48h
```

程序执行顺序是：真实几何渲染 → panel 专属审计 → 300 dpi 排版 → manifest。
任何 panel 失败时不会导出可用于论文的最终包，而会在
`paper_evidence_audit.json` 逐项写明补拍、漂移、遮罩或谓词问题。导出目录必须
包含六张 300 dpi 图、逐图证据副本、overlay provenance、审计结果和
`figure_evidence_manifest.json`。

## 每次物理采集后的最短检查

1. 先确认槽位总览中，已有料盘的槽位没有出现在空槽候选中。
2. 图 (b)、(c) 连续记录 10 秒；若日志中任一帧 `drift_ratio > 0.05`，该次运行进入失败案例。
3. 图 (d) 在“仅装料盘”时必须停留在 S1；只有送料口和 PTFE 证据也通过才允许完成。
4. 图 (f) 错误画面必须同时保存 `safe_to_advance=false` 和至少一个失败的必要谓词。
5. 每个 panel 至少保留三次独立运行；不能只保留最漂亮的一次而删除失败运行。
