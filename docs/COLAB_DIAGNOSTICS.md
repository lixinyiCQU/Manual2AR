# Colab 远端日志与无模型诊断

在当前 `Manual2AR.code-workspace` 使用 Run Task；所有参数通过 `configs/colab.local.json` 修改，不输入密钥。业务服务与诊断实验使用不同会话，诊断不会覆盖业务连接文件。

## 业务日志持续留存

正常运行「Colab: 启动 GPU」即启用。旧配置未写这些字段时，也使用下面的默认值：

```json
"remote_logs": {
  "enabled": true,
  "path": "/content/drive/MyDrive/Manual2AR/logs",
  "interval_seconds": 15
}
```

首次需要授权挂载 Google Drive；即使关闭依赖缓存，开启远端日志仍需要挂载。日志采集在远端独立进程中进行，本地断网或退出监控后仍可继续，直到运行时结束、手动停止或采集达到 12 小时上限。采集不会执行 Notebook 保活、虚假推理或自动申请 GPU。

每次启动产生 `MyDrive/Manual2AR/logs/<运行目录>/<UTC时间-随机标识>/`，包含：

- `observations.jsonl`：每轮 UTC 时间、系统启动标识、内存、磁盘空间、GPU 显存和利用率、已注册子进程是否存在。
- `latest.json`：最近一次遥测。
- `logs/`：安装、服务、隧道、启动状态和推理事件日志的最近快照，每个文件最多约 256 KiB，较早文本可能被截去。
- `run.json`：观察开始时间、持续时长和间隔。
- `end.json`：采集器正常结束或收到可处理信号时的记录。SIGKILL、整机消失和 Drive 故障可能来不及写它。

不复制配置文件、连接令牌、原始图片、模型权重或整份工作目录。文本日志会脱敏。Drive 使用异步存储，可能丢失最后一个采集周期及尚未落盘的数据，不能保证在虚拟机突然删除时记录平台终止原因。

本地启动输出会显示留存目录，并保存到 `paths.runtime/colab/remote-retention.json`。远端 `retention-status.json: write_failed` 表示留存失败，不能把目录存在当成持续写入成功。Drive 断开后原本地日志仍在，但不会承诺自动恢复挂载。

## 无模型诊断入口

运行任务 **「Colab: 无模型诊断实验」**。它申请或复用 `manual2ar-diagnostics` 专用 T4，上传标准库诊断源码，挂载 Drive 并开始有限时长的遥测。不会安装/加载 SAM 或 Cutie，不开推理 HTTP 服务，不启动 cloudflared，不修改 `inference.connection.local.json`。

```json
"diagnostics": {
  "suite": "session_lifecycle",
  "session_name": "manual2ar-diagnostics",
  "duration_minutes": 30,
  "sample_seconds": 15
}
```

为了避免并发 GPU 配额冲突，首次创建诊断实例前应明确释放业务实例；任务不会替你停止业务。如果配置里没有这些字段，自动使用上述默认值。允许观察 1–120 分钟，采样间隔 5–300 秒。

本地终端定期报告远端留存状态。Ctrl+C 只停止本地等待，远端观察仍按设定时长运行；观察完成也不会自动释放 GPU。结束后运行 **「Colab: 释放诊断运行时」**，仅操作诊断别名。

也可以把 [Manual2AR_Diagnostics.ipynb](../deploy/colab/Manual2AR_Diagnostics.ipynb) 上传 Colab，选择 T4，修改顶部表单并 Run all。Notebook 和任务入口共用同一实现；单元返回后，后台采集才刚开始，Run all 不会等待全部观察时长。网页创建的运行时需要在网页断开并删除，CLI 不会接管不属于本项目诊断别名的实例。

## 如何对照和解释

使用同一账号、同类 GPU，在不同时间分别做：CLI 无模型观察、网页 Notebook 无模型观察、正常模型推理。记录每次分配时间、观察开始时间、是否有人在其他客户端手动断开；避免在诊断实例中同时运行其他任务。资源和额度会变化，单次对照不能证明因果。

- 无模型实例也消失：降低了“只有 SAM/Cutie 崩溃或显存压力才会导致中断”的可能性，但仍需检查平台记录与额度。
- 只有模型任务退出、实例仍存在：检查日志中的 OOM/异常及退出前内存。
- 本机服务正常但公网失败：优先查隧道、DNS、TLS。
- 实例直接消失：查看 Drive 最后记录；没有 `end.json` 不是平台强杀的充分证据。不能从遥测自动判定 Google 未公开的回收规则。

观察 GPU 利用率本身不产生 GPU 计算。本诊断不会用假负载把 GPU 持续占满；它用于排除模型因素，不保证保留会话。

## 增加其他诊断

`deploy/colab/diagnostics.py` 的 `SUITES` 是唯一诊断项注册表。新增处理函数并注册命名项，配置验证与 Notebook 下拉列表会读取该表；复用远端留存和独立会话入口。若新增独立源码文件，显式加入 `tools/build/colab_diagnostics.py` 的 `SOURCES` 白名单，不从配置加载任意 Python 路径。

修改后运行 `python -m tools.build.colab_diagnostics` 重新生成笔记本。Notebook 不含现场数据或密钥；它内嵌白名单诊断源码，未来的诊断也应保持此导出边界。
