# Frontend

本目录提供 rumor-checking 的 Next.js 单页前端。

更新时间：2026-07-23（Asia/Shanghai）

## 当前实现

- 面向普通用户的单页核查产品，分两个视图：**搜索态**（居中输入框 + 示例卡片 + 后端状态点）和**结果态**（判定卡片 + 可折叠的逐条核查/证据/时间线 + 底部执行过程 trace）。
- 页面输入支持 `text / url / question`（默认 `auto`）
- 页面通过 `POST /api/v1/analyze/stream` 获取流式分析过程
- 页面启动时通过 `GET /api/v1/health` 判断后端状态
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
