# 演示前 Smoke Checklist

适用对象：主控、演示者、临时接手机器的同学

更新时间：2026-07-19（Asia/Shanghai）

## Go / No-Go

- `Go / 讲 mock demo + 边界`：页面能打开，后端可用，`expired-yogurt` 可跑，来源标签正常
- `Go / 讲 real live`：真实检索（推荐 `playwright`）已联调通过，但需按 real-live 配方配置且时延高，讲的时候要如实标注"非默认、需配置、慢"
- `No-Go / 讲交互式演示`：后端起不来，或页面无法跑出真实 `Report`

## 1. 先决定今天走哪条路径

[ ] 明确今天是 `mock demo`（默认、稳、零 key）还是 `real live`（真实联网、需配方、慢）

检查：

- 对外演示默认走 `mock demo`
- 走 `real live` 前先确认已按第 7 节配好（模型、超时、key），并接受单次可能超 120s 的时延

## 2. 环境与启动

[ ] Python `>= 3.8`

[ ] Node.js `>= 18.18.0`

[ ] 后端可启动

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

[ ] 前端可启动

```bash
cd frontend
npm install
npm run dev
```

如果仓库通过 `\\wsl.localhost\...` 挂到 Windows 下，优先使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

## 3. 默认基线确认

[ ] 当前默认环境仍是：

- `ANALYSIS_PROVIDER=off`
- `RETRIEVAL_PROVIDER=mock`
- `RETRIEVAL_FALLBACK_TO_MOCK=true`

[ ] 演示者知道这代表 `mock` 路径，不是 `real_live` 通过口径

## 4. 后端接口检查

[ ] `GET /api/v1/health` 正常

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health | ConvertTo-Json -Depth 4
```

[ ] `POST /api/v1/analyze` 正常

```powershell
$body = @{
  raw_input = '3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。'
  input_type = 'text'
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/analyze -ContentType 'application/json; charset=utf-8' -Body $body | ConvertTo-Json -Depth 8
```

[ ] `POST /api/v1/analyze/stream` 正常

```powershell
$body = @{
  raw_input = '晨星生物裁员40%是真的吗？'
  input_type = 'question'
} | ConvertTo-Json
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8000/api/v1/analyze/stream -ContentType 'application/json; charset=utf-8' -Body $body
```

## 5. 前端页面检查

[ ] 页面能打开：`http://127.0.0.1:3000`（裸 `next dev` 默认端口；Windows 脚本走 `-Port 3020`）

[ ] 页面顶部能看到后端状态

[ ] 运行任一样例后，页面能看到来源标签，且只会落到以下三类之一：

- `backend_live`
- `backend_mock`
- `unknown`

## 6. 推荐样例检查

[ ] `expired-yogurt` 可稳定跑通

[ ] `morningstar-question` 只作为受控补充，不进默认主线

[ ] `viral-death-ambiguous` 能稳定停在 `safe_mode`

[ ] 不把 `chemical-odor`、`morningstar-layoff` 排进默认主线

## 7. real live 路径（真实联网，非默认）

[ ] 如果要走真实检索，把 `backend/.env` 显式切到当前推荐的 playwright 配方：

- `RETRIEVAL_PROVIDER=playwright`、`RETRIEVAL_FALLBACK_TO_MOCK=true`（纯 httpx 抓百度/Bing，无需浏览器二进制）
- `AGENT_ORCHESTRATOR_ENABLED=true`
- 判定层可选：`ANALYSIS_PROVIDER=kimi` + `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`（模型/端点/密钥只放 git 忽略的 `backend/.env`）
- `RETRIEVAL_TIMEOUT_SECONDS`（默认 12s，单条抓取读超时；多条 query 已并发，单轮约等于最慢一条）

> 注：早期 `RETRIEVAL_PROVIDER=kimi`（模型内建 `$web_search`）依赖供应商内建搜索，当前网关无此能力，真实联网优先走 `playwright`。

[ ] 演示者知道：这条路会标 `backend_live + retrieval_live`；fast 档约 0.2–0.3s，deep 档因 LLM synthesis 首调可达几分钟，不适合无缓存的快速演示

## 8. 当前不再保留的保底链路

[ ] 团队明确知道：

- 当前没有公开 `replay` 接口
- 当前前端不会读取本地 demo payload
- 后端请求失败时，页面不会再伪造本地报告壳

## 9. 最终判断

[ ] 如果后端、前端、`expired-yogurt` 和 provenance 标签都正常：`Go / 讲 mock demo + 边界`

[ ] 如果后端起不来或 analyze 不能返回真实 `Report`：`No-Go / 讲交互式演示`
