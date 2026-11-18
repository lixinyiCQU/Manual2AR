# GitHub 私有开发副本

学长从私有仓库的独立 `Dev` 分支验收。2026-11-16 的交接记录使用 lixinyiCQU 的个人开发副本，协作者需先登录并接受邀请。[Dev 分支](https://github.com/lixinyiCQU/Manual2AR/tree/Dev)

## 分支与来源

- `main`：从 NibiruCommander/Manual2AR 克隆的原始基线，保留提交及作者历史，不并入本轮开发。
- `Dev`：U7-Pipeline 合并后的开发进度，包括目标定位、条件计划、现场核验、Unity 前端与交接文档。作为本库默认分支供验收。
- 11 月 16 日的上传目标为本机 `personal`，该远程指向个人私有仓库。`origin` 指向学长仓库。本次独立验收直接查看 `Dev`，如以后需要并入主分支，再另行评估迁移和 PR。

**2026-11-18 工作树状态。** 当天本机提交为 `fbc79c5`。新增的外挂料盘和 AMS lite 开箱照片 AR 仍包含未提交及未跟踪的源码、资产和测试。交付这项功能时，请将这些文件连同相应的 Unity `.meta` 一起纳入提交，记录交付提交号，并提供与其匹配的客户端。从 GitHub 检出该功能的前提是对应提交已上传。

后续提交开发进度时，在本机开发目录使用：

```bash
git switch Dev
git status
git add <本次修改的文件>
git commit -m "说明本次修改"
git push personal Dev
```

本机将默认推送远程设为 `personal`。这项 Git 配置不随克隆传播；其他人应按自己的权限和协作方式配置。

## 接手与运行

获得权限后克隆：

```bash
git clone --branch Dev https://github.com/lixinyiCQU/Manual2AR.git
cd Manual2AR
```

人从[独立分支验收](ACCEPTANCE.md)开始，里面给出了 U7 和两个开箱版本的验收路线。Agent 先读 [README_AGENT](../README_AGENT.md) 与 [AGENTS](../AGENTS.md)。

Git 保存已提交的源码、契约、任务定义、资产及其提交历史。完整离线演示还需通过团队渠道另收 Wiki、U7 历史照片以及与源码匹配的 Windows 程序，文件位置和配置方式见[独立分支验收](ACCEPTANCE.md)。账号凭据由接收者在本机配置。`Manual2AR-Data/` 与 `References/` 单独存放。

## 历史上传记录

11 月 16 日交接记录覆盖当时的已知凭据与 Git 文件大小检查。现行打包工具的已知风险见[仓库审计](REPOSITORY_AUDIT.md)。持有 11 月 12 日完整封存包的接收者可按[历史包恢复说明](HANDOFF.md)操作。
