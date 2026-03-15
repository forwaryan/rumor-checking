# rumor-checking

一个面向面试演示和 V1 交付的新闻核查工作台。

更新时间：2026-03-15（Asia/Shanghai）

本仓库当前冻结的默认基线是：

- 默认开发路径：`ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`
- 默认演示路径：与默认开发路径保持一致，优先保证 `零 key / 可复现 / 可回归`
- 可选增强路径：在默认演示路径基础上显式打开 `ANALYSIS_PROVIDER=kimi` 并配置 `KIMI_API_KEY`
- `live probe` 仍只用于内部诊断，不能对外讲成“真实检索已通过最终验收”

## 当前结论

- 前端支持文本、URL、问题三类输入，并能展示 `backend_live / backend_mock / backend_replay / demo_payload / frontend_fallback` 来源标签。
- 后端已支持 `GET /api/v1/health`、`POST /api/v1/analyze`、公开 HTML URL 抽取、`mock / gdelt / kimi / off` 检索分流、provider 回退和 `report.provenance`。
- 默认基线已恢复到 `off + mock + fallback=true`，`pytest backend/tests -q` 当前实测 `63 passed`。
- `W-G` 已冻结高分路线样例矩阵：`expired-yogurt` 作为对外 `complete` 主线，`morningstar-question` 作为受控 `partial` 回归，`viral-death-ambiguous` 作为 `safe` 边界 case。
- `F8` 正式验收记录仍保留在 [overview/13_f8-random-acceptance.md](/home/forwaryan/mianshi/rumor-checking/overview/13_f8-random-acceptance.md)；它是 `2026-03-14` 的历史验收，不再代表 `2026-03-15` 起冻结的默认开发基线。
- `chemical-odor` 已从预期 `partial_mode` 漂移到 `safe_mode`，`morningstar-layoff` 已从预期 `safe_mode` 漂移到 `complete_mode`；两者当前都不应作为稳定 demo 对外口播。
- live probe 在 `RETRIEVAL_PROVIDER=gdelt` 且 `RETRIEVAL_FALLBACK_TO_MOCK=false` 的条件下实测为 `0/4 real_live`，当前不能对外宣称真实检索链路已通过最终验收。
- 后端仍没有公开的 `demo-cases` / `replay` HTTP 接口，replay 不是当前可交付运行路径。

## 文档入口

- 当前运行路径与环境变量：[overview/11_runtime-and-env-outline.md](overview/11_runtime-and-env-outline.md)
- 当前限制与降级边界：[overview/12_limits-and-degradation-outline.md](overview/12_limits-and-degradation-outline.md)
- `F8` 最终验收记录：[overview/13_f8-random-acceptance.md](overview/13_f8-random-acceptance.md)
- 高分路线样例与回归入口：[overview/14_high-score-golden-cases.md](overview/14_high-score-golden-cases.md)
- 演示前检查：[SMOKE_CHECKLIST.md](SMOKE_CHECKLIST.md)
- 演示脚本：[DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- 后端说明：[backend/README.md](backend/README.md)
- 前端说明：[frontend/README.md](frontend/README.md)
- 总导航：[docs/README.md](docs/README.md)
- 代码核验后的当前状态：[docs/status/current-verified-state.md](docs/status/current-verified-state.md)

## 高分路线入口

- 对外主线：`expired-yogurt`，重点讲双主流程、结构化输出和 provenance。
- 受控回归：`morningstar-question`，重点讲 question-first、反驳型 claim 和 partial 边界。
- 边界演示：`viral-death-ambiguous` 或前端 fallback，重点讲“不强判”“证据不足”和风险提示。

如果你只准备一条最稳主线，就讲 `expired-yogurt + provenance + fallback`；如果评委追问系统边界，再补另外两条受控 case。

## 环境要求

- Python：`>= 3.8`
  当前已在 `Python 3.8.10` 下跑通 `backend/tests` 全量回归。
- Node.js：`>= 18.18.0`，建议 `>= 20.9.0`
  `frontend/package.json` 当前使用 `next@15.5.12`。若当前环境低于该版本，先升级 Node 再跑前端命令。

## 默认环境变量

推荐先复制：

```bash
cp backend/.env.example backend/.env
```

默认基线写法：

```dotenv
ANALYSIS_PROVIDER=off
RETRIEVAL_PROVIDER=mock
RETRIEVAL_FALLBACK_TO_MOCK=true
```

如果要启用可选的 Kimi 分析增强，再显式补充：

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

该脚本会自动设置 `NEXT_PUBLIC_API_BASE_URL`。

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

### 4. 运行演示

1. 启动后端 `http://127.0.0.1:8000`
2. 启动前端 `http://127.0.0.1:3020`
3. 打开页面后运行 `expired-yogurt`

## 当前运行路径

> 说明：各实现线程可能临时切换 `.env` 做排障或 live probe。开始演示前，不要假设当前 shell 环境就是对外交付环境，先按 [SMOKE_CHECKLIST.md](SMOKE_CHECKLIST.md) 选路。

| 路径 | 关键环境变量 | 适合做什么 | 当前不能怎么讲 |
| --- | --- | --- | --- |
| `default dev` | `ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`、`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` | 默认开发、联调、回归和新人上手路径。 | 不能讲成真实检索已通过最终验收。 |
| `default demo` | 与 `default dev` 保持一致 | 当前推荐的可交付演示路径。可讲 mock demo、页面 provenance 标签和 fallback 边界。 | 不能讲成 `real_live` 路径。 |
| `enhanced demo` | 在默认演示路径基础上显式加 `ANALYSIS_PROVIDER=kimi` 与 `KIMI_API_KEY` | 在不改变 retrieval 基线的前提下增强标题、摘要和 claim 抽取。 | 仍然不是 `real_live` 检索通过口径。 |
| `live probe` | `RETRIEVAL_PROVIDER=gdelt`、`RETRIEVAL_FALLBACK_TO_MOCK=false`；如需 Kimi 再单独配置 | 只用于内部诊断，观察是否真的出现 `backend_live + retrieval_live`。 | `F8` 实测 `0/4 real_live`，不能作为对外演示通过口径。 |
| `replay` | 无新增公开变量；仅后端内部 request-level 开关与文件草案 | 只可保留为内部调试或后续扩展方向。 | 当前没有公开 `replay` HTTP 接口，也没有正式交付流程。 |
| `frontend fallback` | 后端离线或请求失败时无需额外变量 | 可作为保底演示，demo 卡片回退到 `demo_payload`，普通输入回退到 `frontend_fallback` 的 `safe_mode`。 | 不能讲成真实 analyze 结果，也不能替代 live 验收。 |

## 当前边界

- `live` 只在 `source_type=backend_live` 且 `evidence_source=retrieval_live` 且没有 fallback 时成立。
- `mock` 包括 `backend_mock`、`retrieval_mock`、`request_mock` 等联调或演示路径。
- `replay` 只有后端显式返回 `backend_replay` 才成立；前端不会额外发 replay 请求。
- `fallback` 包括后端 `fallback_used=true` 或 `evidence_source=none`，以及前端本地 `demo_payload / frontend_fallback`。
- URL 输入当前只支持公开 HTML 页面，不支持登录页、强反爬、浏览器渲染页面、PDF 和图片正文。
- 如果今天要上台，当前最稳的结论是：`Go / 讲 mock demo + 边界`，`No-Go / 讲真实检索较真`。

## 为什么不是直接让 LLM 给真假概率

因为题目不是单点真假分类，而是两条主流程同时成立：

- 要解释传播链，就必须给时间线节点、来源和 `why_selected`，不能只给一个概率。
- 要解释内容核查，就必须把整段输入拆成 claim，并把“事实 / 观点 / 可能有误”分开。
- 要避免误导，就必须把 `live / mock / replay / fallback` 说清楚；否则模型哪怕给出一个分数，也会把边界讲混。

所以当前产品的策略是：先给结构化核查结果、来源边界和风险提示；可信度分字段已经进 contract，但在未计算完成前允许显式空值，而不是伪造精确分。

## AI 原生协作与多线程方法

这套仓库当前的 AI 使用方式，不是“让模型一次性输出真假”，而是把它放在可解释的协作链里：

- `claim-first`：先拆 claim，再做 verdict 和摘要。
- `retrieval-first`：先组织证据层和传播节点，再决定能讲到什么程度。
- `provenance-first`：每次输出都标明它来自 `live / mock / replay / fallback` 的哪条路径。
- `regression-first`：用 golden cases、Smoke 和 Demo Script 把“能讲什么、不能讲什么”冻结下来。

对应的高分路线入口见 [overview/14_high-score-golden-cases.md](overview/14_high-score-golden-cases.md)。
