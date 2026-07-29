# Frontend

Next.js 单页前端。产品能力/两档/概率维度看主 [README.md](../README.md)；这里只讲前端目录本身的运行方式、目录结构和边界。

更新时间：2026-07-29（Asia/Shanghai）

## 当前实现

- 面向普通用户的单页核查产品，两个视图：**搜索态**（居中输入框 + 示例卡片 + 后端状态点）和**结果态**（判定卡片 + 可折叠的逐条核查/证据/时间线 + 底部执行 trace）
- 主"核查"按钮走 `fast`，结果页给"深度核查（较慢）"入口触发 `deep`
- 通过 `POST /api/v1/analyze/stream` 消费流式事件；按 `stage_key` 聚合成执行时间线（`lib/trace-steps.ts`），每步展开可看"干了什么/输入/输出/结论"
- `query / mode / model` 都写进 URL（`?q=&mode=&model=`），刷新/分享可复现

## 运行

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:3000`

WSL/Windows 挂载路径下优先用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

WSL Node 版本过低时改用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\run-local-windows-checks.ps1 -BackendUrl http://127.0.0.1:8000
```

## 验证命令

```bash
npm run typecheck
npm test
npm run build
```

## 目录

- `app/` — Next.js 页面入口、根布局、全局样式
- `components/` — `analyze-page.tsx`（编排）+ `verdict-card` / `claim-list` / `evidence-list` / `possibilities-section` / `search-input` / `timeline-section` / `trace-timeline`
- `lib/` — API client、解析、展示辅助
- `types/` — 前端消费的 `Report` 类型

## 依赖后端接口

- `GET /api/v1/health`
- `GET /api/v1/models`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`

## 边界

- 共享字段结构以 [../contracts/report.schema.json](../contracts/report.schema.json) 为准
- `next.config.ts` 的 `externalDir` 允许前端读取仓库上层共享文件
- 后端请求失败时页面不伪造本地报告，直接展示错误态与重试入口
- provenance 缺失时保守落到 `unknown`；当前后端只输出 `backend_live` / `backend_mock`
