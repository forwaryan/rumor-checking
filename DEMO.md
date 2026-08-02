# 演示脚本 + 演示前 Smoke

更新时间：2026-08-03（Asia/Shanghai）

**适用对象**：主控 / 演示者 / 临时接手机器的同学
**目标**：把 mock demo 演清楚；需要真跑 live 时按第 6 节配方切换。

---

## Go / No-Go

- ✅ **Go / mock demo + 边界**：页面能打开，后端可用，`expired-yogurt` 可跑，来源标签正常
- ✅ **Go / real live**：真实检索（`playwright`）已按配方配置；接受单次 120s+ 时延
- ⛔ **No-Go / 交互式演示**：后端起不来，或页面无法返回真实 `Report`

## 1. 决定走哪条路径

明确今天是 **`mock demo`**（默认、稳、零 key）还是 **`real live`**（真实联网、需配方、慢）。

- 对外演示默认走 `mock demo`
- 走 `real live` 前先按第 6 节配好（模型、超时、key），并接受单次可能超 120s 的时延

## 2. 环境启动

- Python `>= 3.12`（CI 用 3.12）
- Node.js `>= 20.9.0`（`frontend/.nvmrc` 锁定为 20.9.0）

```bash
# 后端
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload

# 前端
cd frontend && npm install && npm run dev
```

若通过 `\\wsl.localhost\...` 挂到 Windows：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

## 3. 默认基线确认

```dotenv
ANALYSIS_PROVIDER=off
RETRIEVAL_PROVIDER=mock
RETRIEVAL_FALLBACK_TO_MOCK=true
```

演示者知道这是 `mock` 路径，**不是**"真实检索已通过"口径。

## 4. 接口 Smoke 检查

```bash
curl http://127.0.0.1:8000/api/v1/health

curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"raw_input": "3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期。", "input_type": "text"}'
```

**前端页面检查**：`http://127.0.0.1:3000` 能打开，顶部能看到后端状态；任一样例跑完后来源标签只落到 `backend_live` / `backend_mock` / `unknown` 三者之一。

## 5. 主线样例

### 5.1 `expired-yogurt`（**默认主线**，产品版首选）

```text
3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。
```

**讲什么**：把一段新闻拆成结构化结果——事件摘要 / claim / 时间线 / 证据 / 风险提示，同时明确标注 provenance（`backend_mock` vs `backend_live`）。

**不要讲**：
- 不要说"这已经证明真实互联网检索稳定通过"
- 不要只讲 `complete_mode`，不讲 provenance
- 不要把时间线讲成完整传播链还原

### 5.2 `morningstar-question`（答辩补充，不进默认开场）

```text
晨星生物裁员40%是真的吗？
```

**讲什么**：问句输入会先改写成待核查 claim，再结合 retrieval 决定哪些能被反驳、哪些保留边界（question-first + partial 边界）。

### 5.3 `viral-death-ambiguous`（`safe_mode` 边界演示）

```text
最近有个女网红脑出血死了真的假的？
```

**讲什么**：证据不够时系统宁可停在 `safe_mode`，不会把模糊传闻包装成确定性判断。

### 5.4 不进默认主线

`chemical-odor` / `morningstar-layoff`：不排进默认主线，稳定性未收口。

## 6. real live 路径（真实联网，非默认）

要走真实检索，把 `backend/.env` 切到 playwright 配方（模型/端点/密钥只放 git 忽略的 `backend/.env`）：

```dotenv
RETRIEVAL_PROVIDER=playwright
RETRIEVAL_FALLBACK_TO_MOCK=true
AGENT_ORCHESTRATOR_ENABLED=true
ANALYSIS_PROVIDER=kimi
LLM_API_KEY=（你的真实 key）
LLM_BASE_URL=（你的 OpenAI 兼容网关端点）
LLM_MODEL=（你的模型名）
RETRIEVAL_TIMEOUT_SECONDS=12
```

演示者要知道：
- **fast 档** ~0.2–0.3s；**deep 档** LLM synthesis 首调可达几分钟，不适合无缓存快速演示
- 结果会标 `backend_live + retrieval_live`
- 内网网关地址是硬密码，永不写入代码或文档

> 早期 `RETRIEVAL_PROVIDER=kimi`（模型内建 `$web_search`）依赖供应商能力，当前网关不支持，真实联网优先走 `playwright`。

## 7. 不再保留的保底链路

- 没有公开 `replay` 接口
- 前端不读本地 demo payload
- 后端请求失败时页面不伪造本地报告壳；只展示错误态与重试入口

## 8. 常见追问

**Q：现在能查任意新闻了吗？**
> 还不能这么说。当前正式稳定的是 mock 基线下的结构化核查能力 + provenance 边界。真实检索链路走 real live 配方能出真实结果，但延迟高、非默认。

**Q：如果后端挂了，页面还能演示吗？**
> 不再保留本地 payload 回放。后端起不来时页面只有错误态和静态壳，不能讲成"完整交互演示"。

**Q：为什么不直接让 LLM 给一个真假概率？**
> 每条 claim 已经带了 `truth_probability` + `probability_basis`（evidence / prior）。但产品要的不只是一个数——还包括传播链还原、claim 拆解、证据挂靠，所以先做结构化流水线，再谈概率。

## 9. 最终判断

- 后端、前端、`expired-yogurt`、provenance 标签都正常 → **Go / mock demo + 边界**
- 后端不可用或 analyze 不返回真实 `Report` → **No-Go / 交互式演示**
