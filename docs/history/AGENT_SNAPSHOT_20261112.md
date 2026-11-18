# Manual2AR：Agent 交接快照

快照：2026-11-12。先读本文件和 `AGENTS.md`，再读源码、Git 历史及相关测试。本文记录当前实现与边界；历史计划不是开发授权，测试通过不是实物验收通过。

## 当前工作树与目标

- 2026-11-12导航修复：用户明确开箱、首次打印也是演示内容，恢复catalog.tasks原卡片、缩略图、版本选择及继续当前指导；隐藏的仅审核/编译等研究入口。U7Demo查看官方步骤此前被reply==null挡住，现在catalog提供完整官方步骤，无需照片、模型或会话；生成计划后用当前目标范围的步骤，核验失败也能打开。原任务数据和配置此前未删除，本次恢复入口。接口10项通过，Unity最终 `validation-spatial-20261112-160037` 四场景0运行错误并构建Windows；已检查恢复的开箱、首次打印、进料、退料卡片及生成前官方步骤截图。证据 `runs/baseline/demo-navigation-fix-20261112-v1/`。

- 当前模块二保留“打印机开箱”“首次打印”等registry原教材任务，并提供“提问及拍摄现场生成AR指导”U7汇报Demo。先读 [U7_DEMO](../../baseline/U7_DEMO.md)。新U7DemoView＋guidance/u7_demo.py读取原已审核GT和资产；默认历史照片预设观察，另一模式实时拍摄/真实模型；用户明确授权两种保留、默认稳定。默认动画为照片平面示意，可点选调整，不能声称实机自动定位或空间标定。原研究接口/审核记录保留但菜单隐藏。
- Demo会话及素材在模块二runtime_dir/u7-demo，全部演示/真实模式记录均excluded_from_research_evaluation，不混入原18次编译、人审或实物结论。预设是明确编写的受控观察，不冒充旧VLM回复或人工图像GT；使用原两张历史照片SHA。原GT两节点8条件及绑定不改写，仍要求显式勾选当前全部人工条件。新会话已装支架、底座遮挡仍未知；切换预设整场景检查并处理反向变化；同一步失败保持当前步骤，不重复AR入口。
- 核心包0.7.2：goals.py支持明确组合目标，各子句独立对应官方任务后并集、按依赖执行；不支持对象仍拒绝。已新增复合问题测试。首轮相关Python223项通过，另9项Demo回归通过（重叠）；最终交付元数据见 `runs/baseline/u7-demo-20261112-v1/`。Unity首轮154028流程过但人工看截图发现Footer缺AppActionBar.Add，补齐并添加按钮可见尺寸断言；154546在复制工程阶段主动中断以补真实模式失败提示/相机切换新会话，未作为通过记录；最终154709用原历史照片字节＋预设观察完成四场景0运行错误及Windows构建，含失败不重播、底座单独结束、已装支架新会话保持未知、实时模式错误反馈及按钮实际尺寸检查。最后Demo/目标31项回归通过。生产后端已更新，演示素材两张已核对，用户审核文件保持原SHA。

- 2026-11-12修复最新两轮U7反馈与同一步重试，见 [UI_FLOW](../../baseline/UI_FLOW.md) 末节。最新f21d0459：照片支架已装，模型holder=true、base=true、screws=unknown且底座误认下方白壳；状态卡在底座缺证据，旧UI却隐藏后一步可见结果。倒数第二轮e6528303两次holder=false且实拍确在桌面，后台没有退步；结果默认AR入口及每revision重置准备使界面像重做第二步。现在总览显示所有相关步骤可见结果；原始观察放识别详情；同一步操作核验失败只调整后重拍，不重入AR。相同步骤/模式的新revision不重置准备，步骤/模式改变仍清理。
- 新增scene_conditions/user_summary/user_feedback为宿主展示字段，冻结定义、视觉协议、会话/照片/版本门控不变。默认用语只说结果和下一步，未知不说未安装，可见通过不冒充机械完成；人工要求仍保留官方语义。相关Python216项通过；最后简化部件短标签及“前一步待确认”措辞后，宿主相关14项再次通过（重叠，不相加）。Unity最终 `validation-spatial-20261112-100641` 四场景0运行错误并构建Windows，包含失败不重入AR和简洁反馈/详情检查。原始两轮记录、日志快照、后续交付校验在 `runs/baseline/feedback-20261112-v1/`。本轮不追加真实模型调用或手填实物结论；模型误认仍是已知限制。

- 当前0.7.1修复视频中的评估／核验／人工确认流程，先读 [UI_FLOW](../../baseline/UI_FLOW.md)。相机启动仅显示实时帧，必须主动点击评估；主按钮按初始评估、操作核验、待人工、完成互斥显示。照片结果先展示逐条件状态及对应原始模型观察；当前操作人工条件同窗，默认未勾选，一次提交。保留单项旧客户端兼容、严格视觉和会话版本门控；重开窗口不拍照，明确重拍不代替人工确认。
- 本轮最终基线及四个宿主测试文件215项通过；首次相关集合420项通过，两者重叠不相加。Unity最终 `validation-spatial-20261111-230811` 四场景0运行错误，已构建Windows；基线专项覆盖两资产、同窗确认、重拍、相机重建及失败恢复。生产后端已重启并启用两项交互契约，人工审核记录保持不变；原评价389文件SHA不变。交付需关闭旧客户端后重开 `Manual2AR-Windows/启动教学系统.cmd`，附U7现场评估与人工确认说明。报告 `runs/baseline/ui-flow-20261111-v1/REPORT.md`。本轮无真实模型调用或物理相机验收。
- 实际视频会话8cb7fa4c已完成两步，但旧UI隐藏判断依据并连续弹出人工项；另一轮1c17295c模型把黑色平台当支架，不能将程序接受说成识别正确。本轮不优化或追加调用真实模型。Windows旧日志272次SpatialCallout空引用，已在共享入口处理空label/anchor及新presentation无旧asset；相机重建统一取消旧跟踪、清除partsDisplayActive/冻结帧，失败也释放changing。受控帧源验证恢复不代表物理驱动验收。最近五会话及日志快照保留在 `runs/baseline/ui-flow-20261111-v1/`，旧事实及人工审核记录不改写。

- 当前已完成0.7.0“U7目标颗粒度与现场指导”改造，先读 [GOAL_FLOW](../../baseline/GOAL_FLOW.md)。新增核心goals.py按官方操作引用/部件/动作解析目标，不改冻结候选任务；实际r02/r03的“安装料盘支架／安装支架底座／滑入料盘底座”分别映射完整两步／仅底座／滑入支架并核实底座依赖，第三种明确展示解释。歧义和无来源支持的对象拒绝；显式编号父标题需与官方一致，未编号父层诚实标记compiled_task_summary，不声称完整开箱树。
- Session新增固定target_node_ids和scene_guided策略；strict默认保留旧符号评价。宿主启用scene_guided，已验证依赖后可指导结果仍未知的后续操作，完成条件仍须全部视觉及人工满足。底座单独目标核验后结束；完整/滑入目标底座通过后进入支架AR入口。首帧目标闭包观察、/verify当前操作、/assess全部必要依赖分开；未查询旧证据不冒充新观察，明确反证仍撤销依赖确认。照片提示包含问题及官方片段，声明不是事实；原任务/协议hash及session/action/frame/epoch/revision边界保留。
- 宿主新增/goal-preview与Begin.goal_intent，目标选择在新会话内固定并写goal.json；execution返回task_summary/current_step/goal_title/steps与guidance_ready。Unity新增SpatialGoalFlow，目标匹配解释→明确选用→相机；当前步骤置顶、整体及剩余进度持续显示，人工确认后提供下一操作入口，沿用几何位置仍实际确认。CheckBaseline区分/assess与/verify。AppReadableText会硬换行，测试检查Source；摘要缓存原文避免逐帧重复排版。
- 本阶段最终419项相关Python回归通过；局部视觉与宿主60项及最终提示12项重叠回归通过，不相加。两份真实生成U7×三问法的6例受控宿主闭环通过，原评价389文件全部校验未变；记录 `runs/baseline/granularity-20261111-v1/native-host-release/`。Unity首次214951因中文换行后的断言误报，随后修正测试和重复排版；215624四场景通过并构建，最终当前步骤置顶及位置确认优化后220020四场景0错误并完成Windows构建。旧交付备份 `builds/u7-pipeline/before-granularity-20261111-2150/`。
- 真实模型同一历史照片四轮各3问法，共28次HTTP/116023tokens：各轮观察契约接受1/3、3/3、2/3、2/3；第二轮出现底座单独问法判断未安装、另两问法判断已到位。随后对声明定位区域增加局部身份复核，包括粗粒负结论；无可靠ROI保留未知，局部确认缺失仍可指导。第三轮有运行中源码边界修补，保留启动版与后续磁盘版快照但不冒充冻结方法比较；最终一轮先封存14模块并逐问核对未变，结果为完整目标身份未知、底座单独目标契约失败、滑入目标进入底座人工确认。全部原回复及失败保留、没有真实人工确认或独立标签，不能把契约通过说成识别正确，更不能混入原18次编译率。详见 `runs/baseline/granularity-20261111-v1/REPORT.md`。用户最后明确以软件架构鲁棒为本轮验收重点，之后不再追加模型优化或调用。明确重新评估导致旧操作需复核时，反馈指出受影响操作并保留原人工确认事件。原实际装配确认与人审记录不回写，新UI需要重开客户端并建立新会话；本阶段仍无实物相机/装配/AR精度联合验收。

- 当前修复摄像头启动后“重新评估现场/拍照核验无反应”：实际请求200，但模型categorical事实的evidence_boxes为空，evaluate保留未知、ROI跳过；Unity每帧RefreshExecutionPreparation又覆盖进度/结果。已改SpatialBaseline使用verificationFeedback持久展示进度、最终反馈和错误；RefreshExecutionPreparation增加checking保护。宿主verify返回具体feedback（缺框/遮挡/细节不足/ROI未执行），读取诊断在状态提交前完成。
- 核心包更新0.6.1：vision.py强化框要求，categorical可见完整断言缺框时复用原最多一次修复；仍缺框则返回unknown，不发明框、不放宽规则。状态Reading.reason枚举未扩充，缺框原因放evaluated.details.diagnostic；避免诊断字段破坏状态事件契约。首次开发测试发现该枚举边界后已修正，失败日志保留。原13模块实现现有vision.py变化，旧评价原始实现继续保存在inputs/implementation，不能用新方法重算旧基线。
- 新增回归覆盖一次补充成功/失败/如实未知不重试、宿主反馈与busy释放、实时Unity Update下的核验进度/未知结果保留和按钮恢复。Unity受控服务才有/test/baseline/grounding，生产没有事实注入接口。真实模型已对用户同一历史帧（原始/归一化SHA及协议SHA均相同）完成整图+ROI两次调用，结果进入底座方向ask_manual，未提交任何人工确认；不是独立视觉准确率标注。记录 `/home/lixin/projects/Manual2AR-Data/runs/baseline/verification-fix-20261111-v1/real-photo/`。
- 修复后相关回归381项通过；最终Unity四场景0错误并完成Windows构建，证据 `builds/u7-pipeline/validation-spatial-20261111-183102/`，缺框反馈截图已查看。早期枚举边界失败的182804验证日志保留，未作为交付。最新包仍在 `builds/u7-pipeline/Manual2AR-Windows/` 与同级zip；更新后须关闭旧客户端重新进入相机。旧审核客户端备份 `builds/u7-pipeline/before-feedback-fix-20261111-182823/`。本阶段报告与后端记录位于 `runs/baseline/verification-fix-20261111-v1/`，不改原18次生成评价或人工标签。

- 当前进入“Unity人工审核与两次U7现场试验接入”。新增宿主 `guidance/baseline_review.py`、Unity `BaselineReviewView.cs`、固定登记 `resources/evaluation/v1/catalog.json`，入口“候选人工审核与 U7 实测”。先读 [REVIEW_UI](../../baseline/REVIEW_UI.md)。核心 baseline/ 的13个Python模块没有改变，原评价方法及代码快照继续匹配。
- API `/api/guidance/reviews`，延迟装载与runtime_dir同级baseline/中的固定评价归档，计划与整个archive manifest的SHA由公开登记固定；读取原文/实际协议/图片/操作依赖与条件，失败记录也可查。标签保存到 `runtime_dir/baseline-review/`，追加UUID历史、原子current版本、冲突检测；绑定计划/试次/task/manifest，不回写原归档。导出为原HumanLabels契约。UI默认未评价，支持草稿、正式审核、刷新、筛选、图片放大与返回；测试标签仅在受控服务临时目录，未替用户审核。
- 两个登记的实验试次为 `a1mini-u7-control.r02`、`.r03`，稳定UUID5复制到official-compilation，不重新调用模型、不改任务字节、不回退GT；沿用OfficialCompiler与BaselineSpatial动态隔离运行时。AR标题显示候选次数，各新会话从未知开始；审核和现场确认独立。未完成人工审核也可按用户授权先做实验，进入实验不会生成approved标签。
- 相关Python集合377项通过（含旧集合，不相加）；随后对审核/导入接口的局部增强另跑10项通过。两份真实U7生成任务均通过受控软件闭环 request_view→ask_manual→ask_manual→operate→ask_manual→complete，证据 `/home/lixin/projects/Manual2AR-Data/runs/baseline/review-ui-20261111-v1/native-u7-controlled-loop.json`。不是实际照片／真实人工紧固或硬件验收，原7份正式人审仍pending。
- Unity验证在独立工程 `/mnt/c/Users/lixin/Manual2AR-Baseline-Review-Validation` 完成并构建Windows客户端；首两版发现统计区域/下拉状态与截图重绘问题，修正后重建。旧交付备份 `/home/lixin/projects/Manual2AR-Data/builds/u7-pipeline/before-review-ui-20261111-175338/`。最新构建证据与启动位置见本阶段交付报告。不要把受控UI验证的approved标签导入用户评价。
- 最终Unity验证／Windows构建证据 `builds/u7-pipeline/validation-spatial-20261111-180230/`（4场景、0错误），截图已人工查看；保存后图像/文本、统计及候选状态均显示正确。新版交付位于 `/home/lixin/projects/Manual2AR-Data/builds/u7-pipeline/Manual2AR-Windows/` 与同级zip，含《候选审核与U7实测.md》。已核对旧8011进程cwd/cmdline为本树后优雅重启；新后端修订 `93ec4f462a993392b833d41aa863ba30302dd8e5829516d1d11bba324d631cae`，实际只读API核对18次/7可审/0已审、两次U7实测可用，未替用户触发正式审核或实际相机会话。交付报告 `/home/lixin/projects/Manual2AR-Data/runs/baseline/review-ui-20261111-v1/REPORT.md`。当前源代码仍未提交。

- 新基线当前进入“未见任务与设备评价”阶段，包版本 `0.6.0`。先读 [baseline/README.md](../../baseline/README.md)、[COMPILATION](../../baseline/COMPILATION.md) 与 [EVALUATION](../../baseline/EVALUATION.md)。核心不导入旧业务／视觉运行时，宿主复用既有 AR 资产与显示。
- 用户接受基线多次生成只有一次成功，要求分别统计 VLM 编译成功、人工审核通过，并为后续模块/模型对比与消融保留基线。首轮 suite 为 `baseline/evaluation/transfer-v1.json`：6任务×3次固定排程，包括 U7 seen control、U8/前盖/切刀同设备任务、A1擦嘴与P1霍尔板局部安装。来源预检过，不声称盲测、整个旧项目未见或模型训练未见；P1不是整页换件验收。用户选择亲自审核，不能代填标签。
- 新增 `evaluation.py` 与 CLI `eval-plan` / `eval-run` / `eval-report`。期望URL/标题只在检索后评价，不喂模型、不强选页；检索错误不继续编译，但仍计管线排程。固定成功也跑完；显式修复属于同一试次；中断消费原试次，恢复不偷重试。保存源码快照/资料/能力/模型参数/依赖/排程SHA；有单写锁与逐次证据校验；报告需同版源码/依赖，升级后可用计划内源码快照出报告。仅Linux/WSL评价命令，不是新增Unity界面。
- 编译器新增 `compile-stage.json` 及语义复核前提案检查点：后续复核超时不会抹去任务编译阶段成功，最终AR门控仍保持严格。统计契约通过、方法支持、AR目录覆盖、同模型复核和ready；AR目录覆盖不含宿主几何/作用点容量或实物验收。人工标签绑定计划/试次/taskSHA/manifestSHA，4项rubric及审核人理由；pending不算失败，无标签不报人工通过率。
- 当前相关回归 **372项通过**（含此前集合，不相加）。本轮没有修改Unity或重测摄像头/现场装配。首轮真实重复评价路径 `/home/lixin/projects/Manual2AR-Data/runs/baseline/transfer-20261111-v1/`，计划已冻结，真实生成结果与用户待审核材料见其中 `report/`。
- 首轮18试次已结束：6次检索范围错误未调用模型；12次真实生成、27次HTTP调用（20编译含8修复、7语义复核），全部返回，用量254692 tokens。契约通过7/12，含检索失败7/18；U7 2/3、U8 3/3、A1擦嘴0/3、P1局部装板2/3，前盖/切刀各0/3。排除已见U7后为5/15（启动模型的未见试次5/9）。同模型复核7次均通过，但人工7份仍pending；仅U7两次ready，P1r03另有ROI缺口，所有新任务/设备缺AR资产。人工索引为该目录 `START_HERE.md`，包含7份审核页与空白标签；用户未提交审核结论，禁止替填。
- 已独立核对39个冻结输入、18试次证据、12个编译manifest、报告manifest、全部调用与用量，归档源码可复核计划。原自动报告有6个检索失败试次的链接指向未生成compilation目录，属于展示缺陷；不改封存报告，START_HERE已链接真实selection/source记录。后续报告器可在新版本修正，不能重封旧试次、混入新逻辑或隐去失败。当前源码/全部新基线仍未提交，HEAD用Git读取。
- 主入口为模块二任务列表“从官方资料生成 AR 任务”，手工路径改名“U7 GT 对照”。新增 `sources.py`、`compiler.py`、`capabilities/v1.json`、宿主 `guidance/official_compiler.py` 与 Unity `OfficialCompileView.cs`；自动路径不读 GT 任务／人工映射／核验答案。契约类仍复用 `gt.py`。
- 原始来源为公开 manifest 固定的离线 Wiki archive；重解析 DOM 核对文字、标题与图片关联，收束完整父章节。自动检索当前选择 standalone 官方开箱第7步，和 GT 的 combo 页不同，不强行替换来源。用户完成声明只记录，编译只收到经来源复核绑定的操作目标；明确安装上下文支持“希望完成部件”，否定／复杂约束保守拒绝。
- 生成任务、方法、视觉协议和 AR 绑定一并封存；数量、规格、方向、机械紧固、目标依赖闭包与能力覆盖均检查。固定件 ROI 从所属操作唯一安装关系派生。未支持要求保留并阻止执行，无 GT 回退。`experimental_ready` 是可审阅实验候选，不是人工语义批准或真实视觉标准。
- API `/api/guidance/compiled/jobs`，选用候选后注册 `/api/guidance/compiled/jobs/{id}/spatial`。根应用需将 `official_compiler.app` 指向聚合 app，动态路由才对外可见。compiled 运行模式 `experimental_compiled_photo_analysis`，不从 GT ledger 装载。人工确认强制绑定 task SHA、会话、epoch、revision；固定激活时整个 manifest，核验前／回写前复核产物与来源，同任务换协议也拒绝。
- 当前相关回归 **357 项通过**，包括原测试集合；不能与早期 114／325／351 相加。Unity 独立工程编译与四场景回归通过，自动编译预览→生成任务 AR→返回预览也通过；证据 `/home/lixin/projects/Manual2AR-Data/builds/u7-pipeline/validation-spatial-20261111-162237/`。后续仅增加后端来源／版本固定门控，已用受控 API 回归覆盖。
- 真实编译诊断已归档 `/home/lixin/projects/Manual2AR-Data/runs/baseline/compiler-20261111-v1/REPORT.md`：a5 为真实模型可用候选（2节点6条件，未启用ROI）；a7 的真实回复任务／模型复核通过，但被过严ROI映射拦截；修正后 a8-replay 原始回复逐字回放成功，任务／条件未手改、未调用新模型，带ROI并跑完受控 AR API闭环。全部失败也保留；共12次已返回的真实模型调用，服务报告133229 tokens，不作成功率样本或独立准确率。没有新现场照片、物理相机或真实装配联合验收。
- 编译 CLI 为 `compile-official`，独立 GT 比较为 `compare-gt`，详见 COMPILATION。GT 比较在封存之后才读取 GT、不回写候选。当前本机已安装可编辑包0.5.0；后端需重启、前端需重新编译，未构建 Windows EXE、未覆盖旧交付、未重启用户原有服务。编译任务不跨服务重启自动恢复。
- 用户已确认手工 U7 来源、两个操作节点、螺丝联合检查、M3-8 只作选材要求；后又委托按经验审核方向／遮挡策略并进行状态与调度验证。当前冻结输入为 `baseline/ground_truth/u7/v1/state-validation/`（2 节点、8 条件、19 项要求），仅 `approved_for_state_validation`。两个方向采用明确人工确认；完整核验的同会话节点可在正常遮挡时保留有效证据，新会话未知须补拍；反证、身份不明或上下文变化会重新限制依赖。具体见 [STATE_VALIDATION](../../baseline/STATE_VALIDATION.md)。历史两版候选保留，委托身份与授权原话独立记录，不伪称实物人工标注已完成。
- 用户随后授权真实视觉开发，并明确暂时没有额外照片／标签，先完成接口与待标注审核包；又指出旧代码有整图定位底座后放大找螺丝的方法。新基线已独立接入 `provider.py`、`vision.py`、`photos.py`、`photo_review.py` 和 CLI，当前协议 `baseline/ground_truth/u7/v1/visual-protocol-roi.json`。见 [VISION](../../baseline/VISION.md)。不导入旧运行时，不修改冻结任务批准范围，照片会话为 `experimental_photo_analysis`。
- 照片接口阶段验证：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest baseline/tests -q`，114 项通过；`validate-state` 的32个受控符号场景通过，两集合有重叠不相加。测试包括 fake provider，不能充当真实视觉标签。该阶段未修改旧运行时代码；后续 AR 阶段的验证见下文。
- 已用私有本机配置的真实 `qwen3.8-flash` 试跑两张历史实拍，记录含中间方法、失败与当前协议，索引 `/home/lixin/projects/Manual2AR-Data/runs/baseline/vision-20261111-d9b173b7/SUMMARY.md`。当前 ROI 结果：底座可见图返回 `ask_manual`（方向）；已装支架图返回 `request_view`（底座身份未知）。没有替用户提交实物人工确认。审核页和全部 unrated 标签已生成，尚无独立准确率。最终遮挡原因传播修复通过受控回归，未再次调用模型；每次真实记录保留调用时实现指纹。
- 旧 `automatic_vision.py` 的整图→ROI→点定位与 `automatic.py` 的两视角标定三角化是两个环节。照片接口阶段只移植前者的二维观察思路，保存裁剪来源和坐标变换；不做跨照片实例拼接。CLI 补拍恢复须明确 `--same-context` 或新 `--context-id`；失败／被修改记录不可恢复。
- 后续用户明确授权 AR 闭环：复用现有 U7 资产与展示，新增 `baseline/ar.py`、冻结 `ar-bindings.json`、宿主 `guidance/baseline_spatial.py` 和 Unity `SpatialBaseline.cs`；入口为模块二任务列表“U7 基线闭环”，API `/api/guidance/baseline/spatial`、契约 `baseline-ar-v1`。核心包不导入旧运行时；宿主复用标定／两视角／展示，不使用旧核验或进度。见 [AR_LOOP](../../baseline/AR_LOOP.md)。
- AR 会话每次从未知开始。运行目录 `runtime_dir/baseline-ar/`，按相机／rig 一次复制旧空间配置并记录来源，不覆盖旧配置、不继承旧教程完成标记。仅当前需要操作时显示动画；视觉和人工条件满足才推进。底座方向、实际紧固及支架方向逐项确认。没有新增隐藏底座的放行规则。
- 本轮相关回归命令见 AR_LOOP，325 项通过（其中包含原 114 项基线测试，不能相加）。Unity 受控闭环检查已加入 `tests/unity/WikiPipelineValidation.cs` 并由 ProductValidation 调用，测试服务才提供 `/test/baseline/state`；生产路由没有事实注入接口。没有新增真实模型调用或物理摄像头／装配验收。
- Unity 2022.3.34f1 独立工程编译与四场景回归通过，零运行错误；新增闭环两套资产实际渲染、3 个人工门控、正常遮挡沿用与最终完成均通过。报告与截图 `/home/lixin/projects/Manual2AR-Data/builds/u7-pipeline/validation-spatial-20261111-155037/REPORT.md`。此前两次验收脚本因缺少快照字段、错误按空对象判断是否有视觉资产而失败，日志保留；正式相机已有快照，渲染器已有 HasPlacement 判定，本轮修正测试后通过。未构建 Windows EXE，也未覆盖旧交付包。
- 后端新增本地依赖 `manual2ar-baseline`；`run.sh setup` 包含 `-e baseline`，现有环境需先本地安装并重启后端。Unity 源码已改变，旧 EXE 不含新入口；不能用旧构建证明打包。

- 本次开发工作树：`Manual2AR-U7-Pipeline`，分支 `lixin/u7-end-to-end`。当前提交用 `git rev-parse HEAD` 获取；不要依赖对话里的旧提交号。
- 源基线 `2634a05`：原 Dev 的手工 U7、自动空间初始化及三模块系统。本树在此基础上增加 Wiki→任务→U7 AR 纵向管线。
- `Manual2AR-Dev` 是另一工作树，不是本树别名；已归档主仓库 `../Archive/Manual2AR/.git` 是关联工作树的 Git 公共目录，不能删除。
- 下述参考原型的研究与限制：同一契约如何从官方资料生成、对齐现场、绑定现有能力并核验；其自动绑定仅覆盖 U7 的 `holder.base`、`holder.slide` 各最多一次。新 `baseline/` 的状态引擎不采用这个限制，已用另一设备的多节点符号任务验证，但尚无跨设备实物结果。

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
| Wiki→AR 管线 | [WIKI_TO_AR](../reference/WIKI_TO_AR.md) | `guidance/pipeline.py`、`knowledge/retrieval.py` |
| 官方任务编译、出处 | 同上 | `knowledge/compilation/{compiler,models,prompts,source,binding}.py` |
| 实验开关／成本／人工评价 | [PIPELINE_ABLATIONS](../reference/PIPELINE_ABLATIONS.md) | `guidance/experiments.py`、`enhancements.py`、`tools/evaluation/pipeline_ablation.py` |
| 现场状态与执行 | [SCENE_DRIVEN_EXECUTION](../reference/SCENE_DRIVEN_EXECUTION.md) | `guidance/{scene_planning,stateful_spatial,pipeline_spatial}.py` |
| 严格观察与规则 | [VISUAL_OBSERVATION_CONTRACT](../reference/VISUAL_OBSERVATION_CONTRACT.md) | `guidance/observations.py` |
| 人工 U7／坐标与自动配置 | [AUTOMATIC_U7_SETUP](../reference/AUTOMATIC_U7_SETUP.md)、[PRINTER_WORK_COORDINATES](../reference/PRINTER_WORK_COORDINATES.md) | `guidance/spatial/{automatic,automatic_vision,machine,placement,service}.py` |
| 公共 UI／图例／资产 | [UI_CONTRACT](../reference/UI_CONTRACT.md)、[GUIDANCE_DISPLAY_CONTRACT](../reference/GUIDANCE_DISPLAY_CONTRACT.md)、[VISUAL_ASSET_LIBRARY](../reference/VISUAL_ASSET_LIBRARY.md) | Unity `Common/`、`Guidance/Spatial/`、`VisualGuidance/`；后端 `visuals/` |
| 应用／启动／构建 | [OPERATIONS](../OPERATIONS.md)、[ARCHITECTURE](../ARCHITECTURE.md) | `application/`、`tools/build/`、`deploy/windows/` |
| 本轮审查及遗留边界 | [REPOSITORY_AUDIT](REPOSITORY_AUDIT_20261111.md) | 对照其中的修复与验证记录 |

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

当前审查的最终测试、构建与未测范围见 [REPOSITORY_AUDIT](REPOSITORY_AUDIT_20261111.md)。不要将较早文档中的425／508／410等数字写成当前结果，也不要把集合有重叠的测试数相加。

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
