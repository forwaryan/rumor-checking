# Backend

FastAPI 主进程。产品能力/两档核查/概率维度看主 [README.md](../README.md)；这里只讲后端目录本身的接口、运行方式和边界。

更新时间：2026-08-03（Asia/Shanghai）

## 当前接口

- `GET /api/v1/health`
- `GET /api/v1/models` — 分析模型白名单 + 默认（只返回模型名，不含网关地址/密钥）
- `GET /api/v1/model-health` — 进程内 LLM 模型健康度快照（运维用）
- `GET /api/v1/search-sources` — 检索源开关状态
- `GET /api/v1/agent-trace/{run_id}` — supervisor span trace 只读导出（`AGENT_TRACE_ENABLED=true` 才启用）
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream` — NDJSON 流式事件

同一进程通过 `request_context.mode=fast|deep` 提供两档分析，详见主 [README.md](../README.md#两档核查--秒级-vs-分钟级)。

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

**Provider 枚举**：`mock | playwright | gdelt | kimi | off`。对照说明见主 [README.md](../README.md#接口与运行路径)。

**运行时缓存**（`data/cache/` 下）：

- 检索缓存：`data/cache/retrieval/<provider>/<cache_key>.json`；key = `sha256(v1|provider|compact_query)` 前 24 位
- URL 正文缓存：`data/cache/url_fetch/<cache_key>.json`；key = `sha256(v1|url)` 前 24 位；TTL 由 `URL_FETCH_CACHE_TTL_SECONDS` 控制（默认 12h）
- 诊断入口：`request_context.retrieval_cache_only=true` 强制只读缓存；`bypass_retrieval_cache=true` 跳过缓存直连 provider

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

- URL 输入只支持公开 HTML 页面（不支持登录页、强反爬、浏览器渲染页、PDF、图片正文）
- verdict / timeline 基于检索结果的规则+启发式，不是完整 agent 搜证系统
- `Report.provenance.source_type` 当前只输出 `backend_live` 或 `backend_mock`
- 共享契约以 [../contracts/report.schema.json](../contracts/report.schema.json) 为准

## LLM 推理与日志

- **共享 httpx client**：`LlmAgentReasoner._client` 是模块级 singleton（`_SHARED_HTTPX_CLIENT`），跨请求复用连接池，避免 per-request TLS 握手浪费。见 `backend/app/services/agent_reasoner.py::_get_shared_client`
- **health-aware failover**：`_candidate_models` 通过 `get_model_health_registry().order_by_health()` 排序候选，健康模型优先；不健康模型不 drop 而是排到后面（picker override 例外）
- **空返回短路**：单候选连续 2 次 empty 直接 break，避免耿同学/Nature 撤稿类 case 里 3 次 timeout 共花 2m 40s。见 `backend/tests/test_stream_completion.py::test_empty_streak_shortcircuits_when_only_one_candidate`
- **规则兜底证据回填**：LLM synthesis 空返回 3 次时若 pool 里有 ≥3 条 B/A/S 高信度证据，`_backfill_rule_fallback_evidence` 会将 top 3 附给主 fact claim，避免"20+ 证据但报告只挂 1 条"
- **JSON 结构化日志**（opt-in）：`APP_LOG_FORMAT=json` 切换到 `_JsonFormatter`（`backend/app/core/logging.py`）。每行一个 JSON，`timestamp` / `level` / `logger` / `message` + 任意 `extra={run_id, stage_key, model}` 作为顶层字段。默认 `text` 走原有人类可读格式，无回归
