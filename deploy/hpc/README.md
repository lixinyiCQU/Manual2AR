# SSH / 学校 HPC

本目录沿用同一份 SAM3.1 + Cutie HTTP 服务，不维护模型副本。先在本地运行 `bash run.sh inference-bundle`，把生成的 ZIP 传到已获分配的 GPU 节点，解压并进入其目录。集群如何申请 GPU、安装网络与 SSH 跳板遵循学校提供的方式；本项目未预设调度器。

准备一个 Python 3.12 环境并设置 `MANUAL2AR_GPU_PYTHON` 指向其解释器，运行 `bash deploy/hpc/run.sh prepare`。该步骤会联网安装固定依赖、拉取固定提交和下载模型，生成私有 `configs/inference.local.json`。后续只运行 `bash deploy/hpc/run.sh serve`；服务启动不重复安装模型。

参数全部在该 JSON 内编辑。通过 SSH 转发时，将 `host` 改为 `127.0.0.1`。建立本地端口转发，例如学校允许直接连接计算节点时：

```bash
ssh -N -L 8021:127.0.0.1:8021 username@gpu-node
```

连接需要跳板时按学校 SSH 配置调整。该隧道必须与推理服务连接到同一个计算节点。集群禁止计算节点出网时，依赖与权重需通过学校允许的镜像或离线方式预先准备；prepare 不会自动绕过这些限制。

在 GPU 节点导出连接文件：

```bash
python -m deploy.common.launch connection --config configs/inference.local.json --work-dir . --public-url http://127.0.0.1:8021 --output configs/inference.connection.local.json
```

把连接文件下载到本地仓库同名位置，后端配置无需更换供应商。该文件包含令牌，仅保存在本地，不提交 Git。此入口已做命令与导出验证，尚未在学校 HPC 执行模型部署。
