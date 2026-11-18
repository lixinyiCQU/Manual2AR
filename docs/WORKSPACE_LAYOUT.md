# 当前工作区与分支

日常开发在 `Manual2AR-Dev/`。本机保留 `main` 和 `Dev`，共享 Git 库在工作区根目录 `.git-store/`。`main` 保留原始基线，Dev 用于独立验收。原 U7 分支的提交已并入 Dev，原工作树已移除。[当前交付范围](ACCEPTANCE.md)

根目录仅保留Manual2AR-Dev、Manual2AR-Data、References和README。Data保留原始实验、模型回复、人审标签、标定、Wiki和当前Windows程序；不上传源码Git。缓存集中于Data/cache，Dev的.venv为内部链接。

精简记录在Data/archives/slim-workspace-20261112：删除退休U7环境、pip/临时缓存、重复程序、旧UI截图与控制台日志；保留最新截图和结果JSON。旧归档剔除模型缓存、可从Git恢复的源码和与规范Wiki逐文件SHA相同的副本，独有资料仍保留。archive-compaction.json记录恢复commit和逐项原因。旧分支完整bundle仍在workspace-cleanup-20261112。

程序：Data/builds/dev/Manual2AR-Windows/启动后端.cmd，然后启动教学系统.cmd。更换硬件需要重新校准。本轮未重测相机/GPU/AR精度。
