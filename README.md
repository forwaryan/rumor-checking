# rumor-checking

一个面向真实用户的新闻/传闻核查产品（含面试演示与 V1 交付）。

更新时间：2026-07-23（Asia/Shanghai）

## 当前基线

- 默认开发路径：`ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`
- 默认演示路径：与默认开发路径一致，优先保证 `零 key / 可复现 / 可回归`
- 可选增强路径：显式打开 `ANALYSIS_PROVIDER=kimi` 并配置 `LLM_API_KEY`（模型/端点由 `backend/.env` 决定）
- 可选真实联网检索：`RETRIEVAL_PROVIDER=playwright`（抓取百度/Bing 搜索结果页，无需额外依赖）
- 当前没有公开的 `replay` 或 `demo-cases` HTTP 接口
- 前端 demo 卡片只负责填充输入，不再走本地 demo payload 回放

## 当前结论

- 前端是面向普通用户的单页核查产品：搜索态输入一条消息，结果态给出判定卡片，并把逐条核查、证据、时间线折叠成可展开区块，执行过程 trace 折叠在底部。
- 前端支持文本、URL、问题三类输入，并通过流式接口消费后端执行过程。
- 后端已提供 `GET /api/v1/health`、`POST /api/v1/analyze`、`POST /api/v1/analyze/stream`。
- `report.provenance.source_type` 当前只会出现 `backend_live` 或 `backend_mock`。
- 默认冻结基线仍是 `off + mock + fallback=true`，适合稳定联调和回归。
- 真实联网检索优先走 `RETRIEVAL_PROVIDER=playwright`（抓取百度/Bing），中文覆盖较好且不依赖模型内建搜索；延迟高于 mock，不作为默认路径。

## 文档入口

- 当前已核验状态：[docs/status/current-verified-state.md](./docs/status/current-verified-state.md)
- 提问分析全链路：[docs/question-analysis-end-to-end-flow.md](./docs/question-analysis-end-to-end-flow.md)
- 演示前检查：[SMOKE_CHECKLIST.md](./SMOKE_CHECKLIST.md)
- 演示脚本：[DEMO_SCRIPT.md](./DEMO_SCRIPT.md)
- 后端说明：[backend/README.md](./backend/README.md)
- 前端说明：[frontend/README.md](./frontend/README.md)
- 协议说明：[contracts/README.md](./contracts/README.md)
- 数据与缓存：[data/README.md](./data/README.md)
- 评测与最小回归：[evals/README.md](./evals/README.md)
- 总导航：[docs/README.md](./docs/README.md)

历史性的任务拆分、执行提案、Prompt 归档和规则草案已从当前文档面移除；现在仓库只保留和现行代码、运行、演示直接相关的文档。

## 环境要求

- Python：`>= 3.8`
- Node.js：`>= 18.18.0`，建议 `>= 20.9.0`

## 默认环境变量

推荐先复制：

```bash
cp backend/.env.example backend/.env
```

默认基线：

```dotenv
ANALYSIS_PROVIDER=off
RETRIEVAL_PROVIDER=mock
RETRIEVAL_FALLBACK_TO_MOCK=true
```

如果要启用可选的 LLM 分析增强，再补充（模型/端点/密钥都放 git 忽略的 `backend/.env`）：

```dotenv
ANALYSIS_PROVIDER=kimi
LLM_API_KEY=你的真实 key
LLM_BASE_URL=你的网关端点
LLM_MODEL=你的模型名
```

> 说明：`ANALYSIS_PROVIDER=kimi` 只是历史遗留的开关字面量，不代表具体供应商；LLM 调用层已供应商中立，走标准 OpenAI 兼容 `chat/completions`。

如果要启用真实联网检索（抓取百度/Bing，无需额外依赖）：

```dotenv
RETRIEVAL_PROVIDER=playwright
RETRIEVAL_FALLBACK_TO_MOCK=true
```

## 标准命令

### 1. 启动后端

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

默认地址：`http://127.0.0.1:8000`

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:3020`

如果是在 Windows 下通过 `\\wsl.localhost\...` 访问仓库，优先使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

### 3. 运行测试

后端回归：

```bash
pytest backend/tests -q
```

前端检查：

```bash
cd frontend
npm install
npm run typecheck
npm test
```

如果仓库当前跑在 `\\wsl.localhost\...` 且 WSL Node 版本过低，改用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\run-local-windows-checks.ps1 -BackendUrl http://127.0.0.1:8000
```

## 当前运行路径

| 路径 | 关键环境变量 | 适合做什么 | 边界口径 |
| --- | --- | --- | --- |
| `default dev / demo` | `ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`、`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` | 默认开发、联调、回归、演示、新人上手 | 零 key、可复现；结果标 `backend_mock`，不讲成真实检索 |
| `enhanced demo` | 额外加 `ANALYSIS_PROVIDER=kimi` 与 `LLM_API_KEY` / `LLM_MODEL`（放 `backend/.env`） | 在 mock 检索基线上，用 LLM 增强标题/摘要/claim/grounded 判定 | 检索仍是 mock，不是真实联网 |
| `agent orchestrator` | 额外加 `AGENT_ORCHESTRATOR_ENABLED=true`（可再加 `LIGHTWEIGHT_AGENT_ENABLED=true`） | 走可插拔 agent 循环；配 LLM 时 LLM planner 在岔路口决策 | 未配 LLM 时等价于固定 pipeline（RulePlanner 保 parity） |
| `real live（推荐 playwright）` | `RETRIEVAL_PROVIDER=playwright`、`ANALYSIS_PROVIDER=kimi`、`AGENT_ORCHESTRATOR_ENABLED=true` | 真实联网调查：抓取百度/Bing 搜索结果页 → grounded 判定，结果标 `backend_live + retrieval_live` | 中文覆盖较好、无需模型内建搜索；检索多条 query 已并发，单轮约等于最慢一条；延迟仍高于 mock，不作为默认路径 |

### `real live` 路径注意事项

- **优先用 `playwright` 检索**：纯 httpx 抓取百度（主）+ Bing（兜底）搜索结果页，不依赖浏览器二进制，也不依赖模型内建联网搜索，中文覆盖较好。
- **检索已并发**：一轮 query plan 的多条 query 会并发抓取，单轮检索墙钟时间约等于最慢一条，不再随 query 条数线性增长；`RETRIEVAL_TIMEOUT_SECONDS`（默认 12s）即单条抓取的读超时，死连接会快速失败，通常无需再放宽。首次冷启动的主要耗时来自 LLM 判定/synthesis，不是检索。
- **`kimi` 检索分支需模型支持内建 `$web_search`**：当前所用新模型/网关无此能力，故真实联网优先走 `playwright`。
- **判定模型要选 key 能访问的**：用 `GET /v1/models` 确认；模型名/端点只放 `backend/.env`，不写入代码或文档。
- 完整配方也在 [backend/.env.example](./backend/.env.example) 注释里。

## 当前边界

- 前端当前只消费后端返回的真实 `Report`，不会额外请求 `replay`，也不会读取本地 demo payload。
- `mock` 路径仍会明确展示 provenance，避免误讲成实时联网结果。
- `unknown` 只用于缺失或不完整 provenance 的保守展示。
- URL 输入当前只支持公开 HTML 页面，不支持登录页、强反爬、浏览器渲染页面、PDF 和图片正文。
- 演示口径：`mock demo` 稳、可复现、零 key，适合默认展示；`real live` 已联调通过，讲的时候要如实说明"延迟高、非默认、需按配方配置"，别讲成随手就能实时跑。
