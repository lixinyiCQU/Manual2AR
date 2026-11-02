# 分阶段目录迁移

工作树：`Manual2AR-Integrated`；分支：`lixin/integration-v1`；基线：`f48cdd3`。没有创建提交或暂存内容。三个模块的 V1 来源在 `integration/sources.json`，原工作树保持不变。

## 阶段与结果

1. **保存当前整合版**：迁移前快照包含已跟踪和未跟踪的有效源码，排除本地凭据及生成产物。外部目录 `Manual2AR-Data/archives/pre-layout-20261101T145444Z/` 保存 `source.zip`、源码哈希清单；提供恢复依据。
2. **分离应用和公共库**：Unity、业务后端、GPU 服务归入 apps；CPU 算法及共享协议独立成 packages，分别提供 src 布局和安装元数据。移除根目录旧包入口，所有 Python 导入已更新。
3. **归位教学资源**：任务包、部件知识、Prompt、官方参考图及证据归入 resources 并版本化。资源解析由配置注入，支持更换资料根目录；procedure、Prompt、引用和图片保持原始内容，目录索引单独更新。
4. **统一配置和外部数据**：私有配置迁入 configs 并保持忽略；原始 Wiki、运行证据、缓存、构建和归档放到项目外 Manual2AR-Data。迁移时为旧数据路径保留兼容符号链接；后续 Projects 顶层整理时，这三个旧别名目录已移入项目外归档，当前整合版直接使用 Manual2AR-Data。
5. **分离部署与开发工具**：GPU 算法位于 apps/inference，Colab/HPC/container 入口位于 deploy，构建/资源校验/静态实验位于 tools；Notebook 和独立 GPU ZIP 由同一份规范源码生成。
6. **回归与交付**：更新测试、README、资源同步和打包命令；执行 Python 回归、资源完整性与 Unity 四场景验证。生成物保存在项目外 builds/integrated。

## 主要映射

| 迁移前 | 迁移后 |
|---|---|
| `unity/Manual2AR` | `apps/unity/Manual2AR` |
| `application` | `apps/backend/src/manual2ar/application` |
| `learning`、`guidance`、`inspection` | `apps/backend/src/manual2ar/modules/*` |
| `vision` 中 CPU 算法 | `packages/perception/src/manual2ar_perception` |
| `vision` 中协议、身份及几何 | `packages/contracts/src/manual2ar_contracts` |
| `vision` 中 VLM、GPU 客户端 | 后端 `integrations` |
| `knowledge` 与离线阅读 | 后端 `knowledge` |
| `gpu` 算法和 HTTP 服务 | `apps/inference/src/manual2ar_inference` |
| `gpu` 环境安装/权重/Drive 缓存 | `deploy/common` 和 `deploy/colab` |
| `notebooks` | `deploy/colab/Manual2AR_GPU.ipynb` |
| `content` | `resources/{devices,tasks,modules,sources,samples}` |
| `application/config.local.json` | `configs/app.local.json` |
| `application/cutie.connection.local.json` | `configs/inference.connection.local.json` |
| 根目录依赖清单 | `apps/backend/requirements*`、各包 pyproject |

没有更换模型、视觉方法、对外 API 或三个模块的任务规则。GPU 的进程入口改用显式配置和工作目录；新部署应使用本次生成的 Notebook/源码包。

## 验证与限制

- 175 项 Python 检查通过：原有 166 项及新增 9 项迁移边界检查。覆盖模块隔离、GPU 真实 HTTP 协议配受控引擎、静态测试、Wiki 原文与离线浏览器渲染、资源注入、源码包一致性和私有配置隔离。
- 迁移前后逐字节核对：138 份教学资源、92 份 Unity 源文件完全一致。
- 资源校验通过：10 个逻辑资源、6 个教程变体，官方快照 archive SHA256 与清单一致。
- Unity 2022.3.34f1 四场景实际 Play 验证：静态识别、教程导航、分阶段检查、返回主页，运行时错误为 0。
- 未调用真实 VLM，未进行真实 SAM3.1/Cutie、实物摄像头、HPC 或容器部署验收。模型算法没有调整；自动测试不能证明现场识别质量。

验证截图、日志和成功报告在 `Manual2AR-Data/builds/integrated/validation/`。原始调试记录继续位于各原工作树或项目外档案中，没有复制回产品源码。

## 恢复方式

先另存迁移后的工作目录。将迁移前 `source.zip` 解压到新的空目录，按清单检查源码哈希；从当前 configs 私下复制本地配置到快照原来的 application 路径，或重建本地配置。切勿直接覆盖现有工作树或用 `git reset --hard` 丢弃尚未提交的整合代码。

迁移快照不含 API Key、GPU 令牌、Python 环境或原始 Wiki；这些独立资料需要按本地备份和配置恢复。旧配置如仍引用旧数据别名，需要改为 Manual2AR-Data 下的现行路径，或从项目外清理归档中恢复旧别名目录。

## Projects 顶层整理

当前仅保留 `Manual2AR-Li/`（代码、Git 主仓库及工作树）和 `Manual2AR-Data/`（项目外数据）。三个旧数据别名及三个练习目录完整移入 `/home/lixin/archives/projects-cleanup-20261101-232522`；恢复映射见该目录的 `manifest.json`。本次不移除任何 Git 工作树，不创建提交。
