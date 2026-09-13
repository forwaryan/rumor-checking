# Backend

FastAPI 主进程。产品能力/两档核查/概率维度看主 [README.md](../README.md)；这里只讲后端目录本身的接口、运行方式和边界。

更新时间：2026-08-29（Asia/Shanghai）

## 当前接口

- `GET /api/v1/health`
- `GET /api/v1/models` — 分析模型白名单 + 默认（只返回模型名，不含网关地址/密钥）
- `GET /api/v1/model-health` — 进程内 LLM 模型健康度快照（运维用）
- `GET /api/v1/search-sources` — 检索源开关状态
- `GET /api/v1/source-capabilities` — Provider Doctor 快照（仅检查配置与本地依赖，不访问外网）
- `GET /api/v1/agent-trace/{run_id}` — supervisor span trace 只读导出（`AGENT_TRACE_ENABLED=true` 才启用）
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream` — NDJSON 流式事件

同一进程通过 `request_context.mode=fast|deep` 提供两档分析，详见主 [README.md](../README.md#两档核查--秒级-vs-分钟级)。

深度推理按来源索引、摘要和原文片段组织证据，并对完整提示统一预算。上下文消耗诊断、配置与经审核的核查策略库见 [证据上下文与核查经验](../docs/evidence-context.md)。

## 本地运行

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

默认地址：`http://127.0.0.1:8000`

## 环境变量

**默认基线**（零 key、可复现）：

```dotenv
ANALYSIS_PROVIDER=off
RETRIEVAL_PROVIDER=mock
RETRIEVAL_FALLBACK_TO_MOCK=true
```

**启用真实检索 + LLM**：模型/端点/密钥只放 git 忽略的 `backend/.env`，不写入 `.env.example` 或版本库。

**检索层可调参数**：

- `RETRIEVAL_TIMEOUT_SECONDS`（默认 12s 读超时）
- `RETRIEVAL_MAX_RESULTS`
- `RETRIEVAL_CACHE_ENABLED` / `RETRIEVAL_CACHE_TTL_SECONDS` / `RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR` / `RETRIEVAL_CACHE_DIR`
- `RETRIEVAL_GDELT_BASE_URL`
- `LLM_SEARCH_MODEL`
- `XHS_SEARCH_ENABLED` / `TOUTIAO_SEARCH_ENABLED` / `SOGOU_WEIXIN_SEARCH_ENABLED` / `PIYAO_SEARCH_ENABLED`

**Provider 枚举**：`mock | playwright | gdelt | kimi | off`。对照说明见主 [README.md](../README.md#接口与运行路径)。

`google_news_rss_provider.py` 当前是未接入 `RetrievalService` 的实验实现，`RETRIEVAL_GOOGLE_NEWS_ENDPOINT` 仅为该实现预留；不要把它当作可选 `RETRIEVAL_PROVIDER` 值。

**证据质量增强（可选，默认关，失败自动回退）**：

- `EVIDENCE_RERANK_ENABLED` / `EVIDENCE_EMBED_MODEL` / `EVIDENCE_EMBED_API_KEY` — 语义证据重排。开启后证据按 embedding 余弦相似度重排(语义主导 + `authority_score` 微调),替代纯字面打分;embedding 走现有 LLM 网关但用独立 key。未配置/超时/异常时静默回退 `evidence_ranker` 的字面打分。详见主 [README.md](../README.md#语义证据重排--治字面撞词)
- `RENDERED_FETCH_ENABLED` — 真浏览器抓正文兜底。静态 httpx 抓回空壳时用 Playwright 无头 Chromium 渲染 JS 页面(如 163/微博)再抽取。需先 `pip install playwright && playwright install chromium`;整条路径异常隔离,失败降级到搜索摘要。详见主 [README.md](../README.md#抓取正文--三层降级链路)

**运行时缓存**（`data/cache/` 下）：

- 检索缓存：`data/cache/retrieval/<provider>/<cache_key>.json`；key = `sha256(v1|provider|compact_query)` 前 24 位
- URL 正文缓存：`data/cache/url_fetch/<cache_key>.json`；key = `sha256(v1|url)` 前 24 位；TTL 由 `URL_FETCH_CACHE_TTL_SECONDS` 控制（默认 12h）
- 抓取可靠性：正文抓取走 `reliable_get`，对**瞬时故障**（连接/读超时、连接错误、5xx）做退避重试，次数由 `URL_FETCH_MAX_RETRIES` 控制（默认 1，保守）；4xx（含 403/429）视为确定答复**不重试**，避免对明确拒绝的站点反复敲门。每次请求用独立短连接（会话隔离）。**只借鉴可靠性设计，不做任何绕过反爬**。
- SearXNG 补充源（默认关）：`SEARXNG_SEARCH_ENABLED=true` 且配置 `SEARXNG_BASE_URL` 后，`SearxngSearchProvider` 走该独立实例的 `/search?format=json` 扩英文/海外来源覆盖。**AGPL：只作为独立 HTTP 服务调用，绝不并入本仓代码**（见 ADR 0004）。任何失败降级为空、不影响其他源。当前为脚手架，未接真实实例验证。
- 诊断入口：`request_context.retrieval_cache_only=true` 强制只读缓存；`bypass_retrieval_cache=true` 跳过缓存直连 provider
- Provider Doctor：`python backend/scripts/source_doctor.py`；加 `--json` 输出机器可读快照，加 `--strict` 检查所有已配置来源的本地依赖。该命令不访问外网。
- 模型调用账本（默认关）：`MODEL_LEDGER_ENABLED=true` 后，每次 LLM 补全在 `data/model_ledger/model-calls-<日期>.jsonl` 追加一行：`provider/model/input_tokens/output_tokens/cache_tokens/latency_ms/status/error_class/trace_id/stage_key`。补 in-flight `TokenUsage` 之不足（后者一次请求后即丢）。**脱敏红线：只记 token 计数与模型名，绝不写原始 prompt/正文、绝不写网关 host/endpoint/key**；写入前还有一层按 key/value 的敏感词兜底剔除。账本故障不影响主流程。

## 最小联调

```bash
curl http://127.0.0.1:8000/api/v1/health

curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"raw_input": "网传某地出台新规，要求周末全面停工整顿。", "input_type": "text"}'

curl -X POST http://127.0.0.1:8000/api/v1/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"raw_input": "最近某公司裁员 40% 了吗？", "input_type": "question"}'
```

## 边界

- URL 输入以公开 HTML 页面为主（不支持登录页、强反爬、PDF、图片正文）；JS 渲染页在 `RENDERED_FETCH_ENABLED=true`（可选，需装 Playwright）时由无头浏览器兜底
- verdict / timeline 基于检索结果的规则+启发式，不是完整 agent 搜证系统
- `Report.provenance.source_type` 当前只输出 `backend_live` 或 `backend_mock`
- 共享契约以 [../contracts/report.schema.json](../contracts/report.schema.json) 为准

## LLM 推理与日志

- **共享 httpx client**：`LlmAgentReasoner._client` 是模块级 singleton（`_SHARED_HTTPX_CLIENT`），跨请求复用连接池，避免 per-request TLS 握手浪费。见 `backend/app/services/agent_reasoner.py::_get_shared_client`
- **health-aware failover**：`_candidate_models` 通过 `get_model_health_registry().order_by_health()` 排序候选，健康模型优先；不健康模型不 drop 而是排到后面（picker override 例外）
- **空返回短路**：单候选连续 2 次 empty 直接 break，避免耿同学/Nature 撤稿类 case 里 3 次 timeout 共花 2m 40s。见 `backend/tests/test_stream_completion.py::test_empty_streak_shortcircuits_when_only_one_candidate`
- **规则兜底证据回填**：LLM synthesis 空返回 3 次时若 pool 里有 ≥3 条 B/A/S 高信度证据，`_backfill_rule_fallback_evidence` 会将 top 3 附给主 fact claim，避免"20+ 证据但报告只挂 1 条"
- **JSON 结构化日志**（opt-in）：`APP_LOG_FORMAT=json` 切换到 `_JsonFormatter`（`backend/app/core/logging.py`）。每行一个 JSON，`timestamp` / `level` / `logger` / `message` + 任意 `extra={run_id, stage_key, model}` 作为顶层字段。默认 `text` 走原有人类可读格式，无回归
