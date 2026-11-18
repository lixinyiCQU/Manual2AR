# 2026-11-12 封存包恢复说明

**使用范围。** 已收到完整 `Manual2AR-Handoff-20261112/` 的接收者，可以按下文验包和恢复。下文的分支名、目录、实验结果和命令都对应封存时的副本。

验收现行 `Dev` 请从[独立分支验收](ACCEPTANCE.md)开始。2026-11-18 查到旧打包工具的私有配置排除规则、缓存链接处理和恢复时的程序路径均与现工作区有出入。新建交接包要先修正这些问题并验证创建与恢复全流程。详情见[当前仓库审计](REPOSITORY_AUDIT.md)。

## 接收者先看什么

人先看本说明，再看源码 `baseline/U7_DEMO.md`；Agent先看包根 `AGENT_HANDOFF.md`，进入源码后读 `README_AGENT.md` 与 `AGENTS.md`。研究方向见 `References/Manual2AR_研究蓝图_v0.1.md`，师兄原蓝图保存在 `legacy-docs/research_blueprint_v0_2.md`。原包内的审计记录位于其源码 `docs/HANDOFF_AUDIT.md`。现行工作树可查阅[同一历史记录](history/HANDOFF_AUDIT.md)。

当前模块二同时保留U7问答拍照Demo，以及开箱、首次打印、进料、退料教材；自动编译与人工审核研究代码保留。默认稳定演示无需模型密钥；实时视觉需要另配。U7动画是照片上的示意，不能当作实机定位精度证明。

## 一个文件夹里有什么

```text
Manual2AR-Handoff-20261112/
  README_交接.md / AGENT_HANDOFF.md
  handoff.py                         验包、移机配置、生成启动副本
  workspace/Manual2AR-U7-Pipeline/   独立.git、当前源码、资源、测试、文档
  Manual2AR-Data/
    sources/                         离线Wiki和第三方来源/许可
    runs/                            原始照片、模型回复、实验、人审、标定
    cache/                           保留的资料缓存
    assets/                          编辑资产及其版本
    builds/                          所有保留的历史构建与验证截图
    archives/                        历史源码和迁移材料
  References/                        论文、蓝图、架构图、演示视频
  legacy-docs/                       师兄原蓝图
  history/                           原状态/refs/补丁、完整Git bundle
  manifests/                         文件SHA256、排除清单、交接提交等
```

此包不依赖原归档仓库的 `.git`。原工作树及所有原分支不被本次打包提交或重置；交接副本在 `handoff/u7-20261112` 有一个本地提交，包含此前未提交和未跟踪的开发成果以及本轮整理。完整HEAD读 `manifests/handoff.json`。所有原分支、标签和其他refs仍保留；`history/all-history.bundle`可独立恢复历史。

只排除凭据和可重建的机器环境：本机配置、旧私有配置、Colab会话令牌、Python/Colab虚拟环境、Python字节码、Unity Library/Temp等。逐项路径和原因在 `manifests/omissions.json`。不带本机密钥，不改原密钥文件；接收方另配。已有资料缓存、原始失败和人工审核都保留，旧源码版本由Git和归档恢复，不再重复打包同级所有旧工作树。

## 换电脑怎么运行

整体复制本文件夹，保留相对结构，后端源码建议放WSL文件系统。先不要运行Git命令、安装或编辑文件，执行一次完整验包：

```bash
cd /你的路径/Manual2AR-Handoff-20261112
python3 handoff.py verify .
python3 handoff.py configure .
cd workspace/Manual2AR-U7-Pipeline
bash run.sh setup
bash run.sh resources
bash run.sh sync
```

需先有Python3.12与venv支持。setup从锁文件安装依赖及Chromium，需要网络；虚拟环境不能跨机器直接使用。configure生成0600权限、无API密钥、本地8011端口的配置，默认拒绝覆盖已有配置。手工修改只动 `configs/app.local.json`。稳定Demo不需要GPU。云端模型权重、远端GPU环境和连接令牌不随包，需按deploy脚本重新部署或从团队已有云缓存恢复；Unity编辑器也需接收方自行安装。

随后在包根目录生成单独的本机启动副本：

```bash
cd ../..
python3 handoff.py launcher .
```

工具复用现有构建校验及启动器导出函数，重新计算当前后端修订，把本机启动文件放 `Launch/Manual2AR-Windows/`。原 `Manual2AR-Data/builds/` 内的旧启动描述、构建证明、程序与哈希保持原样；`Launch/`中的 `migration.json`说明只是重定位启动器，前端沿用已有验证程序。如果输入指纹不匹配则拒绝，必须重新验证构建，不能改证明绕过。

Windows中先运行 `Launch/Manual2AR-Windows/启动后端.cmd`，保持终端打开，再运行同目录 `启动教学系统.cmd`。也可在WSL源码内手动 `bash run.sh start`，然后启动前端。健康地址为 `http://127.0.0.1:8011/health`。后端已被其他工作树占用时，先辨认归属，不要自动杀进程。

配置/安装/Git工作会改变交接清单中的部分文件；清单用于收到原包时验真，不用于强制把后续开发还原。`Launch/`为后生成内容，不属于原封存包。launcher若失败会保留该输出供诊断；移走自己的失败输出后再生成。

## 三分钟演示

进入操作指导→提问及拍摄现场生成AR指导。保留默认历史照片模式，输入“安装料盘支架”，选“底座已装，支架待滑入”，生成计划；查看官方两步与当前视觉结果，集中勾选底座方向和紧固确认，再看滑入支架动画。切换已装支架照片核验，确认方向后完成。

“安装支架底座”只规划底座；“滑入料盘支架”仍需核实底座依赖；“安装料盘底座及滑入料盘支架”对应两个最细操作。新会话直接选已装支架时，底座被挡仍需证据，不能强行放行。官方步骤可在生成前打开。相机启动只预览，照片核验要用户点击。

实时模式不保证识别结果。历史照片预设是已标明的演示脚本，不是原VLM输出，也不算视觉准确率；所有Demo记录均排除研究评价。

## 实验和数据怎么接手

正式评价为 `Manual2AR-Data/runs/baseline/transfer-20261111-v1/`，固定18次排程、12次编译、7份契约通过、2份U7可接AR；不能把7/12说成识别准确率。原manifest登记389个文件，验包工具另用固定manifest/plan的SHA复核，不能仅靠一份可被重新生成的新清单。

人工标签的当前版本在 `runs/u7-pipeline/baseline-review/transfer-20261111-v1/current.json`，有独立history/exports。以当前文件为准，不用旧报告中的“待评价”覆盖它，不替用户审核。历史真实照片、失败回复、原始调用、代码快照、标定、各轮报告均保留。

运行目录恢复不等于内存会话恢复；换后端后新建教学会话。保留的标定只适用于原相机、画幅和场景，移机后须重新确认。历史证据中的原机绝对路径是出处，禁止全目录查找替换。

## 封存副本的分支与历史

在独立源码仓库查看状态与交接分支：

```bash
cd workspace/Manual2AR-U7-Pipeline
git status
git log -5 --oneline
git switch -c agent/你的任务
```

原交接副本的分支是 `handoff/u7-20261112`。源码 Git 包含源码及受版本控制的资源，外部 Data 与 References 在包中单独存放。团队当前使用独立 `Dev` 分支交付源码，见[GitHub 交接说明](GITHUB_HANDOFF.md)。

原包为需要另存该历史分支的接收者保留了以下命令。恢复与验包均可在本地完成。

```bash
git remote add handoff-target https://github.com/你的组织/你的仓库.git
git push handoff-target handoff/u7-20261112
```

仅剩bundle时可 `git clone -b handoff/u7-20261112 history/all-history.bundle recovered`，但忽略的生成资产、外部实验与缓存仍须从完整包恢复，不能只留bundle。

## 验证与已知限制

本轮日志在 `Manual2AR-Data/runs/u7-pipeline/handoff-20261112-v1/`，审计见 `docs/HANDOFF_AUDIT.md`。Python完整验证同时包括 `tests/` 和 `baseline/tests/`；资源校验、独立Git检查、文件清单及冻结389项核对另行记录。此前Unity四场景通过的证据在 `builds/u7-pipeline/validation-spatial-20261112-160037/`，本轮未改C#、未声称重编译前端。

已修复存储失败不释放busy/进度先于记录提交、验证器误覆盖既有Unity工程，并提供本机路径重定位工具。仍待后续处理：异常退出遗留Demo会话（最多64）、离线文章首次渲染失败后需修好环境并重启自己的后端。API按本地单用户使用；不承诺公网安全、多进程隔离、真实相机、GPU在线、真实模型质量或实机AR精度。
