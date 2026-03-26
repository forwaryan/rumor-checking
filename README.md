# rumor-checking

一个面向面试演示和 V1 交付的新闻核查工作台。

更新时间：2026-03-26（Asia/Shanghai）

## 当前基线

- 默认开发路径：`ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`
- 默认演示路径：与默认开发路径一致，优先保证 `零 key / 可复现 / 可回归`
- 可选增强路径：显式打开 `ANALYSIS_PROVIDER=kimi` 并配置 `KIMI_API_KEY`
- 当前没有公开的 `replay` 或 `demo-cases` HTTP 接口
- 前端 demo 卡片只负责填充输入，不再走本地 demo payload 回放

## 当前结论

- 前端支持文本、URL、问题三类输入，并通过流式接口实时展示后端执行过程。
- 后端已提供 `GET /api/v1/health`、`POST /api/v1/analyze`、`POST /api/v1/analyze/stream`。
- `report.provenance.source_type` 当前只会出现 `backend_live` 或 `backend_mock`。
- 默认冻结基线仍是 `off + mock + fallback=true`，适合稳定联调和回归。
- `live probe` 只用于内部诊断，当前不能对外宣称真实检索链路已完成最终验收。

## 文档入口

- 当前已核验状态：[docs/status/current-verified-state.md](/home/forwaryan/mianshi/rumor-checking/docs/status/current-verified-state.md)
- 提问分析全链路：[docs/question-analysis-end-to-end-flow.md](/home/forwaryan/mianshi/rumor-checking/docs/question-analysis-end-to-end-flow.md)
- 演示前检查：[SMOKE_CHECKLIST.md](/home/forwaryan/mianshi/rumor-checking/SMOKE_CHECKLIST.md)
- 演示脚本：[DEMO_SCRIPT.md](/home/forwaryan/mianshi/rumor-checking/DEMO_SCRIPT.md)
- 后端说明：[backend/README.md](/home/forwaryan/mianshi/rumor-checking/backend/README.md)
- 前端说明：[frontend/README.md](/home/forwaryan/mianshi/rumor-checking/frontend/README.md)
- 协议说明：[contracts/README.md](/home/forwaryan/mianshi/rumor-checking/contracts/README.md)
- 数据与缓存：[data/README.md](/home/forwaryan/mianshi/rumor-checking/data/README.md)
- 评测与最小回归：[evals/README.md](/home/forwaryan/mianshi/rumor-checking/evals/README.md)
- 总导航：[docs/README.md](/home/forwaryan/mianshi/rumor-checking/docs/README.md)

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

如果要启用可选的 Kimi 分析增强，再补充：

```dotenv
ANALYSIS_PROVIDER=kimi
KIMI_API_KEY=你的真实 key
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

| 路径 | 关键环境变量 | 适合做什么 | 当前不能怎么讲 |
| --- | --- | --- | --- |
| `default dev` | `ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`、`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` | 默认开发、联调、回归和新人上手路径 | 不能讲成真实检索已通过最终验收 |
| `default demo` | 与 `default dev` 保持一致 | 当前推荐的可交付演示路径 | 不能讲成 `real_live` 路径 |
| `enhanced demo` | 额外加 `ANALYSIS_PROVIDER=kimi` 与 `KIMI_API_KEY` | 在不改变 retrieval 基线的前提下增强标题、摘要和 claim 抽取 | 仍然不是 `real_live` 检索通过口径 |
| `live probe` | `RETRIEVAL_PROVIDER=gdelt`、`RETRIEVAL_FALLBACK_TO_MOCK=false` | 只用于内部诊断，观察是否真的出现 `backend_live + retrieval_live` | 当前不能作为对外交付路径 |

## 当前边界

- 前端当前只消费后端返回的真实 `Report`，不会额外请求 `replay`，也不会读取本地 demo payload。
- `mock` 路径仍会明确展示 provenance，避免误讲成实时联网结果。
- `unknown` 只用于缺失或不完整 provenance 的保守展示。
- URL 输入当前只支持公开 HTML 页面，不支持登录页、强反爬、浏览器渲染页面、PDF 和图片正文。
- 如果今天要上台，当前最稳的口径仍是：`Go / 讲 mock demo + 边界`，`No-Go / 讲真实检索较真`。
