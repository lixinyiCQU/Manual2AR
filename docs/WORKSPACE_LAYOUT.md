# 当前工作区与分支

2026-11-12：仅main和Dev。U7全部合并到Dev后，原分支和工作树已删除。当前开发、后续GitHub提交均使用Manual2AR-Dev。Git公共库在根.git-store，不能删除；main无单独工作目录。Dev用于独立验收，本次只发布该分支，不合入main。

根目录仅保留Manual2AR-Dev、Manual2AR-Data、References和README。Data保留原始实验、模型回复、人审标签、标定、Wiki和当前Windows程序；不上传源码Git。缓存集中于Data/cache，Dev的.venv为内部链接。

精简记录在Data/archives/slim-workspace-20261112：删除退休U7环境、pip/临时缓存、重复程序、旧UI截图与控制台日志；保留最新截图和结果JSON。旧归档剔除模型缓存、可从Git恢复的源码和与规范Wiki逐文件SHA相同的副本，独有资料仍保留。archive-compaction.json记录恢复commit和逐项原因。旧分支完整bundle仍在workspace-cleanup-20261112。

程序：Data/builds/dev/Manual2AR-Windows/启动后端.cmd，然后启动教学系统.cmd。更换硬件需要重新校准。本轮未重测相机/GPU/AR精度。
