# 安装料盘支架：GT 规范化审核

来源已确认不等于本次细分和证据渠道已审核。当前包仅为待审核任务 GT，不是可执行视觉标准或现场标签。

## 操作节点

- **install_base**：使用两颗 M3-8 螺丝安装料盘支架底座，注意官方安装方向；机械紧固须人工确认。
  - 依赖：无；完成条件：c.base.mount, c.base.screws, c.base.appearance, c.base.direction, c.base.secure
- **install_holder**：从上向下滑入料盘支架，确保方向与插槽匹配。
  - 依赖：install_base；完成条件：c.holder.connection, c.holder.appearance, c.holder.direction

## 条件及来源

### c.base.mount：底座位于立柱指定安装区域并贴靠安装面。

渠道：`vision`；定义状态：`needs_visual_standard`；依据：`direct_reference`。

只核验当前可见安装关系；遮挡或无法区分贴靠与悬空时保持未知。具体区域和特征标准留待视觉阶段定义。

- [r.base.mount] 灰色底座已贴靠在立柱正确安装区域（reference_verification / reference.base）
- [r.chapter.outcome] 料盘支架底座与安装面贴合，支架已沿匹配插槽滑入，无明显倾斜。（reference_context / reference.chapter）

### c.base.screws：上下两颗固定螺丝均可见且处于各自对应安装孔位。

渠道：`vision`；定义状态：`needs_visual_standard`；依据：`direct_reference`。

保留原 GT 的联合检查：必须同时确认上下两颗不同螺丝均在对应孔位。只见一颗、重复同一实例或孔位空缺都不能满足；不可见时未知。具体区域与视觉标准留待定义。

- [r.base.quantity] 2 颗（official / official.base）
- [r.base.screws] 上下两颗固定螺丝均可见且处于安装孔位（reference_verification / reference.base）

### c.base.appearance：底座无明显缺件、脱离或倾斜。

渠道：`vision`；定义状态：`needs_visual_standard`；依据：`direct_reference`。

这是外观条件，不证明紧固；明显倾斜的判断标准尚待定义，不设置臆测角度。

- [r.base.appearance] 未见明显缺件、脱离或倾斜。（reference_verification / reference.base）

### c.base.direction：底座安装方向符合官方要求。

渠道：`unresolved`；定义状态：`unresolved`；依据：`direct_reference`。

原要求保留；尚无已审核的辨向特征、指定视角或渠道，不自动转换为二维上下关系或人工确认。

- [r.base.direction] 请注意安装方向。（official / official.base）

### c.base.secure：用户已按官方说明确认底座机械紧固。

渠道：`manual`；定义状态：`manual_definition`；依据：`direct_reference`。

逐项人工确认当前底座机械紧固；不从可见螺丝推断松紧，不添加官方未给出的扭矩。用户最初的完成声明不是此确认。

- [r.base.secure] 用户仍需按官方步骤人工确认机械紧固。（reference_verification / reference.base）

### c.holder.connection：支架安装端与底座区域有清楚可见的外部连接。

渠道：`vision`；定义状态：`needs_visual_standard`；依据：`direct_reference`。

仅核验可见最终连接，无法区分连接和靠在一起时未知；不要求看到被正常遮挡的底座螺丝，不证明隐藏锁止。

- [r.holder.connection] 安装端与打印机立柱的底座区域有清楚可见的连接（reference_verification / reference.holder）
- [r.chapter.outcome] 料盘支架底座与安装面贴合，支架已沿匹配插槽滑入，无明显倾斜。（reference_context / reference.chapter）

### c.holder.appearance：支架无明显脱离或大幅倾斜。

渠道：`vision`；定义状态：`needs_visual_standard`；依据：`direct_reference`。

保留原外观要求；大幅倾斜的可观察标准尚待审核，不臆造角度容差。

- [r.holder.appearance] 且无明显脱离或大幅倾斜。（reference_verification / reference.holder）
- [r.chapter.outcome] 料盘支架底座与安装面贴合，支架已沿匹配插槽滑入，无明显倾斜。（reference_context / reference.chapter）

### c.holder.direction：支架方向与底座插槽方向匹配。

渠道：`unresolved`；定义状态：`unresolved`；依据：`direct_reference`。

保留官方方向要求；具体接口特征与判定渠道待定义，静态图不证明从上向下滑入的历史动作。

- [r.holder.direction] 请确保料盘支架方向与插槽方向相匹配。（official / official.holder）

## 逐项来源覆盖

- r.base.install：来安装料盘支架底座 → install_base
- r.base.quantity：2 颗 → c.base.screws
- r.base.specification：M3-8 → install_base
- r.base.direction：请注意安装方向。 → c.base.direction
- r.holder.slide：从上向下滑入料盘支架。 → install_holder
- r.holder.direction：请确保料盘支架方向与插槽方向相匹配。 → c.holder.direction
- r.optional：如果您计划使用 AMS lite，您可以选择性地安装料盘支架，而不是一定需要安装。 → 任务适用范围/观察边界
- r.base.mount：灰色底座已贴靠在立柱正确安装区域 → c.base.mount
- r.base.screws：上下两颗固定螺丝均可见且处于安装孔位 → c.base.screws
- r.base.appearance：未见明显缺件、脱离或倾斜。 → c.base.appearance
- r.base.secure：用户仍需按官方步骤人工确认机械紧固。 → c.base.secure
- r.base.boundary：只检查可见安装状态，不判断扭矩、螺丝是否真正拧紧、隐藏卡扣或内部结构。 → 任务适用范围/观察边界
- r.holder.connection：安装端与打印机立柱的底座区域有清楚可见的连接 → c.holder.connection
- r.holder.appearance：且无明显脱离或大幅倾斜。 → c.holder.appearance
- r.holder.occlusion：底座会被装好的支架遮住，不要求看见底座螺丝、隐藏插槽、卡扣或细微缝隙。 → 任务适用范围/观察边界
- r.holder.boundary：结论仅限可见安装状态，不表示机械锁紧或安全放行。 → 任务适用范围/观察边界
- r.base.reference_instruction：使用两颗 M3-8 螺丝固定料盘支架底座，注意官方图示方向。画面同时提示两颗螺丝的位置；紧固程度请按官方说明人工确认。 → install_base
- r.holder.reference_instruction：从上向下滑入料盘支架，确保方向与插槽匹配。 → install_holder
- r.chapter.outcome：料盘支架底座与安装面贴合，支架已沿匹配插槽滑入，无明显倾斜。 → c.base.mount, c.holder.connection, c.holder.appearance

## 请审核

### review.orientation

底座正确方向、支架与插槽方向匹配，分别依据哪些可辨识特征和视角？

当前提案：暂保留 unresolved，不删掉方向要求、不把三维方向简化成图像上下、不自动转人工。请指定特征或明确可采用的人工渠道。

### review.occluded_prerequisite

初始照片中支架已经安装并遮挡底座螺丝时，完整任务应如何核实底座前置条件？

当前提案：保留底座未知与支架可见连接两个事实，不凭后者推断前者；待审核多视角补拍或其他明确证据策略，不要求为了核验而自动拆下支架。
