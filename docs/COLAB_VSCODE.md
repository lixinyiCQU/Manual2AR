# VS Code 一键启动 Colab GPU

本入口运行在 WSL，使用固定版本的 Google 官方 CLI（0.7.5）管理本项目专用 Colab 会话。VS Code 提供任务按钮与日志，原来的网页 Notebook 保留。配置继续通过 JSON 文件编辑，日常无需手动上传、下载或移动连接文件。

## 第一次使用

1. 在 **VS Code 的 WSL 窗口**中打开仓库里的 `Manual2AR.code-workspace`，允许工作区任务运行。工作区应显示名为 Manual2AR 的文件夹。
2. 选择菜单 **终端 → 运行任务 → Colab: 初始化工具**。第一次会复制 `configs/colab.example.json` 为私有 `configs/colab.local.json`，并安装独立 CLI 环境。当前工作站已经完成此项。
3. 运行任务 **Colab: 登录 Google**。在终端提供的链接中登录，批准 Google 授权，将 Google 页面显示的授权码粘贴回同一个 VS Code 终端。不要发送到聊天或写入项目配置。
4. 运行 **Colab: 启动 GPU**。首次准备依赖与权重需要等待，终端显示阶段进度。
5. 看到 **6/6 GPU 就绪** 后，启动本地业务后端、在 Unity 开始新的识别。连接文件已经写入 `configs/app.local.json` 的 `gpu.connection_file` 所指定位置，默认 `configs/inference.connection.local.json`。

Windows Colab 扩展和 WSL CLI 不共享登录状态；扩展已登录仍可能需要第 3 步。CLI 会缓存 Google 授权，失效时重新执行登录任务。登录任务只查询运行时，不创建 GPU，也不读取浏览器 Cookie。

## 日常操作

| VS Code 任务 | 行为 |
|---|---|
| Colab: 启动 GPU | 刷新本项目会话；复用已有运行时或按配置申请 GPU；上传当前推理源码，后台准备环境、预加载 Cutie，建立连接并安装通过校验的连接文件 |
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
| `public_url` | 默认留空，启动临时 HTTPS 连接；已有可访问服务地址时可填写 |
| `inference` | Cutie 精度、内部尺寸和记忆间隔等性能设置；模型选择与推理协议保持不变 |
| `drive_cache.enabled` | 默认 false，首次使用无需挂载 Drive；设为 true 可跨运行时复用模型、依赖缓存，启动时可能需要额外授权 |
| `drive_cache.path` | Drive 缓存目录；必须在 `/content/drive/MyDrive` 内 |

同一个运行时重复启动会尝试复用已经准备的环境。跨运行时缓存只有开启 Drive 并成功授权挂载后才生效；默认不会保存现场图像到 Drive。

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
bash run.sh colab-status
bash run.sh colab-logs
bash run.sh colab-stop-service
bash run.sh colab-release
```

免费 Colab 的 GPU 分配、最长运行时间及回收由平台决定，启动器不模拟保活、不规避额度限制。该入口用于交互实验，不能承诺长期服务可用性。

官方参考：[Colab CLI](https://github.com/googlecolab/google-colab-cli)、[VS Code Colab 指南](https://github.com/googlecolab/colab-vscode/wiki/User-Guide)、[Colab 使用限制](https://research.google.com/colaboratory/faq.html)。

## 当前验收范围

2026-11-02 修复 Drive 缓存恢复：按已锁定的推理依赖逐项离线安装，不再重新解析 Cutie 中未使用的训练依赖；配置原子替换，日志在启动子进程前捕获待脱敏凭据，避免配置写入期间的 JSON 读取错误终止安装。相关部署测试 50 项通过，完整回归 225 项通过。Notebook 和推理源码包已同步更新；远端是否就绪以启动任务的 `6/6` 及健康检查为准。

修复版本已在现有 T4 完成真实启动，返回 `6/6 GPU 就绪` 并更新本地连接。远端 94 个锁定依赖通过 `pip --dry-run --ignore-installed --no-index --no-deps` 验证，无需获取额外训练依赖。尚未以全新运行时完整复测跨 VM 的缓存恢复，也未在此次修复中操作 Unity 进行画面验收。

本地最近一次完整回归为 219 项通过。官方 CLI 已实际安装，命令参数、缺少授权时退出、失败保留连接、远端失败日志留存和错误分类均已检查。

2026-11-02：用户已完成授权并实际到达源码上传与远端环境准备阶段，但环境准备失败。排查时原运行时已失效，无法恢复当时的远端安装日志；两次重新申请 T4 均收到分配接口 `503 Service Unavailable`，因此尚未完成真实 GPU 服务启动、Drive 挂载和公网推理验收。不能据此推断原环境失败是哪个依赖造成的。

现在环境准备失败会自动收集远端日志到 `paths.runtime/colab/remote-*`，并在终端显示经过脱敏的错误摘要；全部日志无法下载时会明确报错。运行时失效后已有本地日志保留。遇到 GPU 分配 503，稍后重新运行「Colab: 启动 GPU」即可，无需反复登录或手动改换 GPU；准备失败时先查看终端中的实际依赖错误。原连接文件仅在新服务健康检查通过后才更新。
