# Dev 仓库风险审计 · 2026-11-18

Manual2AR 用官方教材、现场照片和人工确认指导 A1 mini 开箱及安装。本次按一台开发机、一个操作者、前后端可分别重启的演示规模审查。对象是 `Dev` 提交 `fbc79c5` **加上本机尚未提交的开箱 AR 改动**。仅交接这个提交会漏掉新接口、Unity 视图和动作资源。[当前验收范围](ACCEPTANCE.md)

## 演示或交接前优先修

1. **开箱 U7 收到明确反证后，章节仍可能显示已完成。** 同一会话先在开箱 AR 核实底座和支架，再从图文页拍照得到“底座未安装”。内存回放中，图文核验已撤销底座通过，章节总览却继续采用 AR 入口此前保存的两项结果。操作者可能依着旧标记跳过底座。建议两条入口共同撤销被反证的底座及其依赖项，加一条“AR 完成 → 图文反证 → 重开总览”的回归，并另测普通遮挡能沿用有效历史证据。[图文核验](../apps/backend/src/manual2ar/modules/guidance/u7_sequence.py#L40) · [章节完成标记](../apps/backend/src/manual2ar/modules/guidance/unboxing_ar.py#L143)

2. **Unity 工程导出可能误删源码。** `package` 先递归删除 `paths.builds/Manual2AR`，再从源码复制工程。若构建根误配为 `apps/unity`，目标就是源工程，未提交的 Unity 文件也会丢失。此项由路径与执行顺序确认。建议在同步和删除前检查源、目标的真实路径和目录归属，拒绝重叠或未经认领的非空目录。用临时哨兵文件测试错误配置仍保留源文件。[Unity 工程导出](../apps/backend/src/manual2ar/application/manage.py#L85)

3. **旧交接工具对数据区私有配置的排除不完整。** 源码区按文件名排除本机配置，数据区只点名一处旧归档。现场盘点有 4 份其他归档中的私有配置落入待复制集合，内容匹配现有凭据扫描，会触发中止。若历史密钥已独立更换，扫描可能漏过并将旧密钥带入交付物。本轮未导出或分发这些文件。建议对整个数据树按私有配置文件名排除，保留路径级排除清单，以与当前密钥不同的虚拟旧值测试。[排除规则](../tools/build/handoff.py#L32) · [凭据扫描的输入](../tools/build/handoff.py#L132)

## 可复现性与长期运行

4. **照片验收和会话摘要可能相差一次操作。** 11 月 18 日最终两次真实模型试验中，磁盘上的 `acceptance.json` 都已记录修订 2，`flow.json` 仍是修订 1、未评估。复盘时先读对应动作的接受记录。建议以已落盘的接受记录更新可重建的摘要，并测试拍照或人工确认后直接退出。两份原始记录位于数据目录 `runs/dev/unboxing-ar-20261118/real-photo-final/tutorial-runs/`。[验收写入与返回](../apps/backend/src/manual2ar/modules/guidance/unboxing_ar.py#L320) · [摘要写入](../apps/backend/src/manual2ar/modules/guidance/service.py#L52)

5. **关闭原图留存后，失败的分割初始化仍可能留下现场照片。** 推理服务先保存 `input.png`，在模型运行和掩码检查之后才按配置删除。其间任一步骤抛错，原图会留下，重试又会创建新目录。建议把原图清除放进覆盖写入与检查的 `finally`，用模拟失败验证删除，同时保留诊断元数据。[写入与清理位置](../apps/inference/src/manual2ar_inference/engines/engine.py#L116) · [默认留存设置](../configs/inference.example.json#L23)

6. **11 月 12 日交接工具不能直接用于今天的 Dev 布局。** 当前 Dev 有一条指向共享 Playwright 缓存的链接，复制器会拒绝它。恢复工具仍寻找 `builds/u7-pipeline`，本机当前程序在 `builds/dev`。建议排除可以重装的浏览器缓存，从清单读取交付渠道，并在临时目录测试创建、恢复、找到启动程序的全过程。现有封存包按其原说明恢复。[复制器](../tools/build/handoff.py#L88) · [启动器恢复](../tools/handoff_restore.py#L114) · [原包说明](HANDOFF.md)

7. **更新 AR 配置后，Windows 启动器可能沿用旧后台。** 后端修订只覆盖 `apps/backend/src/manual2ar` 下的 Python 文件。开箱动作目录在服务初始化时读入。只改动作条件、保持后台运行时，启动器仍可能判断修订相同，演示读到旧条件。当前可重启对应的 Dev 后台。建议把实际加载的任务和资产目录摘要纳入兼容性判断，以仅改变动作配置的情形测试。[后端修订](../apps/backend/src/manual2ar/modules/guidance/pipeline.py#L139) · [开箱目录加载](../apps/backend/src/manual2ar/modules/guidance/unboxing_ar.py#L89) · [启动器判断](../deploy/windows/Start-Backend.ps1#L29)

8. **打印状态检查会话闲置过期后仍可能占用内存。** 用户发起检查后断开，下次建立会话时，服务从会话表中移除过期项；后台检查队列仍持有旧会话。多轮演示积累的对象不受活跃会话数上限约束。建议闲置淘汰和显式关闭共用清理逻辑，模拟多次断开和时间推进，核对两处登记均被释放。[闲置淘汰](../apps/backend/src/manual2ar/modules/inspection/service.py#L72) · [队列回收](../apps/backend/src/manual2ar/modules/inspection/progress.py#L120)

## 整理与核查范围

本轮整理了文档入口、历史证据、迁移后的引用、桌面导出脚本读取的报告路径，以及新机验收中容易混淆的步骤。源码树中清除了 4 个被 Git 忽略的 Python 字节码文件和 3 个缓存目录，共 30,080 字节。未发现纳入源码版本控制的常见 Python 字节码、Unity 临时目录或运行日志。开箱新资产、运行记录、标定、人审标签及用于对照的旧研究管线均保留。[文档导航](README.md)

重点核查了启动与构建、资源加载、教程拍照和人工核验、会话保存、GPU 原图留存、检查队列及交接工具。第 1 项通过受控回放核对，第 4 项通过实际磁盘记录核对，第 3、6 项核对了当前目录和代码，其余来自静态调用链检查。本次未运行真实模型、摄像头、Windows UI 或破坏性打包，未逐行审核第三方源码、模型权重和 Unity 资产内容。

| 本轮验证 | 结果 |
| --- | --- |
| 现有 Python 测试 `tests` 和 `baseline/tests` | 837 项通过，0 失败、0 跳过，耗时 317.76 秒。Starlette 测试客户端触发 1 条 AnyIO 弃用提示。 |
| `bash run.sh resources` | 16 项资源、6 个任务变体、40 个开箱 AR 动作展示配置通过校验，离线 Wiki 快照 SHA256 匹配。 |
| 冻结评价数据 | 389/389 份文件与原清单哈希一致。清单和计划自身也与交接工具记录的固定哈希一致。 |
| 文档和交付引用 | 全部 27 份 `docs/` 文档可从导航找到。源码库 48 份 Markdown 中的 202 处本地文件链接均可解析，两份导出脚本引用的 8 项文档输入均存在。 |

演示前优先处理第 1 项。下次导出或移交工作树前，优先处理第 2、3、6 项，并核对交付的版本是否实际包含本机开箱功能。
