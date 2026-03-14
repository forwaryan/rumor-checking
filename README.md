# rumor-checking

一个面向面试演示和 V1 交付的新闻核查工作台。

你给它一段新闻、一个链接或一个问题，系统会尽量输出：

- 事件摘要
- 可核查的 claim 列表
- `supported / refuted / insufficient / conflicting` 这类 verdict
- 关键传播节点时间线
- 风险提示与证据列表

当前最适合把它理解成：**一个已经能跑、能演示、能解释边界的 V1 工作台**。
它还不是一个已经完成真实 URL 抽取、reasoning-grounded analyze 和开放场景稳定验收的通用新闻事实核查系统。

## 当前能演示什么

截至 2026-03-14，仓库里已经稳定可演示的能力有：

- 前端单页工作台，支持文本、URL、问题三种输入入口
- `GET /api/v1/health` 和 `POST /api/v1/analyze` 真实联调
- `complete_mode / partial_mode / safe_mode` 三档模式表达
- 结构化结果展示：事件卡片、时间线、claim、证据、风险
- 可选 `RETRIEVAL_PROVIDER=gdelt` 的公开来源检索、缓存和最小真实时间线
- 三条稳定 demo case
- 后端失败或离线时，demo case 可回退到本地 payload
- 前后端共享 contract，以及最小测试基线

如果你只是要做一场 5 到 10 分钟 demo，这些已经够用。
如果你要证明“任意新闻都能完成真实传播链还原”，当前还不够。

## 三条推荐 demo case

| case | 模式 | 输入 | 最适合讲什么 |
| --- | --- | --- | --- |
| `expired-yogurt` | `complete_mode` | 海州酸奶抽检事件 | 主流程通了，结构化结果和关键节点都能展示 |
| `chemical-odor` | `partial_mode` | 化工厂异味核查 | 冲突证据与边界表达，不硬判 |
| `morningstar-layoff` | `safe_mode` | 裁员传闻提问 | 证据不足时保守收口，不伪造结论 |

详细操作顺序、口播主线、每条 case 的“推荐讲法 / 不要说过头的地方”，见 [DEMO_SCRIPT.md](/home/forwaryan/mianshi/rumor-checking/DEMO_SCRIPT.md)。

## 推荐演示入口

如果你是第一次进仓库，建议按这个顺序读：

1. 先看 [DEMO_SCRIPT.md](/home/forwaryan/mianshi/rumor-checking/DEMO_SCRIPT.md)，知道应该怎么讲。
2. 再看 [frontend/README.md](/home/forwaryan/mianshi/rumor-checking/frontend/README.md) 和 [backend/README.md](/home/forwaryan/mianshi/rumor-checking/backend/README.md)，知道怎么跑。
3. 最后看 [overview/09_stage-progress-and-task-audit.md](/home/forwaryan/mianshi/rumor-checking/overview/09_stage-progress-and-task-audit.md) 和 [overview/08_origin_problem_gap_and_demo_strategy.md](/home/forwaryan/mianshi/rumor-checking/overview/08_origin_problem_gap_and_demo_strategy.md)，知道当前能力和原题之间还差什么。

## G2/G3/G4 第一阶段骨架入口

下面这三份是本轮刚补上的“文档结构草案”，作用是先把后续收口位置固定下来：

- replay 格式草案与目录落点：[data/demos/README.md](/home/forwaryan/mianshi/rumor-checking/data/demos/README.md)
- 运行方式与环境变量章节骨架：[overview/11_runtime-and-env-outline.md](/home/forwaryan/mianshi/rumor-checking/overview/11_runtime-and-env-outline.md)
- 限制与降级边界章节骨架：[overview/12_limits-and-degradation-outline.md](/home/forwaryan/mianshi/rumor-checking/overview/12_limits-and-degradation-outline.md)

注意：这三份文档当前只冻结结构、目录和待补段落；涉及 URL 正文抽取、reasoning-grounded analyze、随机 case 验收的最终口径，仍要等 `C10 / C11 / F8` 后再定稿。

## 快速启动

### 1. 启动后端

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

默认地址：`http://127.0.0.1:8000`

如果需要启用 Kimi provider，再补这些环境变量：

```text
ANALYSIS_PROVIDER=kimi
KIMI_API_KEY=你的真实 key
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-8k
PROVIDER_TIMEOUT_SECONDS=20
```

如需启用公开来源检索，再补这些环境变量：

```text
RETRIEVAL_PROVIDER=gdelt
RETRIEVAL_TIMEOUT_SECONDS=12
RETRIEVAL_CACHE_ENABLED=true
RETRIEVAL_FALLBACK_TO_MOCK=true
```

注意：当前 `ANALYSIS_PROVIDER=kimi` 只负责“事件理解 + claim 抽取”增强；真实检索由 `RETRIEVAL_PROVIDER=gdelt` 负责。URL 正文抽取仍未完成。

### 2. 启动前端

标准方式：

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:3020`

如果你是在 Windows 下通过 `\\wsl.localhost\...` 访问仓库，Next.js 文件监听可能不稳定。此时优先使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1
```

### 3. 打开页面并演示

- 页面启动时会先检查后端 `health`
- 提交分析时优先走真实 `POST /api/v1/analyze`
- 如果后端离线或请求失败，预设 demo case 会回退到本地 payload
- 如果是普通输入且请求失败，页面会保守回退到 `safe_mode`

这意味着：

- 想看真实链路，先起后端
- 想求稳做演示，三条 demo case 即使在后端失败时也能兜底

## 当前系统是怎么工作的

当前主链路可以先粗略理解成：

```text
Frontend AnalyzePage
  -> POST /api/v1/analyze
  -> InputNormalizer
  -> ProviderEnricher（可选 Kimi）
  -> RetrievalService（可选 GDELT + Cache + Mock Fallback）
  -> ClaimExtractor
  -> VerdictEngine
  -> TimelineBuilder
  -> ReportBuilder
  -> Report
```

前端再把 `Report` 渲染成：

- 状态条
- 事件卡片
- 时间线
- claim 表
- 证据列表
- 风险提示

如果你要看更完整的实现说明：

- 前端详见 [frontend/IMPLEMENTATION_SUMMARY.md](/home/forwaryan/mianshi/rumor-checking/frontend/IMPLEMENTATION_SUMMARY.md)
- 后端详见 [backend/docs/api-foundation-implementation-record.md](/home/forwaryan/mianshi/rumor-checking/backend/docs/api-foundation-implementation-record.md)
- 代码现状总览详见 [overview/06_current_code_implementation.md](/home/forwaryan/mianshi/rumor-checking/overview/06_current_code_implementation.md)

## 当前限制与不要过度宣称的地方

下面这些边界建议直接写进演示口径，不要省略：

- 不要说系统已经完成任意新闻的真实传播链还原
- 不要说当前 verdict 已经完全建立在真实互联网证据检索上
- 不要说 URL 输入已经稳定支持正文抓取
- 不要把 demo payload 回退结果说成“实时分析结果”
- 不要把 `safe_mode` 解释成“系统已经证明这条传闻是假的”

当前还没有完成的关键能力包括：

- `C10`：URL 正文抽取
- `C11`：把 analyze 主链从场景占位推进到更真实的 reasoning-grounded 流程
- `F2 / F3 / F4 / F6`：按 eval 文件驱动的分层回归
- `F8`：稳定 demo 与随机 case 的最终通过记录
- `E9`：结果来源与 provenance 展示
- `G2`：replay 数据格式与使用说明

## 演示前检查清单状态

`F7` 的独立 smoke checklist 文档已经交付：

- [SMOKE_CHECKLIST.md](/home/forwaryan/mianshi/rumor-checking/SMOKE_CHECKLIST.md)

当前建议的演示前顺序是：

- 先按 [SMOKE_CHECKLIST.md](/home/forwaryan/mianshi/rumor-checking/SMOKE_CHECKLIST.md) 做环境、接口、页面和 fallback 检查
- 再按 [DEMO_SCRIPT.md](/home/forwaryan/mianshi/rumor-checking/DEMO_SCRIPT.md) 过口播顺序
- 如需确认后端状态，本轮已验证 `pytest backend/tests -q` 通过，结果为 `28 passed`

仍待补齐的不是 checklist 文档本身，而是：

- 带真实公网请求的 GDELT smoke 记录
- `C10` URL 正文抽取路径的 smoke 记录

## 推荐阅读路径

按“第一次进仓库的人”最省时间的顺序，建议这样读：

1. [DEMO_SCRIPT.md](/home/forwaryan/mianshi/rumor-checking/DEMO_SCRIPT.md)
2. [SMOKE_CHECKLIST.md](/home/forwaryan/mianshi/rumor-checking/SMOKE_CHECKLIST.md)
3. [frontend/README.md](/home/forwaryan/mianshi/rumor-checking/frontend/README.md)
4. [backend/README.md](/home/forwaryan/mianshi/rumor-checking/backend/README.md)
5. [overview/09_stage-progress-and-task-audit.md](/home/forwaryan/mianshi/rumor-checking/overview/09_stage-progress-and-task-audit.md)
6. [overview/08_origin_problem_gap_and_demo_strategy.md](/home/forwaryan/mianshi/rumor-checking/overview/08_origin_problem_gap_and_demo_strategy.md)
7. [overview/07_quality-and-demo-baseline.md](/home/forwaryan/mianshi/rumor-checking/overview/07_quality-and-demo-baseline.md)
8. [frontend/IMPLEMENTATION_SUMMARY.md](/home/forwaryan/mianshi/rumor-checking/frontend/IMPLEMENTATION_SUMMARY.md)
9. [backend/docs/api-foundation-implementation-record.md](/home/forwaryan/mianshi/rumor-checking/backend/docs/api-foundation-implementation-record.md)

## 仓库目录怎么理解

- `frontend/`：单页演示工作台
- `backend/`：FastAPI 分析链路
- `contracts/`：前后端共享 schema 和 demo payload
- `evals/`：最小测试集和 case 资产
- `overview/`：对外说明文档和现状总览
- `tasks/`：并行协作任务板和状态回写

## 当前一句话判断

这个仓库现在已经足够支撑“有产品、有实现、有边界”的面试演示。
最稳的交付方式不是把它包装成已经全部完成，而是把它清楚地说明为：**一个能跑、能演示、能交代边界的 rumor-checking V1。**

