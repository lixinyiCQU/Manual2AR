# 当前工作区与分支

2026-11-12：仅本地整理，没有fetch、push或远程合并。Dev已合并lixin/u7-end-to-end；保留main、Dev和该U7分支。主开发目录是Manual2AR-Dev。Git公共库在工作区根.git-store，不能删除；main无需单独工作树。

所有本地项目数据/缓存/构建在../Manual2AR-Data，Python环境也在该目录cache下，源码.venv为内部链接。不要将Data上传GitHub。公开模板路径已改为工作区内数据目录。本机Dev与Pipeline使用各自runtime/cache/builds；目前都用8011端口，只运行一个。

旧分支完整bundle、已退役工作树的源码/资源/实验归档、旧配置及清理记录在Data/archives/workspace-cleanup-20261112。含私密配置，禁止上传。原始冻结实验与人审文件不重写。根README给出当前入口，历史交接说明中的旧目录/未提交状态仅供追溯。

当前程序启动位置：Data/builds/dev/Manual2AR-Windows/启动教学系统.cmd；先启动同目录的启动后端.cmd。本轮仅核对复用原前端构建，不宣称真实相机/GPU/AR精度通过。后续上传仅在明确授权后推送Dev，不自动推送main和其他历史。
