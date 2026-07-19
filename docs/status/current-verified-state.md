# 当前已核验状态

更新时间：2026-07-19（Asia/Shanghai）

这份文档只保留已经被当前代码核验过的事实，用来约束 README 和现行运行文档的口径。

## 核验依据

已直接核对以下实现或测试文件：

- `backend/app/api/v1/endpoints/analyze.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/agent/{state,planner,runner}.py`
- `backend/app/agent_tools/{base,tools}.py`
- `backend/app/services/agent_reasoner.py`
- `backend/app/models/schemas.py`
- `backend/app/services/report_builder.py`
- `frontend/components/analyze-page.tsx`
- `frontend/components/agent-run-panel.tsx`
- `frontend/lib/agent-run.ts`
- `frontend/lib/api-client.ts`
- `frontend/lib/report-utils.ts`
- `contracts/report.schema.json`

## 已确认事实

### 1. 当前公开 API

当前公开路由只有：

- `GET /api/v1/health`
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

### 5. URL 抽取与检索边界

- URL 输入已支持公开 HTML 页面抽取
- 不支持登录页、强反爬页面、浏览器渲染页面、PDF 或图片正文

### 6. Agent 编排（默认关闭，可回退）

- 存在一层可插拔的 agent 编排：`backend/app/agent`（`state` / `planner` / `runner`）把现有服务包装成工具（`backend/app/agent_tools`），按 `plan -> tool -> observe -> decide -> finalize` 的小循环执行。
- 由 `AGENT_ORCHESTRATOR_ENABLED` 控制，**默认 `false`**。开关关闭时走原来的固定 `AnalyzePipeline`。
- Planner 可插拔：
  - `RulePlanner`（默认）复刻固定 pipeline 的顺序，在 `off + mock` 路径上产出与旧链路**逐字节一致**的 `Report`（由 `backend/tests/test_agent_orchestrator.py` 的 parity 测试保证）。
  - `LlmPlanner`（配置了 Kimi 时启用）在真实岔路口调用 LLM 决策，带非法动作护栏，失败即退回 `RulePlanner`。当前岔路口的候选动作：`investigate`（补一轮检索）、`fetch_url`（抓取高价值证据全文）、`synthesize`（直接综合）。
- `fetch_url` 自主动作：LLM 可选择抓取当前证据里最权威（high-trust/非聚合/高 tier）来源的正文，按**同一 `result_id`** 挂靠喂给 synthesis（grounding 安全，不新增证据源）；由 `AGENT_MAX_URL_FETCHES` 限制（默认 1，0=关），带去重与抓取失败降级。`fetch_url` 在 `legal_actions` 里始终排在规则默认动作之后，所以 `RulePlanner`（取首个）永不选它 → off+mock parity 不受影响。
- runner 抛错时自动回退固定 pipeline，不影响可交付性。
- 前端有对应的调查过程面板（`frontend/components/agent-run-panel.tsx`），从现有 `stage`/`log` 事件派生，非 agent 路径自动隐藏。

### 7. Grounded verdict 与诚实兜底

- 开 Kimi 时，`agent_reasoner.synthesize` 接管 verdict：任何 `supported/refuted/conflicting` 判定必须带有效证据（`evidence_result_id`），否则降级为 `insufficient`（`backend/tests/test_agent_grounded_verdict.py` 锁定）。
- 当 Kimi 启用但最终落到规则引擎时，provenance 会带显式 `fallback_reason=llm_synthesis_unavailable_rule_fallback`，不伪装成正常 LLM 结论。

### 8. 真实检索已联调通过（有配置前提，非默认）

- `RETRIEVAL_PROVIDER=kimi` 的 Kimi `$web_search` 联网检索已对真实 Moonshot API 端到端跑通：真实 URL、`source_type=backend_live`、`evidence_source=retrieval_live`、grounded 判定。
- `fetch_url` 自主动作也已真实联调：LLM planner 会自主选择抓取正文，并挑中官方来源（如中国驻法国大使馆），抓取的正文进入 synthesis。
- **前提**（真实联调发现，写入 `.env.example`）：检索需用大上下文模型（`KIMI_SEARCH_MODEL=moonshot-v1-32k`，8k 会因 web 内容撑爆而 400），且 `RETRIEVAL_TIMEOUT_SECONDS>=45`（默认 12s 会 ReadTimeout）。
- 延迟真实：一次完整 agent + 真实检索（首轮 2 条 + 追加 1 轮）可超过 ~120s。不建议作为无缓存的同步对外路径。
- 默认交付/演示路径仍是 `off + mock`（见第 4 条）。

## 当前仍未完成的事项

- 真实 live retrieval 的缓存/降低延迟策略（当前单次可超 120s，尚不适合无缓存同步对外）
- 公开 HTML 之外的 URL 抽取扩展
- agent planner 更强的自主性（当前只在 investigate/synthesize 岔路口决策，尚不能自主决定抓 URL、换角度重搜等）
- 若未来确实需要 replay，是否公开接口和如何冻结术语体系

## 使用规则

- 若其他文档和当前代码实现冲突，以本文件和对应实现为准
- 这份文档只记录当前仍有效的事实，不再维护历史冲突登记表
