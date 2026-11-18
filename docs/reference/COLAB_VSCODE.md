> 手动浏览器方式：上传 [Manual2AR_GPU.ipynb](../../deploy/colab/Manual2AR_GPU.ipynb) 至 Colab，选择 T4 并全部运行，将下载的 `inference.connection.local.json` 放入本地 `configs/` 覆盖旧文件，再重启本地后端并重新识别。默认不挂载 Drive；无需执行下方 CLI 登录、启动任务。笔记本首段包含完整操作说明。

# VS Code 一键启动 Colab GPU

本入口运行在 WSL，使用固定版本的 Google 官方 CLI（0.7.5）管理本项目专用 Colab 会话。VS Code 提供任务按钮与日志，原来的网页 Notebook 保留。配置继续通过 JSON 文件编辑，日常无需手动上传、下载或移动连接文件。

## 第一次使用

1. 在 **VS Code 的 WSL 窗口**中打开仓库里的 `Manual2AR.code-workspace`，允许工作区任务运行。工作区应显示名为 Manual2AR 的文件夹。
2. 选择菜单 **终端 → 运行任务 → Colab: 初始化工具**。第一次会复制 `configs/colab.example.json` 为私有 `configs/colab.local.json`，并安装独立 CLI 环境。本机是否完成以当前配置和登录状态为准。
3. 运行任务 **Colab: 登录 Google**。在终端提供的链接中登录，批准 Google 授权，将 Google 页面显示的授权码粘贴回同一个 VS Code 终端。不要发送到聊天或写入项目配置。
4. 运行 **Colab: 启动 GPU**。首次准备依赖与权重需要等待，终端显示阶段进度；成功后自动进入持续监控，终端保持运行。
5. 看到 **6/6 GPU 就绪** 后，启动本地业务后端、在 Unity 开始新的识别。连接文件已经写入 `configs/app.local.json` 的 `gpu.connection_file` 所指定位置，默认 `configs/inference.connection.local.json`。

Windows Colab 扩展和 WSL CLI 不共享登录状态；扩展已登录仍可能需要第 3 步。CLI 会缓存 Google 授权，失效时重新执行登录任务。登录任务只查询运行时，不创建 GPU，也不读取浏览器 Cookie。

## 日常操作

| VS Code 任务 | 行为 |
|---|---|
| Colab: 启动 GPU | 完成部署和健康检查后持续监控，Ctrl+C 只停止本地监控 |
| Colab: 持续监控 | 监控已有运行时和公网服务，不部署、不申请 GPU、不自动重启 |
| Colab: 诊断连接与进程 | 用户主动执行一次远端进程、本机服务健康、GPU 显存检查，下载远端日志 |
| Colab: 无模型诊断实验 | 独立诊断会话，不加载 SAM/Cutie，有限时长采集并持续保存到 Drive |
| Colab: 释放诊断运行时 | 只释放无模型诊断别名，不操作业务运行时 |
| Colab: 查看状态 | 查询本项目运行时与已安装 GPU HTTP 服务；不会分配运行时 |
| Colab: 查看日志 | 下载并脱敏状态、安装、服务和连接日志到项目外运行目录 |
| Colab: 仅停止推理服务 | 停止本项目监督的安装进程、GPU 服务和隧道；**运行时仍保留** |
| Colab: 停止并释放本项目运行时 | 删除本项目专用会话的整个运行时，释放资源；临时文件、内存和会话随之丢失。其他笔记本的运行时不操作 |

安装进程在远端后台运行；本地取消等待后，安装可能继续。再次点击启动可接续等待，不会因为等待中断就另开 GPU。配置或源码变化时，已就绪的服务会重启；正在安装另一版本时会拒绝覆盖，请先明确停止再重新启动。

连接更新后，Unity 中的旧 Cutie 跟踪会话不再有效，需要重新识别。失败或超时不会覆盖原连接 JSON，原连接也不代表仍然可用。

## 文件配置

只需编辑 `configs/colab.local.json`。它与私有连接文件一起被 Git 忽略。无需在命令行中填写 API Key 或令牌。

| 字段 | 说明 |
|---|---|
| `session_name` | 本项目专用会话名；默认 manual2ar-integrated |
| `gpu` | 默认 T4；也支持 L4/G4/A100/H100，账号必须有相应额度；不自动升级或购买 |
| `auth` | 默认 oauth2；已自行设置 ADC 的用户可改为 adc |
| `client_oauth_config` | 通常留空，使用官方 CLI 自带 OAuth 客户端；需自建客户端时填写文件路径 |
| `remote_root` | 独立 `/content` 子目录，默认 `/content/Manual2AR`；不能使用整个 /content 或 Drive 根目录 |
| `startup_timeout_seconds` | 默认等待 3600 秒；超时不会删除远端运行时 |
| `poll_seconds` | 远端状态轮询间隔，默认 5 秒 |
| `monitor_seconds` | 就绪后每轮监控完成后的等待秒数，默认 30，允许 15–300；旧配置不必添加此项 |
| `remote_logs` | 默认向 Drive 持续保存脱敏日志及遥测，每 15 秒一次；即使不缓存模型也需要 Drive 授权 |
| `diagnostics` | 无模型诊断的名称、独立会话别名、有限时长和采样间隔 |
| `public_url` | 默认留空，启动临时 HTTPS 连接；已有可访问服务地址时可填写 |
| `inference` | Cutie 精度、内部尺寸和记忆间隔等性能设置；模型选择与推理协议保持不变 |
| `drive_cache.enabled` | 默认 false，首次使用无需挂载 Drive；设为 true 可跨运行时复用模型、依赖缓存，启动时可能需要额外授权 |
| `drive_cache.path` | Drive 缓存目录；必须在 `/content/drive/MyDrive` 内 |

同一个运行时重复启动会尝试复用已经准备的环境。跨运行时缓存只有开启 Drive 并成功授权挂载后才生效；默认不会保存现场图像到 Drive。

远端留存与诊断源码位于 `deploy/colab/{retention,diagnostics}.py`，按需生成的笔记本入口见 [使用说明](../OPERATIONS.md)。业务留存自下次部署开始生效；旧配置使用默认值，不必复制密钥或手动移动日志。

## 运行中监控与会话消失

正常启动任务在 `6/6` 后保持终端监控；已启动的服务可单独运行「Colab: 持续监控」。两者使用同一个监控锁，避免重复请求。需要再次启动任务时先 Ctrl+C 结束现有监控；它不释放 GPU。监控不持有部署操作锁，另一终端仍可以停止服务或释放运行时。关闭 VS Code/WSL 或系统休眠会停止本地监控。

监控分别查询 Google 的本项目运行时记录和经过验证的公网 `/health`，不执行笔记本循环、不模拟点击、不调用保活接口、不运行虚假推理。轮询是可用性监测，不能保证延长 Colab 的寿命；不会在实例消失后自动申请新 GPU。仅当 Google 成功查询后移除了原实例，才报告当前账号不再返回该实例；账号切换也可能造成此结果，不能一概断言平台回收。查询超时报告“无法判断”，公网 TLS/DNS 失败报告“运行时存在但公网不可达”。旧连接属于另一实例时停止探测，避免把其他部署误当成当前实例。

日志在 `paths.runtime/colab/`：`monitor-events.jsonl` 每轮记录 UTC 时间、运行时标识摘要和状态；`monitor-status.json` 保存最新结果。`launcher.log` 新增 UTC 时间，安装收据记录运行时与就绪时间。不会记录令牌或完整 HTTP 请求。运行时已被平台删除时，无法再取回远端日志，也不能从“不存在”反推唯一回收原因。

从正常状态首次转入公网连接/鉴权异常时，监控会尝试通过文件接口保存启动状态、服务和隧道日志到 `monitor-captures/<UTC时间>/`（每个文件最多末尾 64 KiB，单次下载超时 15 秒）。连续同一种错误不重复采集；采集不执行内核代码，也不会重启服务。网络中断可能只留下本地观察记录。

公网不可达时，主动运行诊断入口。如果远端本机 `/health` 正常但公网失败，检查隧道或本地网络；服务进程退出时检查 `remote-service.log` 的 OOM/异常；Google 不再返回实例则是整个运行时已消失。诊断结果保存为 `diagnosis.json`。初次部署的 `status.json: ready` 是上次启动结果，不是持续存活证明。

本项目 `session_idle_seconds=300` 只清理闲置 Cutie 跟踪会话，释放掩码记忆；不关闭服务或释放 GPU，不能通过增大它来阻止 Colab 回收。Google 官方 CLI 已移除客户端保活守护程序；Colab 的空闲回收、使用额度及最大寿命由平台管理，未公布固定“十分钟”保证。后台 HTTP 服务运行、内核显示 IDLE 与整台 GPU 运行时存在是不同状态。免费或零付费计算单元环境更不适合持续远程服务。参见 [官方 CLI 会话说明](https://github.com/googlecolab/google-colab-cli/blob/main/docs/01_session_management.md)、[Colab 限制与额度](https://research.google.com/colaboratory/faq.html)。

实验时运行真实交互任务，启用 Drive 缓存以减少回收后的重建等待；需要更长实验窗口可使用具有正计算单元余额的适用 Colab 方案，仍无存活保证。需要连续稳定服务时，使用 [学校 HPC 入口](../../deploy/hpc/README.md) 等已分配、由你控制的 GPU 节点；本次没有部署 HPC。

## 自动化边界

本地启动器为 `tools/deployment/colab.py`，远端监督器为 `deploy/colab/worker.py`。复用现有推理源码包、Drive 缓存和 GPU 服务；没有复制模型算法或改写三个模块的 API。

启动器只上传规范推理源码包以及白名单部署设置，不上传本地 VLM Key、Wiki、摄像头图片或工作目录。Google 运行时代理令牌与本项目 GPU API token 各自管理；不会把 Jupyter 地址误写成推理服务地址。连接经协议、TLS/地址、令牌格式和 HTTP 健康检查后原子替换，失败保留原文件。令牌不进入 Notebook 输出或启动器日志。

本机工具与会话状态位于 `paths.cache/colab/`；日志与收据位于 `paths.runtime/colab/`。官方 CLI 的 Google 授权由其保存在 WSL 用户的 `~/.config/colab-cli/`，不在项目中；该入口采用私有文件权限。记录的历史命令不包含 GPU token 的内容。

CLI 与依赖锁定在 `deploy/colab/requirements-cli.lock`，安装在项目外独立 Python 环境，不改后端 Python 依赖。MCP 或其他本地自动化可以调用同一入口；不需要为 MCP 再维护一套部署逻辑。

## 维护用入口

VS Code 任务内部使用以下命令，用户正常使用任务菜单即可：

```bash
bash run.sh colab-setup
bash run.sh colab-login
bash run.sh colab-start
bash run.sh colab-start-watch
bash run.sh colab-watch
bash run.sh colab-diagnose
bash run.sh colab-status
bash run.sh colab-logs
bash run.sh colab-stop-service
bash run.sh colab-release
```

免费 Colab 的 GPU 分配、最长运行时间及回收由平台决定，启动器不模拟保活、不规避额度限制。该入口用于交互实验，不能承诺长期服务可用性。

官方参考：[Colab CLI](https://github.com/googlecolab/google-colab-cli)、[VS Code Colab 指南](https://github.com/googlecolab/colab-vscode/wiki/User-Guide)、[Colab 使用限制](https://research.google.com/colaboratory/faq.html)。

诊断笔记本是按需生成的构建产物：`bash run.sh diagnostics-notebook` 输出到 `paths.builds/Manual2AR_Diagnostics.ipynb`，不写回源码目录。历史部署验收记录已归档，不作为当前服务存活的证据。
