# U7：问题与现场照片到 AR 指导

本工作树 `Manual2AR-U7-Pipeline`、分支 `lixin/u7-end-to-end` 从 `2634a05` 独立开发。原 `Manual2AR-Dev` 和正式教材保持原样。这是单设备、已有 U7 能力上的纵向原型，不是任意设备自动生成资产的平台。

最新现场驱动执行（v1.4 / 新模式v3）见 [SCENE_DRIVEN_EXECUTION](SCENE_DRIVEN_EXECUTION.md)。旧候选不迁移，启用新开关后重新生成。

最新可选优化见 [PIPELINE_ABLATIONS](PIPELINE_ABLATIONS.md)，视频诊断见 [BASELINE_VIDEO_AUDIT](BASELINE_VIDEO_AUDIT.md)。本页原流程描述全部开关关闭的基线。

## 用户验收

使用本工作树独立构建目录中的 `Manual2AR-Windows/启动教学系统.cmd`。进入设备教学 → 模块二 → **提问并生成 AR 指导**。

1. 启动摄像头，必要时选择 USB 镜头。让打印机、底座和待安装支架入镜，点击“拍摄现场”。
2. 输入真实目标，例如“我想安装料盘支架，请指导我”。不需要指定 U7、Wiki URL 或章节。
3. 点击“根据问题与照片生成”，侧栏显示四个阶段和等待时间。生成可能需要1–2分钟；现场描述保持简短，完成后自动打开预览。
4. 检查生成动作、核验条件、官方原文和参考图，再确认进入。关闭预览后仍可点击“预览并进入 AR”重新打开。
5. 在 AR 页面启动摄像头，同镜头同画幅可复用相机标定。新生成任务需在空间锚点配置中确认工作坐标板，拍两视角设置本任务作用点；不会沿用旧任务的螺丝位置。已有本候选配置时仍需确认相对位置未变，再点击开始。先固定底座，核验并人工确认后再进入支架安装；第二步手动识别部件。
6. 核验失败或不确定时补拍；不能以动画播放或照片替代真正紧固的人工确认。

若模型服务失败，可以重新拍摄或重新生成；系统不会暗中改用手写 U7。目标超出现有两动作能力时保留候选但禁用 AR 接入。

若已生成过任务或等待中退出，请点击顶部“继续上次任务”。系统恢复原照片和候选；生成未结束时继续等待，结束时直接打开预览，不重复调用模型。恢复的是最初的照片与方案，AR仍需重新取景、识别和核验。目标或照片改变后需重新生成。

## 实际链路与契约

`离线 Wiki → 原文/图片证据 → 问题+照片 → BM25章节候选 → 有限VLM章节选择 → Direct编译 → 能力绑定 → 用户预览确认 → 独立U7 AR会话 → 生成条件核验`

- 复用 HTML 原生结构与不可变来源 ID，不提前指定 U7 章节。首版检索限定 `/zh/a1-mini/`；按任务章节补齐编号子节与图片。中文使用2至4字片段，保留型号/规格词。
- VLM 从最多8个检索候选中选择最直接支持用户目标的章节；依据不足时停止。该选择与编译独立保存。
- 照片生成的是检索线索和未经核验的现场描述；不据此省略前置操作或自动标记完成。
- 编译输出沿用 `ProcedureDocument` / `ObservationNode`。每条要求保留 `explicit/inferred/observation_policy` 与证据 ID。最多一次本地契约修复；供应商客户端的传输重试单独存在。
- `BindingPlan` 只支持当前顺序 `holder.base`、`holder.slide`，且每步须有视觉核验条件。选择已有网格、运动与部件身份，不复制手写教材的验收 Prompt 来修补候选。
- AR 使用生成的指导文字、参考图和观察条件；识别目标仍限现有底座与支架能力。五类视觉指导契约、工具/滑入资产、CPU/GPU跟踪和米制定位沿用基线。
- 每个候选有独立几何、动作参数和验收进度；只复制相机标定，不复制其他任务的作用点、机器XYZ、朝向或动画微调。本候选后续自行设置的几何可以保留，但每次开始仍需显式确认。旧实现复制的配置按 `compiled-spatial-v2` 策略备份隔离，原教材不写回。
- 编译、参考图展示和既有资产绑定不变；核验调用只发送一张当前现场照，官方图不进入该调用。`SceneCheck` 返回现场图片ID、SHA256、观察点ID和证据框；缺失、串照片、串条件或无有效证据时不能放行。原始输入、图片角色清单和返回随核验保存。
- 核验结果绑定当前步骤/目标及请求token；切换后回到同一步也不能采纳之前的结果。失败的旧请求不覆盖更新核验；视觉条件不满足时不能弹出人工确认绕过视觉核验。非视觉条件仍只允许指定渠道确认。
- 源任务、绑定和文件哈希不一致时拒绝运行。照片 SHA256、capture_id、client_frame_id 贯穿生成请求，AR 会话继续使用既有帧/步骤身份与过期检查。

首次快速验证没有引入 PDDL、知识图谱、向量服务或新的资产生成。当前可用资料是离线 Wiki；未找到原始同设备 PDF，因此不宣称已经完成 PDF 接入。

## 入口与产物

后端：`bash run.sh start`。本机新工作树配置使用 `127.0.0.1:8011`；runtime/cache/builds 都使用独立 `u7-pipeline` 目录。凭据留在忽略的本地配置，不复制到交付物。

API：

- `GET /api/guidance/pipeline/config`
- `POST /api/guidance/pipeline/jobs`：intent、JPEG/PNG base64、source_sha256、capture_id、client_frame_id、camera_signature。
- `GET /api/guidance/pipeline/jobs/{id}`：queued/observing/retrieving/compiling/binding/ready/unsupported/failed/approved。
- `GET /api/guidance/pipeline/jobs/latest`：恢复最近任务及其拍摄身份，不触发生成；无记录时返回empty。
- `GET /api/guidance/pipeline/jobs/{id}/scene`：读取原始照片，校验SHA256，禁止浏览器缓存。
- `POST /api/guidance/pipeline/jobs/{id}/approve`：确认并提交 procedure_sha256。
- 审核后的独立 AR：`/api/guidance/pipeline/candidates/{id}/spatial/...`。

生成记录位于配置 runtime 的 `u7-pipeline/jobs/{id}/`：

`input.json`、`scene.jpg`、现场模型输入/返回、`selection.*`、`retrieval.json`、`evidence-bundle.json`、`compile/source.json`、编译输入/返回、`draft.json`、`lineage.json`、`review.json`、`task/procedure.json`、`binding/result.json`、`approval.json`。失败保留 `failure.json` 与已完成阶段产物。状态是工程处理状态，不是模型语义正确率。

## 验证边界

`tests/backend/test_wiki_to_ar.py` 覆盖从提问照片到生成候选、确认、动态接入组合应用的 AR 路由、前置核验、人工条件、来源篡改及失败保留。`test_semantic_compiler.py` 覆盖编译/引用/观察边界。

`tests/unity/WikiPipelineValidation.cs` 在受控模型与合成照片上检查输入、生成、证据预览、AR接入和返回。它不打开真实摄像头。

真实模型烟雾验证使用官方参考图代替现场照片，仅证明配置的模型服务、完整检索/编译/绑定链路可运行；失败尝试同样保留。实物动画贴合、遮挡、分割效果与安装正确性需用户现场验收，不由该验证代替。

2026-11-10 本机验证：完整 Python 回归449项通过；最后的生成链路与构建来源检查18项通过。Unity四场景及新增问题/照片→候选→确认→AR→返回测试通过，Windows构建日志显示成功，交付经过源码/项目/二进制哈希核对。真实模型样例 `e94ac59f8af849cdb36a494e22582f08` 自动检索并生成两动作、绑定就绪，耗时40.23秒；这是单次开发烟雾样例，不是任务成功率。日志与失败样例在外部 `runs/u7-pipeline`，Windows验证在 `builds/u7-pipeline/validation-spatial-20261110-212031`。

二次实测诊断：用户两次任务均已ready（84.04/90.48秒），没有收到approval；最近一次生成完成晚于Player退出约21秒，Player日志没有运行异常。修复等待反馈、自动预览、断线有限重试和任务/照片恢复；26项相关测试通过，含后端重启恢复与原照篡改拒绝。诊断、原Player日志和仅使用官方证据的紧凑编译验证在外部 `runs/u7-pipeline/ui-recovery-validation`。不据一次耗时对比宣称普遍提速。

管线基线逻辑修复（2026-11-10）：保留检索→Direct编译→U7绑定→AR的大框架。旧空间缓存不再跨任务继承，历史副本备份至候选 `spatial/backups/`，用 `profile-policy.json` 记录新策略。核验改为当前现场单图并校验照片/条件身份及证据框；保留现有编译条件，不用手写U7条件补齐模型遗漏。42项编译/管线专项及465项Python回归通过；Unity验证为受控模型和合成照片，不能代表实物识别性能。当前模型的误识别、编译条件遗漏/错误和置信度校准问题留待后续模型/架构实验，不由本轮工程修复冒充解决。
