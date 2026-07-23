# 当前已核验状态

更新时间：2026-07-23（Asia/Shanghai）；概率与情形分布特性于同日追加

这份文档只保留已经被当前代码核验过的事实，用来约束 README 和现行运行文档的口径。

## 核验依据

已直接核对以下实现或测试文件：

- `backend/app/api/v1/endpoints/analyze.py`
- `backend/app/api/v1/endpoints/health.py`
- `backend/app/core/config.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/agent/{state,planner,runner}.py`
- `backend/app/agent_tools/{base,tools}.py`
- `backend/app/services/agent_reasoner.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_models.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `backend/app/services/content_check_builder.py`
- `backend/app/models/schemas.py`
- `frontend/components/analyze-page.tsx`
- `frontend/lib/agent-run.ts`
- `frontend/lib/trace-steps.ts`
- `frontend/lib/api-client.ts`
- `frontend/lib/report-utils.ts`
- `contracts/report.schema.json`

## 已确认事实

### 1. 当前公开 API

当前公开路由只有：

- `GET /api/v1/health`
- `GET /api/v1/models`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`

当前没有公开的：

- `GET /api/v1/demo-cases`
- `POST /api/v1/replay`

### 2. provenance 已收敛

`report.provenance.source_type` 当前 contract 与实现只保留：

- `backend_live`
- `backend_mock`

前端缺失 provenance 时，会保守落到 `unknown` 展示，但这不是后端返回值枚举的一部分。

### 3. 前端不再消费本地报告 JSON

- demo 卡片当前只负责填充稳定输入样例
- 前端分析结果来自后端 `analyze` 或 `analyze/stream`
- `contracts/demo_payloads/*.json` 已移除
- 当前也不再生成本地 `frontend_fallback` 报告壳

### 4. 默认基线仍是 mock 路径

默认环境仍是：

- `ANALYSIS_PROVIDER=off`
- `RETRIEVAL_PROVIDER=mock`
- `RETRIEVAL_FALLBACK_TO_MOCK=true`

因此当前最稳的对外口径仍然是 `mock demo + provenance 边界`，而不是“真实检索已稳定通过”。

### 4b. 两档分析（按请求 `mode` 选择）

- `AnalyzePipeline.analyze` 读取 `request.request_context["mode"]`（见 `_is_deep_mode`），同一进程支持两档，不靠全局环境变量切换：
  - `fast`（默认；缺省或未知值都按 fast）：强制零 LLM 规则路径——跳过 agent 编排、`resolve_question` / `synthesize` / `_run_investigation`、`provider_enricher.enrich`（结构化补全），以及检索层的 LLM query 抽取。只保留真实检索（由 `RETRIEVAL_PROVIDER` 决定）+ 规则 verdict。实测约 0.2–0.3s。
  - `deep`：走现有 LLM/agent-first 全链路。
- 由 `backend/tests/test_api.py::test_fast_mode_skips_llm_enrichment_while_deep_mode_uses_it` 锁定：provider 开启时 fast 不产生 LLM 调用、deep 产生。
- 前端主按钮走 fast，结果页再给"深度核查"二次入口触发 deep；深度档可在下拉里选白名单模型（见第 8 条），选择随 `?q=&mode=&model=` 写进 URL，刷新/分享可复现。
- 前端把流式事件按 `stage_key` 聚合成可观测执行时间线（`frontend/lib/trace-steps.ts`），每步展示"干了什么/输入/输出/结论"；每次 LLM 调用的**提问与回答**都以"人类可读 / 原始 JSON"两个 tab 呈现（`humanizeLlmText` 把 planner/investigation/synthesis 的 JSON 翻成中文摘要）。后端 emit 的事件里已去除内网网关地址（只保留模型名），实测流复扫无泄漏。

### 5. URL 抽取与检索边界

- URL 输入已支持公开 HTML 页面抽取
- 不支持登录页、强反爬页面、浏览器渲染页面、PDF 或图片正文

### 6. Agent 编排（默认关闭，可回退）

- 存在一层可插拔的 agent 编排：`backend/app/agent`（`state` / `planner` / `runner`）把现有服务包装成工具（`backend/app/agent_tools`），按 `plan -> tool -> observe -> decide -> finalize` 的小循环执行。
- 由 `AGENT_ORCHESTRATOR_ENABLED` 控制，**默认 `false`**。开关关闭时走原来的固定 `AnalyzePipeline`。
- Planner 可插拔：
  - `RulePlanner`（默认）复刻固定 pipeline 的顺序，在 `off + mock` 路径上产出与旧链路**逐字节一致**的 `Report`（由 `backend/tests/test_agent_orchestrator.py` 的 parity 测试保证）。
  - `LlmPlanner`（配置了 LLM 时启用）在真实岔路口调用 LLM 决策，带非法动作护栏，失败即退回 `RulePlanner`。当前岔路口的候选动作：`investigate`（补一轮检索）、`fetch_url`（抓取高价值证据全文）、`synthesize`（直接综合）。
- `fetch_url` 自主动作：LLM 可选择抓取当前证据里最权威（high-trust/非聚合/高 tier）来源的正文，按**同一 `result_id`** 挂靠喂给 synthesis（grounding 安全，不新增证据源）；由 `AGENT_MAX_URL_FETCHES` 限制（默认 1，0=关），带去重与抓取失败降级。`fetch_url` 在 `legal_actions` 里始终排在规则默认动作之后，所以 `RulePlanner`（取首个）永不选它 → off+mock parity 不受影响。
- runner 抛错时自动回退固定 pipeline，不影响可交付性。
- 前端保留了从 `stage`/`log` 事件派生 agent 调查动作的逻辑（`frontend/lib/agent-run.ts`）。前端重写为单页产品界面后，早期的独立调查过程面板组件已移除，执行过程改为内联在结果页底部的可折叠 trace 区块；非 agent 路径下 trace 仍照常展示流水线事件。

### 7. Grounded verdict 与诚实兜底

- 开 LLM 时，`agent_reasoner.synthesize` 接管 verdict：任何 `supported/refuted/conflicting` 判定必须带有效证据（`evidence_result_id`），否则降级为 `insufficient`（`backend/tests/test_agent_grounded_verdict.py` 锁定）。
- 当 LLM 启用但最终落到规则引擎时，provenance 会带显式 `fallback_reason=llm_synthesis_unavailable_rule_fallback`，不伪装成正常 LLM 结论。

### 8. LLM 供应商可配置（已切到新模型），联网检索现状

- LLM 调用层已做成**供应商中立**：走标准 OpenAI 兼容 `chat/completions`、流式读取，模型/端点/密钥全部由配置（`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_SEARCH_MODEL`）决定。当前已从早期供应商切换到一批**新的可配置模型**（通过内部网关），判定/planner/synthesis 均走该路径并端到端联调通过。
- 具体端点、模型名和密钥只存在于 git 忽略的 `backend/.env`，不写入代码或 `.env.example`（保持对外中立）。
- **联网检索现状**：`RETRIEVAL_PROVIDER` 当前实现的枚举为 `mock | playwright | gdelt | kimi | off`（见 `backend/app/services/retrieval_service.py` 的 `_build_provider`）。
  - `playwright`（`backend/app/services/playwright_search_provider.py`）：**当前推荐的真实联网路径**，用纯 httpx 抓取百度（主）+ Bing（兜底）搜索结果页并解析，不依赖浏览器二进制、也不依赖模型内建搜索，中文覆盖较好。已端到端验证可产出真实 URL 证据并驱动 grounded 判定。
  - `kimi`（LLM 内建 `$web_search`）：仅对支持该工具的供应商有效。真实 `$web_search` 曾在早期供应商上端到端跑通（`source_type=backend_live`、`evidence_source=retrieval_live`、含 `fetch_url` 自主抓正文）；当前所用新模型/网关**没有等价内建搜索工具**，因此该分支在当前模型下不可用。
  - `gdelt`：免费新闻 API，英文偏向、中文覆盖弱。
- 判定层（新模型）与检索层是解耦的：换判定模型不影响检索策略，反之亦然。检索是否联网只由 `RETRIEVAL_PROVIDER` 决定。
- **多模型可选**：`LLM_MODELS`（逗号分隔白名单）+ `LLM_MODEL`（默认）；`GET /api/v1/models` 暴露白名单+默认给前端下拉。请求可带 `request_context.model`，由 `Settings.resolve_model` 校验——不在白名单内的一律退回默认，防止客户端把网关指向任意模型。端点只返回模型名，网关地址/密钥永不返回。
- **SERP 结果清洗**（`retrieval_service._is_noise_result` / `_result_matches_query`）：硬过滤字典/百科/时间校准类垃圾页（全被过滤后诚实返回空而非拿垃圾当证据）；导航型品牌首页（如 `pinduoduo.com/`）只匹配单一实体词、不含事件词时会被丢弃，避免把官网首页当"证据"。
- **无日期结果排序**（codex review 修复）：真实 SERP 命中常无 `published_at`；时间排序键统一以 `undated_sort_flag` 领先，有日期的结果恒排在无日期之前，无日期结果不再"冒充最早"抢时间线 origin。dateless sentinel 已改为带时区（`+08:00`），`published_dt` 也把 naive 字符串归一到 `+08:00`，避免混合有/无日期 bundle 触发 naive-vs-aware datetime 比较崩溃。
- 默认交付/演示路径仍是 `off + mock`（见第 4 条）；要走真实联网优先选 `playwright`。

### 9. 多可能性 + 为真概率（概率与 verdict 解耦）

- 每条 claim 除 `verdict` / `confidence` 外，新增 `truth_probability`（0–100）与 `probability_basis`（`evidence` / `prior`）；`ContentCheckItem` 同步带这两个字段；`PossibilityItem`（承载"整体情形分布"）新增 `probability` + `basis`，保留原 `likelihood` 作缺省降级展示。全部为可选字段，对既有反序列化/parity 是纯增量。
- **核心原则：概率独立于 verdict。** grounded 兜底（无证据的决定性 verdict 必须降级为 `insufficient`，见第 7 条）完全不变；概率是另一维度，用 `basis` 诚实区分"由检索证据支撑（evidence）"与"仅凭常识先验（prior）"。因此一条 `insufficient` 的 claim 仍可带 `truth_probability=15, basis=prior`（由 `test_probability.py::test_probability_is_independent_of_grounded_verdict_downgrade` 锁定）。
- **fast 档（零 LLM）**：`verdict_engine.coarse_truth_probability` 把现有 verdict+confidence 确定映射成粗概率（supported/refuted 分档、conflicting/insufficient=50），在 `report_builder._backfill_claim_probabilities` 单点回填。insufficient→`basis=prior`（无信息中点，不谎称有证据）；决定性 verdict 但无证据挂靠时也降级为 `prior`。整体情形分布仍走规则 `_build_possibilities`，`probability` 留空、**不伪造** sum-to-100 分布。
- **deep 档（LLM）**：`SYNTHESIS_SYSTEM_PROMPT` 要求模型对每条 claim 给 `truth_probability`+`probability_basis`，并额外产出 2–4 条互斥的整体 `scenarios`（合计≈100）。`agent_reasoner._build_scenarios` 解析、clamp 并对偏离 100 的分布按比例归一化；`_normalize_probability_basis` 强制：模型标 `evidence` 但实际无证据挂靠时改回 `prior`。deep 有 scenarios 时以 `possibilities_override` 替换规则可能性。
- 回填在 fast/deep 两档共用的 `report_builder.build` 内，off+mock 下 legacy 与 agent 编排走同一路径 → parity 逐字节一致不受影响（`test_agent_orchestrator.py`）。契约见 `contracts/claim_result.schema.json` 与 `contracts/report.schema.json` 的 `possibilities` / `contentCheckItems`。

## 当前仍未完成的事项

- 真实 live retrieval 的进一步降延迟：检索层已把一轮 query plan 的多条 query 改为并发抓取（`retrieve_for_event` 内用线程池并行执行 cache-miss 的网络请求），单轮检索墙钟时间从"多条 query 串行相加"降到"最慢单条"；`playwright` 抓取超时也已改为读取 `RETRIEVAL_TIMEOUT_SECONDS`（默认 12s，含独立 connect 超时），死连接会快速失败而非吊满窗口。当前剩余的冷启动开销主要来自 LLM 判定/synthesis 首次调用，不再是检索串行
- 公开 HTML 之外的 URL 抽取扩展
- agent planner 更强的自主性（当前可在 investigate/fetch_url/synthesize 岔路口决策，但还不能自主换角度重搜或动态扩大工具集合）
- 若未来确实需要 replay，是否公开接口和如何冻结术语体系

## 使用规则

- 若其他文档和当前代码实现冲突，以本文件和对应实现为准
- 这份文档只记录当前仍有效的事实，不再维护历史冲突登记表
