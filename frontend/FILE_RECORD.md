# Cluster-E / Experience Shell 文件记录

更新时间：2026-03-13 19:16（Asia/Shanghai）

## 1. 记录目的

本文件记录当前 `Cluster-E / Experience Shell` 前端实现阶段已经落下的代码文件、每个文件的职责边界、与后端联调的关系，以及当前验证结论。

这份记录面向后续继续开发、联调、验收和窗口交接，重点回答三个问题：

1. 现在有哪些代码文件已经形成稳定落点。
2. 每个文件负责什么，不负责什么。
3. 下一步继续推进时，应该优先改哪些文件。

## 2. 当前阶段结论

当前前端已经从“纯本地 mock 壳”推进到“真实 analyze 优先，本地 payload 兜底”的阶段：

- 示例输入已经对齐当前后端 scenario。
- 页面优先调用真实 `POST /api/v1/analyze`。
- 后端离线或请求失败时，若当前是 demo 输入，则回退到同主题本地 payload。
- 若不是 demo 输入，则回退到通用 `safe_mode` fallback。

当前后端真实已存在的接口只有：

- `GET /api/v1/health`
- `POST /api/v1/analyze`

当前前端**不再依赖**缺失的 `demo-cases / replay` 后端接口才能演示页面。

## 3. 本次记录覆盖范围

本次记录覆盖两类内容：

- `frontend/` 下的 Next.js 单页壳实现。
- 为前端渲染提供稳定输入的 `contracts/` schema 与 demo payload。

不覆盖以下工作区变更：

- `backend/` 下其他窗口已经在推进的 schema、service 和模型改动。
- Python `__pycache__/` 等运行副产物。

## 4. 详细文件记录

### 4.1 共享协议与 Demo 数据

| 文件 | 当前职责 | 关键内容 | 后续通常由谁继续改 |
| --- | --- | --- | --- |
| `contracts/event.schema.json` | 冻结前端消费的 `Event` 协议 | 约束 `title / summary / source_url / source_name / published_at / keywords / mode` | `T-impl-api`、`T-impl-web` |
| `contracts/timeline_node.schema.json` | 冻结时间线节点协议 | 约束 `node_type / title / url / source_name / published_at / summary / why_selected` | `T-impl-api` |
| `contracts/evidence.schema.json` | 冻结证据来源协议 | 定义 `title / url / source_name / published_at / snippet / relevance_reason / source_tier` | `T-impl-api`、`T-test` |
| `contracts/claim_result.schema.json` | 冻结 claim 核查结果协议 | 定义 `claim_type / verdict / confidence / evidence / notes` | `T-impl-api` |
| `contracts/report.schema.json` | 冻结顶层 `Report` 协议 | 统一 `mode / event / timeline / claim_results / final_summary / risks / sources` | `T-impl-api`、`T-impl-web` |
| `contracts/demo_payloads/complete_mode_report.json` | 完整模式本地 demo payload | 主题已对齐后端 `expired_yogurt` 场景，用于后端离线时本地回放 | `T-impl-web`、`T-demo` |
| `contracts/demo_payloads/partial_mode_report.json` | 部分模式本地 demo payload | 主题已对齐后端 `chemical_odor` 场景，包含 `conflicting` verdict | `T-impl-web`、`T-demo` |
| `contracts/demo_payloads/safe_mode_report.json` | 安全模式本地 demo payload | 主题已对齐后端 `morningstar_layoff` 提问场景，强调证据不足与空时间线 | `T-impl-web`、`T-demo` |

补充说明：

- 三份 demo payload 现在不再是独立于后端的自造案例，而是与后端真实 scenario 对齐的离线回退版本。
- 后端一旦改变字段名或模式切换规则，优先先改 `contracts/` 和后端 schema，再同步前端。

### 4.2 前端工程与配置文件

| 文件 | 当前职责 | 关键内容 | 后续通常由谁继续改 |
| --- | --- | --- | --- |
| `frontend/package.json` | 定义前端依赖与脚本 | 当前使用 `next@15.5.12`、`react@19.2.4`、`react-dom@19.2.4`；脚本为 `dev / build / start / typecheck` | `T-impl-web` |
| `frontend/tsconfig.json` | TypeScript 编译边界 | 开启严格模式、JSON 导入、`@/*` 路径别名 | `T-impl-web` |
| `frontend/next-env.d.ts` | Next.js TS 环境声明 | 标准 `next` 类型声明 | 一般无需手改 |
| `frontend/next.config.ts` | Next.js 工程配置 | 打开 `externalDir`，允许从 `frontend/` 读取上层 `contracts/` | `T-impl-web` |
| `frontend/.gitignore` | 前端本地忽略规则 | 忽略 `node_modules / .next / out` 等产物 | 一般无需手改 |
| `frontend/README.md` | 前端运行与协作说明 | 已更新为真实 `analyze / health` 接口假设和 demo 回退策略 | `T-doc`、`T-impl-web` |
| `frontend/tsconfig.tsbuildinfo` | TypeScript 增量检查副产物 | 由 `tsc --noEmit` 自动更新；不是业务源代码 | 不建议手工维护 |

补充说明：

- 没有继续使用 `next@latest`，因为当前机器 Node 为 `18.19.0`，而 Next 16 需要 `>=20.9.0`。
- `next.config.ts` 的 `externalDir` 是当前前端直接读取 `contracts/demo_payloads/*.json` 的关键配置。

### 4.3 前端类型、Demo 注册与 API 层

| 文件 | 当前职责 | 关键内容 | 后续通常由谁继续改 |
| --- | --- | --- | --- |
| `frontend/types/report.ts` | 前端类型总入口 | 定义 `Report / Event / TimelineNode / Evidence / ClaimResult / DemoCase`，并把 `AnalyzeRequest` 对齐到真实后端 `raw_input / input_type` | `T-impl-web` |
| `frontend/lib/demo-cases.ts` | 本地 demo 索引层 | 注册 `expired-yogurt / chemical-odor / morningstar-layoff` 三条与后端 scenario 对齐的示例输入与本地 payload | `T-impl-web`、`T-demo` |
| `frontend/lib/report-utils.ts` | 前端模式与展示辅助函数 | 负责 mode 文案、时间格式化、confidence 展示、输入校验、fallback report 生成、证据聚合 | `T-impl-web` |
| `frontend/lib/api-client.ts` | 后端 API client 与本地 demo 访问层 | 当前只请求真实 `analyze / health`，`getDemoCases()` 返回本地示例摘要，`getDemoReport()` 提供离线 fallback | `T-impl-web`、`T-impl-api` |

补充说明：

- `api-client.ts` 默认请求 `http://localhost:8000/api/v1/*`，可通过 `NEXT_PUBLIC_API_BASE_URL` 覆盖。
- 当前前端不再主动请求不存在的 `GET /api/v1/demo-cases` 或 `POST /api/v1/replay`。
- `report-utils.ts` 中的 `buildFallbackReport()` 仍然保留，用于“非 demo 输入 + 后端失败”时的通用安全模式回退。

### 4.4 前端页面组件层

| 文件 | 当前职责 | 关键内容 | 后续通常由谁继续改 |
| --- | --- | --- | --- |
| `frontend/components/mode-pill.tsx` | 模式标签组件 | 根据 `complete_mode / partial_mode / safe_mode` 输出统一标签 | `T-impl-web` |
| `frontend/components/input-panel.tsx` | 输入区组件 | 管理输入类型切换、文本框、demo 选择、提交按钮、后端健康提示；文案已改为“真实 analyze 优先，本地 payload 兜底” | `T-impl-web` |
| `frontend/components/status-banner.tsx` | 状态条组件 | 展示 `idle / submitting / complete / partial / safe_mode / error` 状态文案及重试入口 | `T-impl-web` |
| `frontend/components/event-card.tsx` | 事件概览卡片 | 展示事件标题、一句话总结、来源、关键词、模式标签 | `T-impl-web` |
| `frontend/components/risk-panel.tsx` | 风险与边界面板 | 展示当前模式边界、风险列表、节点数/claim 数/来源数统计 | `T-impl-web` |
| `frontend/components/timeline-panel.tsx` | 时间线组件 | 对时间线节点排序并按节点类型渲染关键来源时间线，处理空态 | `T-impl-web` |
| `frontend/components/claim-table.tsx` | claim 核查表 | 展示 claim、claim_type、verdict、confidence、notes、证据数量 | `T-impl-web` |
| `frontend/components/evidence-list.tsx` | 证据列表 | 聚合顶层 `sources` 与 claim 级 evidence，按时间倒序输出来源卡片 | `T-impl-web` |
| `frontend/components/analyze-page.tsx` | 页面状态编排层 | 管理健康检查、demo 选择、真实 `analyze` 提交、离线本地 payload fallback、通用 safe fallback、各组件组装 | `T-impl-web` |

补充说明：

- `analyze-page.tsx` 是当前前端最核心的调度文件。
- 如果后续要接真实轮询、取消请求、缓存、query client 或 reducer，优先从这里抽离，而不是让子组件各自发请求。

### 4.5 Next.js 页面入口与视觉样式

| 文件 | 当前职责 | 关键内容 | 后续通常由谁继续改 |
| --- | --- | --- | --- |
| `frontend/app/layout.tsx` | 根布局 | 注入全局样式和页面 metadata | `T-impl-web` |
| `frontend/app/page.tsx` | 单页入口 | 直接挂载 `AnalyzePage` | `T-impl-web` |
| `frontend/app/globals.css` | 全局视觉与布局样式 | 定义页面主题、背景、卡片、表格、证据卡、时间线、移动端适配 | `T-impl-web` |

## 5. 当前功能闭环状态

当前前端已经形成以下闭环：

1. 单页入口可加载。
2. 输入区可切换 `auto / text / url / question`。
3. 三条示例输入已对齐当前后端 scenario。
4. 示例输入提交时优先走真实 `POST /api/v1/analyze`。
5. `GET /api/v1/health` 会驱动前端在线/离线提示。
6. demo 场景在后端离线或请求失败时，会回退到同主题本地 payload。
7. 非 demo 输入在接口失败时，会回退到通用 `safe_mode` fallback。
8. 时间线、claim 表、证据列表和风险提示都已有空态与边界文案。

## 6. 当前未完成或待继续项

以下内容仍属于下一阶段任务：

- 真实后端返回结构与前端 parser 的最终联调验收。
- 更细的错误码、请求超时、取消请求和并发提交保护。
- 如果后端未来补 `demo-cases / replay` 接口，决定是否恢复远端 demo 索引能力。
- 组件级测试、页面 smoke test、视觉回归记录。
- 如果后续要接真实 schema 校验库，还需要补前后端同源校验方案。

## 7. 验证记录

### 7.1 已完成验证

- 依赖安装：已完成。
- TypeScript 检查：已通过。
- Next.js 生产构建：已通过。

### 7.2 具体验证结论

1. `frontend/package.json` 依赖已调整为 Node 18 可运行的组合：`next@15.5.12 + react@19.2.4 + react-dom@19.2.4`。
2. 直接在当前 `\\wsl.localhost\...` 工作区上用 Windows Node 运行 `next build`，会触发 WSL 挂载路径上的 `readlink` 兼容问题。
3. 将 `frontend/` 与 `contracts/` 复制到 Windows 本机临时目录后，`npm run build` 成功通过，说明当前失败不是业务代码错误，而是路径/运行时环境问题。

### 7.3 当前推荐验证方式

- 开发期：优先在 WSL 内或 Windows 本机盘符路径下跑前端命令。
- 如果继续通过 Windows Node 操作 `\\wsl.localhost\...` 路径，构建类命令仍可能复现同类兼容问题。

## 8. 当前工作区观察（避免串线）

当前工作区还存在以下非本记录主范围内的变更：

- `backend/app/models/schemas.py`
- `backend/app/services/input_normalizer.py`
- `backend/app/services/report_builder.py`
- `backend/app/services/scenario_library.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/verdict_engine.py`

处理原则：

- 这些文件属于其他线程的实现面，不应在继续做前端任务时顺手覆盖。
- 如果后续前端联调需要依赖这些后端文件，先看字段兼容性，再决定是否协同改动。

## 9. 后续继续任务时的建议切入点

如果下一步继续推进 `Cluster-E`，建议按以下优先级继续：

1. 先确认真实后端 `Report` 输出与前端 parser 在所有 scenario 下都一致。
2. 再给 `analyze-page.tsx` 增加更细的 loading / abort / retry 策略。
3. 如需提升演示稳定性，优先补前端 smoke test 与 parser test。
4. 如果后端以后补齐 `demo-cases / replay`，再决定是否恢复远端 demo 注册能力。
