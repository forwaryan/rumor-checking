# Cluster-E / Experience Shell

## 这个子 task 是干什么的

这个工作包负责单页 Web Demo 的全部界面和交互层，是用户真正看到的系统外壳。

## 为什么要有这个子 task

即使后端逻辑完成，如果没有一个清晰的单页工作台，传播链、claim、evidence、风险提示就不能被直观展示，V1 的演示价值会大幅下降。

## 为什么这个子 task 可以并行

前端可以先基于 mock `Report` payload 独立开发，不必等真实后端全部完成。只要共享 schema 明确，前端就能和后端、检索、测试同时推进。

## 当前实现记录

- 详细实现总结：`frontend/IMPLEMENTATION_SUMMARY.md`
- 逐文件记录：`frontend/FILE_RECORD.md`
- 当前状态说明：`E1` 到 `E8` 已完成，页面已进入“真实 analyze 优先，本地 payload 兜底”的可运行状态。

## 详细子任务

### E1 初始化 Next.js 项目骨架
状态：已完成
目标：创建前端项目结构、页面入口、基础样式和运行脚本。
产出：可运行的前端单页壳。
前置依赖：无。
子子任务清单：
- 初始化 Next.js 与 TypeScript 项目。
- 建立单页入口和基础布局文件。
- 确保本地可以启动前端页面。
实现备注：`frontend/` 已具备完整 Next.js 工程结构、运行脚本和全局样式。

### E2 定义前端类型与 API client
状态：已完成
目标：根据共享 schema 固定前端类型，并建立调用后端的 API client。
产出：前端类型层和请求层。
前置依赖：schema 初版可用。
子子任务清单：
- 根据 `Report` schema 定义前端类型。
- 封装 analyze、health、demo 等 API 调用。
- 处理请求异常和基础返回解析。
实现备注：前端已对齐真实 `GET /api/v1/health` 和 `POST /api/v1/analyze`；本地 demo 读取留在页面层，不再假设后端存在 `demo-cases / replay`。

### E3 实现输入区与提交状态
状态：已完成
目标：支持文本、URL、问题输入，并展示 loading、error 等状态。
产出：`InputPanel + StatusBanner`。
前置依赖：E1、E2。
子子任务清单：
- 实现输入框、示例按钮和提交按钮。
- 实现提交中、失败、重试等状态展示。
- 接好基础提交事件和前端校验。
实现备注：输入校验、提交、重试、错误提示和 fallback 提示均已接通。

### E4 实现事件概览与结论区
状态：已完成
目标：展示事件摘要、一句话结论、当前模式和风险概览。
产出：`EventCard + RiskPanel`。
前置依赖：E2。
子子任务清单：
- 渲染事件标题、摘要和来源信息。
- 渲染一句话结论和当前模式标识。
- 渲染风险提示与边界说明区域。
实现备注：事件概览、风险列表、统计信息和模式边界都已落地。

### E5 实现时间线面板
状态：已完成
目标：展示完整模式和部分模式下的时间线节点。
产出：`TimelinePanel`。
前置依赖：E2、mock payload。
子子任务清单：
- 设计时间线节点卡片或列表样式。
- 支持节点类型标签和时间排序展示。
- 处理无时间线或部分时间线的空态。
实现备注：当前已支持排序、空态和节点类型展示。

### E6 实现 claim 表与证据列表
状态：已完成
目标：展示 claim、claim_type、verdict、confidence 和 evidence 列表。
产出：`ClaimTable + EvidenceList`。
前置依赖：E2、mock payload。
子子任务清单：
- 渲染 claim 表格或卡片结构。
- 展示 claim_type、verdict、confidence 和 notes。
- 渲染 evidence 列表及来源信息。
实现备注：当前已支持 claim 表与证据聚合列表，并有基本排序与去重逻辑。

### E7 联通三档模式
状态：已完成
目标：把 `complete_mode / partial_mode / safe_mode` 在页面上完整区分开。
产出：模式联通后的完整页面。
前置依赖：E3、E4、E5、E6。
子子任务清单：
- 区分三种模式的页面结构和文案。
- 确保 safe 模式不会展示过度确定的结论。
- 确保 partial 模式不会伪装成完整结果。
实现备注：三档模式已经在状态条、风险区、空态和 fallback 文案中被清晰区分。

### E8 增加空态、失败提示和边界说明
状态：已完成
目标：补足失败提示、空态文案、demo 边界说明和 fallback 提示。
产出：演示更稳的前端状态表达。
前置依赖：E7。
子子任务清单：
- 为空结果、接口失败、部分结果设计空态。
- 明确展示 fallback 和边界化提示文案。
- 补充 demo 场景下的说明和重试入口。
实现备注：当前 demo 离线回退、接口失败安全回退和边界说明都已经接通。