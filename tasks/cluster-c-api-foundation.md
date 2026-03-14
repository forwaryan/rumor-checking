# Cluster-C / API Foundation

## 这个子 task 是干什么的

这个工作包负责后端主链路和 API 基础设施，是整个系统里最核心的业务实现入口。

## 为什么要有这个子 task

V1 是否成立，最终看的不是文档，而是后端是否能稳定吐出一份结构化 `Report`。没有这个子 task，前端只能停留在静态页面，测试也无法做端到端回归。

## 为什么这个子 task 可以并行

它只聚焦主链路和 API，不承担检索时间线细节，也不承担前端页面实现。在共享 schema 明确后，它可以和前端、检索、测试并行推进，只在少数集成点汇合。

## 窗口执行 Prompt（全局）

```text
你现在负责 Cluster-C / API Foundation。
你的目标是继续推进后端主链路，优先完成本文件中“进行中/未完成”的子任务，当前默认聚焦 C10 与 C11。
请先完整阅读本文件、backend/docs/api-foundation-implementation-record.md、backend/README.md、backend/app/services/、backend/tests/，再决定本轮具体改动。
执行时必须先把当前要处理的子任务拆成 3 到 7 个更细步骤，并先把“本轮执行任务 / 执行步骤”写回本文件对应子任务下，再开始编码。
你可以修改 backend/ 下与 API foundation 直接相关的代码、测试和文档，但不要扩到真实检索系统、前端页面或最终交付包装。
已完成子任务默认不要重做，除非为修复回归、对齐接口或更新实现记录所必需。
完成后必须：
1. 回写本文件中对应子任务的状态，并补充本轮完成记录：改了哪些文件、怎么完成、验证如何、剩余问题是什么。
2. 给出验证结果，包括接口、测试或联调结论。
3. 说明是否需要交给 Cluster-D、F 或 G 继续跟进。
如果用户要求 [log]，同步更新 prompt-history.md。
```

## 当前实现记录

- 详细实现记录：`backend/docs/api-foundation-implementation-record.md`
- 当前状态说明：`C1` 到 `C8` 已完成；`C9` 第一阶段已完成；`C10` 与新增的 `C11` 是当前主线缺口。
- 当前前端虽然已经能优先调用真实 `POST /api/v1/analyze`，但后端主链仍存在明显的 `scenario_library` / 模板证据 / fallback 依赖；现在不能把“能返回一份 Report”直接等同于“已经完成真实 reasoning 闭环”。

## 详细子任务

### C1 初始化 FastAPI 项目骨架
状态：已完成（最小可运行版本）
目标：创建后端目录、入口、路由层、配置层和基础依赖结构。
产出：可启动的 FastAPI 服务。
前置依赖：无。
子子任务清单：
- 创建 `backend/app` 基础目录结构。
- 建立应用入口、主路由和基础配置文件。
- 确保本地可以启动服务并访问根路由或 health 路由。
实现备注：已完成，应用入口为 `backend/app/main.py`。

### C2 建立统一配置与日志规范
状态：已完成（最小可运行版本）
目标：接环境变量读取、日志初始化、基础异常处理。
产出：统一配置和日志基础设施。
前置依赖：C1。
子子任务清单：
- 定义环境变量读取方式和默认配置。
- 建立应用日志格式和日志级别规则。
- 加入基础异常捕获和错误日志输出。
实现备注：已完成，配置在 `backend/app/core/config.py`，日志与异常在 `backend/app/core/`。

### C3 建立健康检查与错误响应
状态：已完成（最小可运行版本）
目标：实现 `health` 接口和统一错误返回结构。
产出：基础 API 可观测性。
前置依赖：C1、C2。
子子任务清单：
- 实现 `GET /api/v1/health`。
- 统一 4xx/5xx 响应结构。
- 为错误响应准备最小示例和测试入口。
实现备注：已完成，health 与统一错误结构均已有测试覆盖。

### C4 实现 `input_normalizer` mock 版
状态：已完成（规则版 + provider 可增强）
目标：基于最小测试集接住文本、URL、问题输入，输出 `NormalizedEvent`。
产出：输入标准化服务。
前置依赖：schema 和测试数据到位。
子子任务清单：
- 识别输入类型并给出分类结果。
- 基于 case 输出标题、摘要、关键词等核心字段。
- 对失败输入返回 fallback 或 safe 模式提示所需信息。
实现备注：已完成，当前基础链路基于规则和 `scenario_library`，文本与问题输入可再叠加 provider enrichment。

### C5 实现 `claim_extractor` mock 版
状态：已完成（规则版 + provider 可增强）
目标：基于 mock 或规则输出 3 到 5 条 claim，并完成类型分类。
产出：claim 抽取服务。
前置依赖：C4。
子子任务清单：
- 设计 claim 抽取服务接口。
- 根据最小 case 产出 claim 与 claim_type。
- 对 opinion、prediction、unverifiable 做边界处理。
实现备注：已完成；provider 开启时会优先使用 provider claims，并在非 generic 场景下与规则 claims 合并，避免 verdict 回归。

### C6 实现 `verdict_engine` mock 版
状态：已完成（规则版）
目标：根据最小 case 的 evidence 和规则输出 verdict 与 confidence。
产出：verdict 服务。
前置依赖：C5、schema。
子子任务清单：
- 把 evidence 输入映射到统一结构。
- 根据规则输出 verdict 和 confidence。
- 对 insufficient 与 conflicting 做保守判定。
实现备注：已完成，覆盖 `supported / refuted / insufficient / conflicting`。

### C7 实现 `report_builder`
状态：已完成
目标：根据输入质量、claim 结果、timeline 结果决定模式并组装成统一 `Report`。
产出：完整 `Report` 构建逻辑。
前置依赖：C4、C5、C6。
子子任务清单：
- 设计 report builder 输入输出接口。
- 实现 `complete_mode / partial_mode / safe_mode` 判断逻辑。
- 组装 event、claim_results、timeline、risks 和 summary。
实现备注：已完成，当前输出字段已与 `contracts/` 对齐。

### C8 实现 `POST /api/v1/analyze`
状态：已完成
目标：把输入标准化、claim、verdict、timeline、report 串成一个编排接口。
产出：前端可直接调用的主接口。
前置依赖：C7 和时间线结果可接入。
子子任务清单：
- 设计请求体和响应体。
- 串联输入、claim、verdict、timeline、report 流程。
- 对异常链路返回统一的错误或保守结果。
实现备注：已完成，当前直接返回裸 `Report`，并已通过 API smoke test、case 测试与 contract 回归测试。

### C9 接入真实 Kimi provider
状态：进行中（第一阶段已完成）
目标：把 mock 的理解与抽取逻辑逐步替换为真实 Kimi 调用。
产出：文本输入真实链路。
前置依赖：C8、测试基本通过。
子子任务清单：
- 接入 Kimi 配置和 provider 调用封装。
- 先替换事件理解和 claim 抽取能力。
- 验证真实输出仍能对齐既有 schema。
实现备注：
- 已新增 `backend/app/services/kimi_provider.py`，通过 OpenAI-compatible chat completion 方式请求结构化 JSON。
- 已新增 `backend/app/services/provider_enricher.py`，在 `AnalyzePipeline` 中把 provider 输出合并进 `NormalizedEvent` 和 claims。
- 默认关闭；只有显式配置 `ANALYSIS_PROVIDER=kimi` 且提供 `KIMI_API_KEY` 时才会调用。
- provider 超时、网络错误、非法 JSON 都会自动回退到规则链路。
- 已新增 provider 成功路径与 provider 失败回退路径测试。
- 尚未完成“带真实 key 的在线联调”和“prompt/输出质量调优”。
本轮执行任务：
- 修复 `Cluster-C` 任务文件的损坏内容，恢复 `C1` 到 `C10` 的完整说明。
- 为真实 Kimi key 的接入补齐项目内的环境变量示例、README 使用说明和联调入口说明。
- 把本轮“Kimi key 接入准备”记录进 task 与日志，作为后续真实在线联调的前置交接。

执行步骤：
- 恢复 `tasks/cluster-c-api-foundation.md` 的完整内容并保留当前真实状态。
- 核对 `backend/app/core/config.py`、`backend/.env.example`、`backend/README.md` 中对 Kimi 配置的说明是否完整。
- 在 `backend/.env.example` 中补齐 `ANALYSIS_PROVIDER`、`KIMI_API_KEY`、`KIMI_BASE_URL`、`KIMI_MODEL`、`PROVIDER_TIMEOUT_SECONDS` 示例。
- 在 `backend/app/core/config.py` 中补充 `.env` 自动加载，允许从仓库根目录 `.env` 或 `backend/.env` 读取配置。
- 在 `backend/README.md` 中补齐真实 provider 启用、启动和最小联调说明。
- 跑后端 API 回归，确认新增配置加载没有破坏现有行为。
- 回写 `C9` 完成记录，并同步追加 `prompt-history.md`。

完成记录：
- 改动文件：`tasks/cluster-c-api-foundation.md`、`backend/app/core/config.py`、`backend/.env.example`、`backend/README.md`、`prompt-history.md`。
- 完成方式：修复了损坏的 `Cluster-C` 任务文件；在后端配置层新增轻量 `.env` 文件加载能力，优先读取仓库根目录 `.env` 与 `backend/.env`，且不覆盖已有进程环境变量；同时补齐 Kimi 相关环境变量示例与 README 启用步骤、联调示例和判断方式。
- 验证结果：`pytest backend/tests/test_api.py -q` 通过，`11 passed`；现有 API 主链路和 provider 回退测试未被本轮配置改动破坏。
- 剩余问题：真实 `KIMI_API_KEY` 仍需由用户提供并写入 `backend/.env` 或 shell 环境；`C9` 仍缺真实在线联调、小样本输出验收和 prompt/输出质量调优，因此状态保持“进行中”。

本轮执行任务（真实在线联调）：
- 在确保密钥不会进入版本控制的前提下，接收用户提供的真实 `KIMI_API_KEY`。
- 把 key 写入本地 `backend/.env`，启用真实 Kimi provider。
- 对 `text_news` 输入执行一次真实 provider smoke test，确认项目已经能走在线模型路径。

执行步骤（真实在线联调）：
- 检查仓库是否已有 `.gitignore` / `.env` 忽略规则。
- 如无忽略规则，先补最小 `.gitignore`，确保 `backend/.env` 与根目录 `.env` 不进入版本控制。
- 将用户提供的 key 写入 `backend/.env`，启用 `ANALYSIS_PROVIDER=kimi`。
- 使用真实 `text_news` 输入跑一次后端 smoke test，记录 provider 成功或失败结果。
- 回写 `C9` 完成记录，说明真实联调结果与剩余问题。

完成记录（真实在线联调）：
- 改动文件：`.gitignore`、`backend/.env`、`tasks/cluster-c-api-foundation.md`。
- 完成方式：新增最小 `.gitignore`，忽略根目录 `.env` 与 `backend/.env`；把用户提供的真实 `KIMI_API_KEY` 写入 `backend/.env`，并通过 `backend/app/core/config.py` 的 `.env` 自动加载路径启用真实 provider。
- 验证结果：已完成两次真实在线调用，日志均出现 `POST https://api.moonshot.cn/v1/chat/completions "HTTP/1.1 200 OK"`；`/api/v1/analyze` 返回 `200`，说明项目已经能走真实 Kimi provider 路径。ASCII 样本下最终返回 `safe_mode`、`1` 条 claim、`insufficient` verdict，说明 provider 已接管事件理解/claim 抽取，但检索、evidence、verdict 仍受下游规则链路限制。
- 剩余问题：`C9` 的“能调用真实 Kimi”已打通，但“输出质量调优”仍未完成；当前可见问题包括 claim 仍偏保守。对同一 ASCII 样本做 `ANALYSIS_PROVIDER=off` 对照后，标题截断问题依然存在，说明这不是 Kimi 回归，而是上游 normalizer 的既有质量问题。若要让“较真”新闻应用在完整性上继续提升，下一步应继续做小样本验收、prompt 调优，以及与 `Cluster-D / C10 / F` 的联动收口。

本轮执行任务（C9 输出质量调优）：
- 建立 10 到 20 条可复用的文本新闻小样本验收集，覆盖标题党、传闻问句、真假混杂、信息残缺和辟谣跟进等常见输入。
- 调整 `backend/app/services/kimi_provider.py` 的 prompt、输入包装与结构化输出清洗，重点提升标题、摘要和 claims 的稳定性，降低字段缺失与过度保守。
- 仅在 `backend/app/services/provider_enricher.py` 内做最小合并策略优化，确保 provider 输出更容易落到最终事件信息，但不改 URL 接入和 analyze 主链分叉。
- 增加 provider 级或 API 级验证，证明 `ANALYSIS_PROVIDER=kimi` 相比 `ANALYSIS_PROVIDER=off` 对文本新闻更有帮助，同时保持 provider 失败回退路径不变。
- 回写 `C9` 剩余问题，并明确交给 `C10 / C11 / F8` 的接口边界与后续验收口径。

执行步骤（C9 输出质量调优）：
- 盘点现有 provider prompt、结构化 JSON 解析和 enrichment 合并逻辑，明确最小改动面。
- 设计并落库小样本验收集，为每条样例补充输入类型、预期关注点和“provider 打开后应优于 off”的观察口径。
- 调整 Kimi provider 的系统提示词、用户提示词和输出清洗规则，优先稳住 title / summary / claims 三类字段。
- 视需要微调 provider enrichment 合并策略，优先保留更完整、更像新闻摘要的 provider 字段，同时不破坏 fallback。
- 补充 provider/API 测试，覆盖 schema 稳定、帮助性对比和 provider 失败回退。
- 运行定向测试与样例验收，最后回写任务文档和后端说明文档。
完成记录（C9 输出质量调优）：
- 改动文件：`tasks/cluster-c-api-foundation.md`、`backend/app/services/kimi_provider.py`、`backend/app/services/provider_enricher.py`、`backend/tests/conftest.py`、`backend/tests/test_kimi_provider_quality.py`、`evals/minimal_v1/provider_text_news_cases.json`、`evals/minimal_v1/README.md`、`backend/README.md`。
- 完成方式：新增 `12` 条 `text_news` 小样本验收集，覆盖标题党、传闻问句、真假混杂、旧视频翻炒、政策误读和辟谣跟进；强化 Kimi system/user prompt，补上 claim_type 宽松归一化、字符串 keywords 清洗、空泛标题/摘要/claim 过滤和从 summary 反推 title 的兜底；在 `provider_enricher.py` 中加入轻量打分合并逻辑，让更具体的 provider title / summary / source_name 优先覆盖嘈杂输入衍生字段；同时把默认测试 client 固定到 `ANALYSIS_PROVIDER=off`，保证 fallback 验证不被本地真实 key 污染。
- 验证结果：`pytest backend/tests/test_kimi_provider.py backend/tests/test_kimi_provider_quality.py backend/tests/test_api.py -q` 通过，`21 passed`；其中 `backend/tests/test_kimi_provider_quality.py::test_api_provider_enabled_surfaces_more_helpful_output_than_off` 复用了 `provider_text_news_cases.json` 的 `KP01`，证明 provider 打开后相比 `off` 能输出更具体的 `source_name / summary`，且 claim 数量从基线的单条保守 claim 提升到两条可核查 claim；`backend/tests/test_api.py` 全量通过，说明现有 API 回退路径未被破坏。
- 剩余问题：这轮主要收口的是 provider 侧“文本新闻理解与抽取质量”，不是在线随机新闻总体验收。`C10` 仍负责 URL 正文抽取与失败降级，当前小样本集故意只覆盖 `text_news`；`C11` 仍负责让下游 verdict / timeline / provenance 更真实消费 provider 输出，当前 provider 提升不会自动消除 `scenario_library` 与模板 evidence 依赖；`F8` 后续应在真实 `ANALYSIS_PROVIDER=kimi` 打开时，复用本轮样例并补充随机 live case，把“提示词调优有效”升级成“随机新闻较真有效”的最终验收结论。
### C10 实现 URL 抽取与 fallback
状态：已完成（公开 HTML 抽取 + 清晰 fallback）
目标：接 URL 内容抽取、失败降级、提示粘贴正文的逻辑。
产出：URL 增强能力和安全 fallback。
前置依赖：C9。
子子任务清单：
- 接入 URL 正文抽取与基础清洗。
- 处理抽取失败、正文为空、来源缺失等情况。
- 返回明确的粘贴正文提示和模式降级信息。
实现备注：
- 已新增 `backend/app/services/url_content_extractor.py`，仅抓取可直接访问的公开 HTML 页面；优先抽取 `<title>`、meta、JSON-LD、`<article>/<main>` 中的标题、摘要、来源、发布时间和正文片段。
- `InputNormalizer` 已在 URL 输入上优先消费抽取结果，并把 `title / summary / source_name / published_at / fallback_reason` 落入 `NormalizedEvent`；`mock_fetch_result` 仍保留为测试与回归入口。
- `ReportBuilder` 已按 `fallback_reason` 输出 URL 专属风险提示，确保抽取失败、超时、非 HTML 页面等情况继续走保守模式而不是中断 analyze。

本轮执行任务：
- 明确 URL 正文抽取的策略、能力边界与降级条件，只覆盖可直接抓取的公开 HTML 页面。
- 新增轻量 URL 抽取服务，向 `InputNormalizer` 提供标题、正文摘要、来源、发布时间和失败原因等结构化结果。
- 将 URL 抽取结果接入 `AnalyzePipeline -> InputNormalizer -> ReportBuilder` 主链路，保证可抽取时优先使用真实字段，失败时回退到保守 URL fallback。
- 补齐 URL 抽取成功、抽取失败、超时/异常 fallback、文本输入不回归测试，并同步更新后端说明文档与实现记录。

执行步骤：
- 盘点现有 URL 输入分支、`mock_fetch_result`、fallback 条件与风险提示，确定新增结构化抽取结果的 schema 边界。
- 实现独立 URL 抽取模块，优先抓取 HTML 页面的标题、正文、摘要、来源和发布时间，并归一化失败原因与超时异常。
- 在 `AnalyzePipeline` 中为 URL 输入接入抽取调用，把结果传给 `InputNormalizer`，确保失败时仍输出保守结果而不是中断 analyze。
- 调整 `InputNormalizer` 的 URL 正常路径和 fallback 文案，让 `title / summary / source_name / published_at` 能在成功时落入最终事件信息。
- 补测试并跑后端回归验证，最后回写 `tasks/cluster-c-api-foundation.md`、`backend/docs/api-foundation-implementation-record.md` 与 `backend/README.md`。

完成记录：
- 对应实现文件：`backend/app/models/schemas.py`、`backend/app/services/url_content_extractor.py`、`backend/app/services/input_normalizer.py`、`backend/app/services/report_builder.py`、`backend/tests/test_api.py`。
- 本轮回写文件：`tasks/cluster-c-api-foundation.md`、`backend/docs/api-foundation-implementation-record.md`、`backend/README.md`。
- 完成方式：URL 输入已接入轻量 HTML 抽取服务，使用 `httpx` 与本地规则优先提取标题、正文、摘要、来源和发布时间；成功时将结构化字段送入 `InputNormalizer`，失败时按 `partial / empty / timeout / error / unsupported` 归一化原因并继续输出保守结果。
- 验证结果：`pytest backend/tests/test_api.py -q` 通过，`15 passed`；已覆盖 URL 抽取成功、非 HTML fallback、超时 fallback、文本输入不触发 URL 抽取、原有文本/问题输入不回归。
- 剩余问题：当前只支持可直接抓取的公开 HTML 页面，不处理登录页、强反爬站点、动态渲染站点、PDF/图片正文与真实网页检索；更深的主链 provenance、真实 evidence 与 verdict 收口仍留给 `C11` 继续推进。
### C11 把 analyze 主链从 scenario 占位推进到真实 reasoning-grounded 流程
状态：未完成
目标：削弱 `scenario_library`、模板证据和前端 demo payload 对主链成功率的依赖，让 analyze 真正基于输入、provider 输出和检索证据生成结论。
产出：真实分析主链与清晰 provenance 边界。
前置依赖：C9、C10，并需与 `Cluster-D` 的 `D5` 到 `D7` 对齐检索输入输出。
子子任务清单：
- 盘点 `AnalyzePipeline`、`VerdictEngine`、`TimelineBuilder` 中仍依赖 `scenario_library`、模板 evidence、mock timeline 的路径。
- 明确真实路径与 fallback 路径的分叉条件，确保 `safe_mode / partial_mode` 不伪装成完整分析。
- 为 report 补齐或稳定结果 provenance 输入，让前端和测试能区分 real analyze、mock retrieval、demo payload 与 frontend fallback。
- 补齐覆盖真实路径、回退路径和无证据保守判定的回归测试。
实现备注：这是当前系统最核心的能力缺口。现阶段后端“能输出 Report”不等于“已经完成真实分析”；只有当主链主要依赖真实输入理解、真实检索证据和保守 verdict 时，V1 才能摆脱缓存 / JSON 驱动的演示感。




