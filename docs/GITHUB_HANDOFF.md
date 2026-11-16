# GitHub 私有开发副本

仓库：[lixinyiCQU/Manual2AR](https://github.com/lixinyiCQU/Manual2AR)。当前开发与验收入口：[Dev 分支](https://github.com/lixinyiCQU/Manual2AR/tree/Dev)。

此库属于 lixinyiCQU 的个人私有仓库，通过协作者邀请向 NibiruCommander 开放。被邀请账号需要先登录并接受邀请，再访问仓库；个人私有仓库的协作者具有读写权限。

## 分支与来源

- `main`：从 NibiruCommander/Manual2AR 克隆的原始基线，保留提交及作者历史，不并入本轮开发。
- `Dev`：U7-Pipeline 合并后的开发进度，包括目标定位、条件计划、现场核验、Unity 前端与交接文档。作为本库默认分支供验收。
- 本机 `origin` 继续指向学长仓库，`personal` 指向自己的私有仓库。本次仅向 `personal` 上传，没有向学长仓库推送、合并或创建 PR。

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

人先读 [验收入口](ACCEPTANCE.md) 和 [交接说明](HANDOFF.md)，Agent 先读 [README_AGENT](../README_AGENT.md) 与 [AGENTS](../AGENTS.md)。U7 演示路线见 [U7 Demo](../baseline/U7_DEMO.md)。

Git 保存源码、契约、审核后的任务定义、受版本控制的资产及这些分支可达的历史；不会自动上传工作区旁的 `Manual2AR-Data/`、`References/`，也不包含被忽略的本机凭据、运行缓存或生成的 Windows 程序。完整离线运行仍需另外接收资料与资源包，按交接说明重定位配置。不要将本机配置或 API 密钥加入 Git。

## 本次上传检查

上传前检查了本机已知凭据是否出现在当前源码及 Git 历史，并检查 GitHub 文件大小上限。该检查不等于针对所有未知或已撤销凭据的完整历史安全审计。上传不修改本地冻结实验、人工标签或标定。
