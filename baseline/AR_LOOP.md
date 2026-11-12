# U7 的 AR 闭环

新基线负责“证据是否充分、当前条件、下一步”；现有 U7 空间服务负责“标定、作用点、资产和显示”。两者通过独立入口连接，旧教程进度不会被当作完成证据。

## 使用入口

原手工任务入口现为：模块二任务列表 → **U7 GT 对照** → 启动摄像头。自动主入口为 [从官方资料生成 AR 任务](COMPILATION.md)，复用本节闭环。需要当前源码对应的 Unity 前端；旧 EXE 不会自动获得新入口。

1. 启动后先用当前照片核验现场。底座未知就提示补拍；底座条件明确未满足时，才进入对应操作指导。
2. 沿用原有相机标定、定位板、两视角／手动作用点配置和“开始本步”流程。确认定位板与打印机没有相对移动后，显示原有工具、上下两颗螺丝、图例和锚定文字。
3. 实际操作后点击“拍照核验”。底座视觉条件通过，界面依次请求确认底座方向、实际紧固。每次只确认一个明确条件，取消不推进。
4. 底座条件全部满足，自动切换到支架节点。尚未连接时显示原有支架滑入虚影、方向箭头及终点提示；再次核验并确认支架方向后，显示本任务条件已满足。
5. 首次看见支架已装且底座被遮挡，仍须补充底座证据；同会话此前完整核验的底座，仅正常遮挡时可以沿用历史证据。

补拍、人工确认和完整完成时隐藏操作动画。识别、分割、播放结束或关闭弹窗均不能完成安装节点。定位板丢失、作用点不足或标定不符时，沿用原有隐藏和配置提示；不拿二维螺丝框生成三维作用点。

如果没有可靠底座视角，系统会停留在补拍；本阶段没有新增通过人工确认绕过隐藏螺丝的规则。

## 实现边界

- [独立映射](ground_truth/u7/v1/ar-bindings.json) 将 `install_base` 绑定到 `holder.base / u7.holder_base`，将 `install_holder` 绑定到 `holder.slide / u7.holder_slide`，并冻结任务、动作、显示配置、自动定位配方及资产目录指纹。
- [基线 AR 契约](src/manual2ar_baseline/ar.py) 仅生成展示决策，仍不依赖旧业务运行时。它可以接收其他任务映射；当前实际制作和评价范围只有 U7。
- [后端适配器](../apps/backend/src/manual2ar/modules/guidance/baseline_spatial.py) 复用现有空间服务，但替换其进度和核验渠道。视觉仍调用新基线的整图／ROI 观察与规则，人工仍调用新基线条件引擎。
- Unity 的 [基线视图适配](../apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/Spatial/SpatialBaseline.cs) 复用既有工作区、资产采样器、渲染器、图例和官方参考图；不复制网格和动画，不生成执行代码。

新 API 前缀为 `/api/guidance/baseline/spatial`，运行契约 `baseline-ar-v1`。既有 `/config`、`/sessions`、`/frames`、定位／标定／作用点及展示事件接口继续由空间服务提供；`/verify`（也支持 `/assess`）进入基线照片核验，`/manual-conditions` 只接受当前待确认条件。

人工请求带当前 epoch、revision、动作和条件；重复、旧弹窗、跳步或缺少视觉证据的确认会被拒绝。视觉调用期间允许继续取景，但不能并发核验或确认。模型结果提交前核对原会话修订、当前动作和照片时效；会话关闭或变化后不推进。

## 数据与配置

运行目录是配置 `runtime_dir` 下的 `baseline-ar/`。首次使用每个相机／打印机配置时，从旧 `guidance-spatial/profiles/` 复制标定、作用点、机器坐标和动作微调，保存来源哈希。以后只调整副本；清空副本不会悄悄重新导入旧位置。复制已有位置也不代替用户对现场未改变的明确确认。

进度每次新建会话都从未知开始，不继承旧教程的“完成”记录，也不跨会话恢复。换相机／画幅会重开会话。复制的几何如果与当前现场不一致，仍须重新配置；系统尚不能自动识别打印机或定位板是否发生了相对移动。

照片核验保留原有审核包及模型原始结果；宿主另保存 `acceptance.json` 或 `rejected.json` 说明观察提案是否被实际会话接收。被拒绝的观察不能作为该 AR 会话的完成依据。人工确认保存明确条件、声明及会话版本。退出会话释放帧、分割任务和相机。

真实视觉使用模块二现有 `vlm` 配置，定位／分割使用既有服务。已有开发环境需安装本地基线包并重启后端：

```bash
.venv/bin/python -m pip install --no-deps -e baseline
bash run.sh start
```

新环境的 `bash run.sh setup` 已包含该包。前端需要重新编译；本轮没有覆盖旧交付 EXE。

## 验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest \
  tests/backend/guidance tests/backend/test_stateful_pipeline.py \
  tests/backend/test_services.py tests/backend/test_application.py baseline/tests -q
```

本轮上述相关回归 325 项通过，覆盖原有 U7 资产／空间能力和新基线。新增 API 测试验证：两个资产配方实际输出、底座→人工方向→人工紧固→支架→方向→完成、正常遮挡沿用、新会话隐藏底座不跳步、旧确认拒绝、动画不推进、模型失败／迟到不推进、标记丢失隐藏及旧配置不被覆盖。

Unity 验证使用独立工程和受控后端，检查真实资产渲染、三个逐项确认和完成界面，输出 `baseline-ar.json` 及四张截图；结果路径记录在根目录 Agent 快照。它没有打开物理摄像头，也没有调用真实模型。

本次 Unity 编译与四场景回归通过，`runtime_errors=0`；新增闭环结果为 `controlled_closed_loop=true`、`both_u7_assets_rendered=true`、`manual_gates=3`、`normal_occlusion_retained=true`。记录位于 `/home/lixin/projects/Manual2AR-Data/builds/u7-pipeline/validation-spatial-20261111-155037/`，可从其 `REPORT.md` 查看截图和早期验收脚本失败说明。本轮未构建或覆盖 Windows EXE。

这一步完成软件闭环接线。先前两张实拍只验证过照片接口；本轮受控 AR 闭环不能代替“真实相机＋真实模型＋实际装配”的联合现场验收，也不新增视觉准确率、贴合精度或扭矩结论。
