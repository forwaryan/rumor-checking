# Frontend

本目录提供 rumor-checking 的 Next.js 单页前端。

更新时间：2026-07-23（Asia/Shanghai）

## 当前实现

- 面向普通用户的单页核查产品，分两个视图：**搜索态**（居中输入框 + 示例卡片 + 后端状态点）和**结果态**（判定卡片 + 可折叠的逐条核查/证据/时间线 + 底部执行过程 trace）。
- 页面输入支持 `text / url / question`（默认 `auto`）
- **两档核查**：主"核查"按钮走 `fast`（默认，秒级、零 LLM 规则路径），请求带 `request_context.mode=fast`；结果页出现"深度核查（较慢）"入口，点击后带 `mode=deep` 走 LLM/agent 全链路（展示"可能需要几分钟"的加载态）。
- **可观测执行过程**：结果态把流式事件按步骤聚合成执行时间线（`lib/trace-steps.ts`），每步显示"干了什么/输入/输出/结论"；每次 LLM 调用的提问与回答有"人类可读 / 原始 JSON"两个 tab。
- **多可能性 + 为真概率**：结果态在判定卡片下方新增"可能性分布"区块（渲染 `investigation.possibilities`：有 `probability` 时画百分比条形分布，否则显示分类 likelihood chip，每行带"有证据/凭常识"basis 标签）；逐条核查每条 claim 旁展示"为真 N%"+ basis。deep 档给 LLM 常识概率与合计≈100 的情形分布，fast 档给规则粗概率、不伪造整体分布。
- **可选模型**：深度核查入口带模型下拉（数据来自 `GET /api/v1/models` 白名单），选中的模型随请求 `request_context.model` 发送；查询、mode、model 都写进 URL（`?q=&mode=&model=`），刷新/分享可复现（fast 秒级重跑、deep 会重新跑几分钟）。
- 页面通过 `POST /api/v1/analyze/stream` 获取流式分析过程
- 页面启动时通过 `GET /api/v1/health` 判断后端状态，并拉 `GET /api/v1/models` 填充模型下拉
- 示例卡片只负责填充稳定输入样例，不再读取本地 demo payload
- provenance 当前只消费 `backend_live`、`backend_mock`，缺失 provenance 时按 `unknown` 保守展示
- 展示逻辑已收敛到单一组件 `components/analyze-page.tsx`（早期十余个面板组件已移除）

## 当前不再保留的路径

- 不再请求 `GET /api/v1/demo-cases`
- 不再请求 `POST /api/v1/replay`
- 不再使用 `demo_payload / frontend_fallback / backend_replay` 作为运行时来源标签
- 不再从 `contracts/demo_payloads/` 读取本地报告 JSON

## 当前依赖的后端能力

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`

## 运行方式

标准方式：

```bash
cd frontend
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:3020
```

如果仓库通过 `\\wsl.localhost\...` 挂到 Windows 下运行，优先使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

验证命令：

```bash
npm test
npm run typecheck
npm run build
```

如果当前 WSL Node 版本过低，改用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\run-local-windows-checks.ps1 -BackendUrl http://127.0.0.1:8000
```

## 目录说明

- `app/`：页面入口、根布局与全局样式（移动端优先，约 300 行）
- `components/`：`analyze-page.tsx` 单一页面组件（搜索态 + 结果态）
- `lib/`：API client、解析与展示辅助逻辑
- `types/`：前端消费的 `Report` 类型

## 协作约束

- 共享字段结构以 [contracts/report.schema.json](../contracts/report.schema.json) 为准
- `next.config.ts` 的 `externalDir` 仍保留，用于允许前端读取仓库上层共享文件
- 当前前端不会自行伪造本地报告；如果后端请求失败，页面直接展示错误态与重试入口
