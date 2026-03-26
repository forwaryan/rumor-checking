# Backend

本目录承载 rumor-checking 的后端主链路。

更新时间：2026-03-26（Asia/Shanghai）

## 当前接口

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`

## 当前状态

- 默认运行基线已冻结为 `ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`
- 已接入公开 HTML 页面 URL 正文抽取
- 已接入流式分析事件输出，前端通过 `analyze/stream` 消费执行轨迹
- 当前没有公开的 `demo-cases` 或 `replay` 接口
- `Report.provenance.source_type` 当前只会输出 `backend_live` 或 `backend_mock`

## 环境与默认基线

```dotenv
ANALYSIS_PROVIDER=off
RETRIEVAL_PROVIDER=mock
RETRIEVAL_FALLBACK_TO_MOCK=true
```

如需启用 Kimi 分析增强，再显式配置：

```dotenv
ANALYSIS_PROVIDER=kimi
KIMI_API_KEY=你的真实 key
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-8k
PROVIDER_TIMEOUT_SECONDS=20
```

## 检索 provider

- `RETRIEVAL_PROVIDER=mock`：稳定回归
- `RETRIEVAL_PROVIDER=gdelt`：公开 GDELT 检索，失败时可回退到 mock
- `RETRIEVAL_PROVIDER=agent` 或 `kimi`：走 Kimi 联网搜索，再整理为 retrieval hits
- `RETRIEVAL_PROVIDER=off`：关闭检索，只保留保守链路

相关环境变量：

- `RETRIEVAL_TIMEOUT_SECONDS`
- `RETRIEVAL_GDELT_BASE_URL`
- `RETRIEVAL_MAX_RESULTS`
- `KIMI_SEARCH_MODEL`
- `RETRIEVAL_CACHE_ENABLED`
- `RETRIEVAL_CACHE_TTL_SECONDS`
- `RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR`
- `RETRIEVAL_FALLBACK_TO_MOCK`
- `RETRIEVAL_CACHE_DIR`

## URL 输入边界

- 只支持公开 HTML 页面
- 不支持登录页、强反爬页面、浏览器渲染页面、PDF/图片正文
- 抽取失败时仍会返回保守结果和明确 fallback 提示

## 最小联调

```bash
curl http://127.0.0.1:8000/api/v1/health
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "raw_input": "网传某地出台新规，要求周末全面停工整顿。",
    "input_type": "text"
  }'
```

流式联调：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{
    "raw_input": "最近某公司裁员 40% 了吗？",
    "input_type": "question"
  }'
```

## 本地运行

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

默认地址：`http://127.0.0.1:8000`

## 当前已知边界

- verdict 和 timeline 仍是基于检索结果的规则/启发式判断，不是完整 agent 搜证系统
- `live probe` 仍只用于内部诊断，不代表真实检索已通过最终验收
- 共享协议仍以 [contracts/report.schema.json](/home/forwaryan/mianshi/rumor-checking/contracts/report.schema.json) 为准
