# rumor-checking

一个面向面试演示和 V1 交付的新闻核查工作台。

截至 2026-03-14，按 `overview/13_f8-random-acceptance.md` 的正式验收记录，当前可交付口径是：仓库已经具备可运行的前后端、可选 provider / retrieval 和明确的 provenance 标签，但稳定可演示的是 `mock/demo` 路径，不是“真实检索已对随机新闻稳定较真”。

## 当前结论

- 前端支持文本、URL、问题三类输入，并能展示 `backend_live / backend_mock / backend_replay / demo_payload / frontend_fallback` 来源标签。
- 后端已支持 `GET /api/v1/health`、`POST /api/v1/analyze`、公开 HTML URL 抽取、可选 Kimi enrichment、可选 GDELT 检索和 `report.provenance`。
- `F8` 正式验收已经落库：默认环境下样本主要落在 `backend_mock / retrieval_mock`，当前唯一可稳定讲的 demo 是 `expired-yogurt`。
- `chemical-odor` 已从预期 `partial_mode` 漂移到 `safe_mode`，`morningstar-layoff` 已从预期 `safe_mode` 漂移到 `complete_mode`；两者当前都不应作为稳定 demo 对外口播。
- live probe 在 `RETRIEVAL_PROVIDER=gdelt` 且 `RETRIEVAL_FALLBACK_TO_MOCK=false` 的条件下实测为 `0/4 real_live`，当前不能对外宣称真实检索链路已通过最终验收。
- 后端仍没有公开的 `demo-cases` / `replay` HTTP 接口，replay 不是当前可交付运行路径。

## 文档入口

- 当前运行路径与环境变量：[overview/11_runtime-and-env-outline.md](overview/11_runtime-and-env-outline.md)
- 当前限制与降级边界：[overview/12_limits-and-degradation-outline.md](overview/12_limits-and-degradation-outline.md)
- `F8` 最终验收记录：[overview/13_f8-random-acceptance.md](overview/13_f8-random-acceptance.md)
- 演示前检查：[SMOKE_CHECKLIST.md](SMOKE_CHECKLIST.md)
- 演示脚本：[DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- 后端说明：[backend/README.md](backend/README.md)
- 前端说明：[frontend/README.md](frontend/README.md)
- 总导航：[docs/README.md](docs/README.md)
- 代码核验后的当前状态：[docs/status/current-verified-state.md](docs/status/current-verified-state.md)

## 最小启动命令

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

该脚本会自动设置 `NEXT_PUBLIC_API_BASE_URL`。

## 当前运行路径

| 路径 | 关键环境变量 | 适合做什么 | 当前不能怎么讲 |
| --- | --- | --- | --- |
| `mock demo` | `ANALYSIS_PROVIDER=kimi`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`、`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` | 当前推荐的可交付路径。可讲 mock demo、页面 provenance 标签和 fallback 边界。 | 不能讲成真实检索已通过最终验收；默认环境不是 `real_live` 路径。 |
| `live probe` | 在上述基础上改为 `RETRIEVAL_PROVIDER=gdelt`、`RETRIEVAL_FALLBACK_TO_MOCK=false` | 只用于内部诊断，观察是否真的出现 `backend_live + retrieval_live`。 | `F8` 实测 `0/4 real_live`，不能作为对外演示通过口径。 |
| `replay` | 无新增公开变量；仅后端内部 request-level 开关与文件草案 | 只可保留为内部调试或后续扩展方向。 | 当前没有公开 `replay` HTTP 接口，也没有正式交付流程。 |
| `frontend fallback` | 后端离线或请求失败时无需额外变量 | 可作为保底演示，demo 卡片回退到 `demo_payload`，普通输入回退到 `frontend_fallback` 的 `safe_mode`。 | 不能讲成真实 analyze 结果，也不能替代 live 验收。 |

## 当前边界

- `live` 只在 `source_type=backend_live` 且 `evidence_source=retrieval_live` 且没有 fallback 时成立。
- `mock` 包括 `backend_mock`、`retrieval_mock`、`request_mock` 等联调或演示路径。
- `replay` 只有后端显式返回 `backend_replay` 才成立；前端不会额外发 replay 请求。
- `fallback` 包括后端 `fallback_used=true` 或 `evidence_source=none`，以及前端本地 `demo_payload / frontend_fallback`。
- URL 输入当前只支持公开 HTML 页面，不支持登录页、强反爬、浏览器渲染页面、PDF 和图片正文。
- 如果今天要上台，当前最稳的结论是：`Go / 讲 mock demo + 边界`，`No-Go / 讲真实检索较真`。
