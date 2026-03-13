# Cluster-C / API Foundation

## 这个子 task 是干什么的

这个工作包负责后端主链路和 API 基础设施，是整个系统里最核心的业务实现入口。

## 为什么要有这个子 task

V1 是否成立，最终看的不是文档，而是后端是否能稳定吐出一份结构化 `Report`。没有这个子 task，前端只能停留在静态页面，测试也无法做端到端回归。

## 为什么这个子 task 可以并行

它只聚焦主链路和 API，不承担检索时间线细节，也不承担前端页面实现。在共享 schema 明确后，它可以和前端、检索、测试并行推进，只在少数集成点汇合。

## 详细子任务

### C1 初始化 FastAPI 项目骨架
状态：未完成
目标：创建后端目录、入口、路由层、配置层和基础依赖结构。
产出：可启动的 FastAPI 服务。
前置依赖：无。
子子任务清单：
- 创建 `backend/app` 基础目录结构。
- 建立应用入口、主路由和基础配置文件。
- 确保本地可以启动服务并访问根路由或 health 路由。

### C2 建立统一配置与日志规范
状态：未完成
目标：接环境变量读取、日志初始化、基础异常处理。
产出：统一配置和日志基础设施。
前置依赖：C1。
子子任务清单：
- 定义环境变量读取方式和默认配置。
- 建立应用日志格式和日志级别规则。
- 加入基础异常捕获和错误日志输出。

### C3 建立健康检查与错误响应
状态：未完成
目标：实现 `health` 接口和统一错误返回结构。
产出：基础 API 可观测性。
前置依赖：C1、C2。
子子任务清单：
- 实现 `GET /api/v1/health`。
- 统一 4xx/5xx 响应结构。
- 为错误响应准备最小示例和测试入口。

### C4 实现 `input_normalizer` mock 版
状态：未完成
目标：基于最小测试集接住文本、URL、问题输入，输出 `EventDraft`。
产出：输入标准化 mock 服务。
前置依赖：schema 和测试数据到位。
子子任务清单：
- 识别输入类型并给出分类结果。
- 基于 case 输出标题、摘要、关键词等核心字段。
- 对失败输入返回 fallback 或 safe 模式提示所需信息。

### C5 实现 `claim_extractor` mock 版
状态：未完成
目标：基于 mock 或规则输出 3 到 5 条 claim，并完成类型分类。
产出：claim 抽取 mock 服务。
前置依赖：C4。
子子任务清单：
- 设计 claim 抽取服务接口。
- 根据最小 case 产出 claim 与 claim_type。
- 对 opinion、prediction、unverifiable 做边界处理。

### C6 实现 `verdict_engine` mock 版
状态：未完成
目标：根据最小 case 的 evidence 和规则输出 verdict 与 confidence。
产出：verdict mock 服务。
前置依赖：C5、schema。
子子任务清单：
- 把 evidence 输入映射到统一结构。
- 根据规则输出 verdict 和 confidence。
- 对 insufficient 与 conflicting 做保守判定。

### C7 实现 `report_builder`
状态：未完成
目标：根据输入质量、claim 结果、timeline 结果决定模式并组装成统一 `Report`。
产出：完整 `Report` 构建逻辑。
前置依赖：C4、C5、C6。
子子任务清单：
- 设计 report builder 输入输出接口。
- 实现 `complete_mode / partial_mode / safe_mode` 判断逻辑。
- 组装 event、claim_results、timeline、risks 和 summary。

### C8 实现 `POST /api/v1/analyze`
状态：未完成
目标：把输入标准化、claim、verdict、timeline、report 串成一个编排接口。
产出：前端可直接调用的主接口。
前置依赖：C7 和时间线结果可接入。
子子任务清单：
- 设计请求体和响应体。
- 串联输入、claim、verdict、timeline、report 流程。
- 对异常链路返回统一的错误或保守结果。

### C9 接入真实 Kimi provider
状态：未完成
目标：把 mock 的理解与抽取逻辑逐步替换为真实 Kimi 调用。
产出：文本输入真实链路。
前置依赖：C8、测试基本通过。
子子任务清单：
- 接入 Kimi 配置和 provider 调用封装。
- 先替换事件理解和 claim 抽取能力。
- 验证真实输出仍能对齐既有 schema。

### C10 实现 URL 抽取与 fallback
状态：未完成
目标：接 URL 内容抽取、失败降级、提示粘贴正文的逻辑。
产出：URL 增强能力和安全 fallback。
前置依赖：C9。
子子任务清单：
- 接入 URL 正文抽取与基础清洗。
- 处理抽取失败、正文为空、来源缺失等情况。
- 返回明确的粘贴正文提示和模式降级信息。
