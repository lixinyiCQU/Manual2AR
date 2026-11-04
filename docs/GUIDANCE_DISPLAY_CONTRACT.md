# U7 画面显示契约

配置：`resources/tasks/bambu_a1_mini/unboxing/spatial/v1/display.json`。
校验：`packages/contracts/src/manual2ar_contracts/guidance_display.py`。
后端组合：`apps/backend/src/manual2ar/modules/guidance/spatial/display.py`。

没有可显示的空间提示时隐藏图例，进入场景或仅启动相机不预先展示模型清单。指导就绪后，画面仅保留固定图例和一条随操作目标锚定的祈使句。检测、分割、代理模型、动画及核验规则保持原有职责。核验结果和运行状态放在画面外的面板。

## 字段

- `schema_version`：`manual2ar-guidance-display-v1`。
- `action_id`：已登记动作，当前为 `holder.base` 或 `holder.slide`。
- `source`：`authored` 或 `agent`；当前使用人工配置，没有接入 Agent。
- `legend`：1–6 个固定条目。模型条目绑定已登记的 `asset_id`，复用真实教学模型的固定视角缩略图；高亮条目绑定 `component_id` 和 RGB 色块。名称不随目标移动。`color` 统一定义图例名称及指令中的组件颜色，`terms` 为需着色的短名称；匹配采用最长词优先，不接受自带富文本。
- `instruction`：`adverbial`（位置或对准关系）、`actor_mode`（工具或移动部件）、`actor`、`action`、`object`、`acceptance`。统一组句为“状语，用工具／将部件执行动作，达到验收要求。”
- `instruction.position_m`：服务端根据已有标定作用点填入，单位米。没有可靠空间位置时不显示锚定文字；不根据 VLM 二维框猜测深度。

底座：“在支架底座上，用内六角扳手拧紧两颗底座螺丝，使底座贴合并固定。”

支架：“对准底座导槽，将料盘支架滑入支架底座，直至滑到底部。”

验收要求是用户操作目标，不表示系统已经检测通过，也不表示测得了扭矩。

## 后续 Agent 接入

Agent 生成语义字段及已有资产 ID，提交前通过 `GuidanceDisplay` 和 `DisplayCatalog` 校验。未知资产、重复图例、额外字段、富文本、非有限坐标及不符合组句规则的文本会被拒绝。空间坐标继续由已标定链路提供。前端不接收任意 UI 指令或自动生成的可执行代码。

Unity 的固定图例、Windows 投影文字与原生 AR World Space 文字共用此契约。当前只配置 U7，其他章节沿用已有显示方式。

## 核验和跟踪的独立生命周期

“检查安装”只请求可见安装状态核验，不取消现有分割跟踪。未完成、看不清或服务错误均在右侧反馈，不清空仍可用的跟踪。

重新识别在后台建立候选任务；原跟踪继续使用原任务及同帧身份检查。候选分割可用后再替换；候选失败只清理候选。切换章节、画幅、退出或重设空间位置仍明确终止旧跟踪。真正跟踪丢失不会用静止旧掩码冒充实时结果。
