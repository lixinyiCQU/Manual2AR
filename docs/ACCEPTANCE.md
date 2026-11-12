# Dev 独立分支验收

本分支保存当前完整开发成果，供学长运行和验收；目录结构以本分支为准，暂不合入主分支，不要求主分支立即采用这套架构。

## 代码与运行资料

Git 分支包含后端、Unity 工程、独立任务核心、已审核 U7 定义、运行用 AR 资产、教材、配置模板及测试。离线 Wiki、现场照片、实验记录、缓存和 Windows 程序在源码旁的 `Manual2AR-Data/`，通过内部文件传输另行提供，不上传源码分支。仅克隆 Git 分支还不能复现默认历史照片演示。

验收的最小目录布局：

```text
Manual2AR-Li/
  Manual2AR-Dev/               克隆本分支
  Manual2AR-Data/
    sources/bambu-wiki/        完整官方离线资料目录，保留 objects 与 runs 层级
    runs/dev/u7-demo/assets-v1/ 两张历史照片和 manifest.json
    builds/dev/Manual2AR-Windows/ 已验证的 Windows 程序；用 Unity 编辑器时可不提供
```

需要复查研究结果时，另提供 `runs/baseline/`、原实验所在的 `runs/u7-pipeline/` 及当前人审记录；这些不是默认演示的验收前提。数据目录内的私有配置和账号会话不作为共享材料，接收者使用自己的凭据。

## 新机器启动

前提：Python 3.12 与 venv 支持；Windows 客户端连接 WSL/Linux 后端。使用编辑器需 Unity 2022.3.34f1。安装 Python 依赖和 Chromium 需要网络。

1. 克隆仓库的 `Dev` 分支到 `Manual2AR-Dev/`，将另行提供的资料放到相邻的 `Manual2AR-Data/`。
2. 在源码内复制 `configs/app.example.json` 为 `configs/app.local.json`。设置 `backend.host` 为 `127.0.0.1`、`backend.port` 为 `8011`、`backend.public_url` 为 `http://127.0.0.1:8011`；将 `paths.runtime/builds/cache` 分别设为 `../Manual2AR-Data/runs/dev`、`../Manual2AR-Data/builds/dev`、`../Manual2AR-Data/cache/dev`。Wiki 路径保留模板中的相对结构。默认历史照片演示的 `vlm.api_key` 可以留空，GPU 连接可不配置。
3. 执行：

```bash
bash run.sh setup
bash run.sh resources
bash run.sh sync
bash run.sh start
```

4. 后端终端保持打开，检查 `http://127.0.0.1:8011/health`。Windows 从完整程序目录运行 `启动教学系统.cmd`。此时后端已手动启动，不使用旧程序包中绑定原机器路径的 `启动后端.cmd`。可替代为在 Unity 打开 `apps/unity/Manual2AR`，运行 `Welcome` 场景。

本地已有的 `.git-store/` 和 `.venv` 链接属于开发机布局；从 GitHub 新克隆时使用普通 `.git/`，无需复制这些链接，也不需要重建原关联工作树。

## 三分钟验收

进入“操作指导”，应看到 U7 问答拍照入口，以及开箱、首次打印、进料、退料教材。U7 使用默认“历史照片演示（预设）”：

1. 输入“安装料盘支架”，选择“底座已装，支架待滑入”，点击生成。
2. 查看官方两步和现场结果，在同一窗口明确勾选底座方向与紧固条件。
3. 播放支架滑入动画，切换到已装支架照片核验，确认方向后完成。
4. 单独输入“安装支架底座”，应在底座完成后结束；“滑入料盘支架”应先核实底座依赖。
5. 新会话直接选择已装支架照片，底座被遮挡应提示证据不足；官方步骤在生成计划前也应可查看。

完整问法、反例与交互见 [U7 演示说明](../baseline/U7_DEMO.md)。预设观察明确标为演示，不计入模型识别或研究成功率；动画是照片平面示意，不代表完成实机配准。实时模型模式需要自己的凭据，可能误认或返回未知；物理相机、GPU与 AR 精度尚未完成联合验收。

## 验证与反馈

现有受控回归与数据完整性记录见 [交接审计](HANDOFF_AUDIT.md)、[当前布局](WORKSPACE_LAYOUT.md)及另行提供的数据目录报告。需要重跑核心与宿主检查可执行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest tests baseline/tests -q -p no:cacheprovider
```

先按本分支验证运行与功能，再决定是否对主分支发起架构迁移 PR。提出反馈时记录所用提交、问题、照片模式和操作阶段；不要将预设演示当成真实视觉准确率。
