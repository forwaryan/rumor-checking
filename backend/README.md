# Backend

本目录承载 rumor-checking 的后端主链路。

更新时间：2026-07-23（Asia/Shanghai）

## 当前接口

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`

## 分析档位（按请求选择）

两个接口都读取 `request_context.mode`，同一个后端进程同时提供两档：

- `mode="fast"`（默认，缺省或未知值都按 fast 处理）：**零 LLM 规则路径**。跳过 agent 编排、resolve/synthesize/investigation、provider 结构化补全和 LLM query 抽取；只做真实联网检索（`playwright`）+ 规则 verdict。实测约 0.2–0.3s，`source_type=backend_live`、真实来源 URL。适合给真实用户当下就能用的实时核查。
- `mode="deep"`：走现有 LLM/agent-first 全链路（planner/investigation/synthesis/结构化补全）。判定质量更高，但在当前网关上一次 synthesis 就要 ~200s（约 0.7s/token），整轮通常要几分钟，属于异步/后台深度档，不作为默认。

> mode 只切换分析深度；检索 provider 仍由 `RETRIEVAL_PROVIDER` 决定，两档都走同一套真实检索。

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

如需启用 LLM 分析增强，再显式配置（模型/端点/密钥都放 git 忽略的 `backend/.env`，不写入版本库）：

```dotenv
ANALYSIS_PROVIDER=kimi
LLM_API_KEY=你的真实 key
LLM_BASE_URL=你的 OpenAI 兼容网关端点
LLM_MODEL=你的模型名
PROVIDER_TIMEOUT_SECONDS=20
```

> `ANALYSIS_PROVIDER=kimi` 只是历史遗留的开关字面量，不代表具体供应商；调用层已供应商中立，走标准 OpenAI 兼容 `chat/completions` 流式接口。

## 检索 provider

- `RETRIEVAL_PROVIDER=mock`：稳定回归（默认）
- `RETRIEVAL_PROVIDER=playwright`：纯 httpx 抓取百度（主）+ Bing（兜底）搜索结果页，中文覆盖较好，无需额外依赖（**当前推荐的真实联网路径**）
- `RETRIEVAL_PROVIDER=gdelt`：公开 GDELT 检索（英文偏向），失败时可回退到 mock
- `RETRIEVAL_PROVIDER=kimi`：走 LLM 内建 `$web_search`（仅对支持该工具的供应商有效；当前新模型无此能力）
- `RETRIEVAL_PROVIDER=off`：关闭检索，只保留保守链路

相关环境变量：

- `RETRIEVAL_TIMEOUT_SECONDS`
- `RETRIEVAL_GDELT_BASE_URL`
- `RETRIEVAL_MAX_RESULTS`
- `LLM_SEARCH_MODEL`
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
- 共享协议仍以 [contracts/report.schema.json](../contracts/report.schema.json) 为准
