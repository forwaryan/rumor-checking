# Frontend

本目录提供 `Cluster-E / Experience Shell` 的 Next.js 单页前端壳，当前已经从“纯 mock 页面”推进到“优先走真实 `POST /api/v1/analyze`，失败时回退本地 demo payload”的状态。

## 已完成内容

- Next.js + TypeScript 工程配置
- 单页入口与全局样式
- `InputPanel / StatusBanner / EventCard / TimelinePanel / ClaimTable / EvidenceList / RiskPanel`
- `complete_mode / partial_mode / safe_mode` 三档页面表达
- 与当前后端对齐的 `analyze / health` API client
- 三条与后端 scenario 对齐的稳定 demo 输入
- 后端离线或请求失败时的本地 demo payload / safe fallback
- 共享 contract schema 与 demo payload（位于 `contracts/`）

## 当前接口假设

当前前端以这两个真实接口为准：

- `POST /api/v1/analyze`
- `GET /api/v1/health`

说明：

- 后端当前没有 `GET /api/v1/demo-cases` 和 `POST /api/v1/replay`。
- 因此前端示例区的 demo 输入会优先走真实 `analyze`；只有后端离线或请求失败时，才回退到本地 payload。

## 运行方式

```bash
cd frontend
npm install
npm run dev
```

默认请求：

```bash
http://localhost:8000/api/v1/*
```

如需覆盖后端地址：

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## 目录说明

- `app/`
  - 页面入口、布局、全局样式
- `components/`
  - 页面各个可复用展示模块
- `lib/`
  - API client、demo 注册、模式和 fallback 辅助逻辑
- `types/`
  - 前端消费的 Report 类型

## 协作约束

- 共享字段结构以 `contracts/*.schema.json` 为准
- 稳定 demo payload 放在 `contracts/demo_payloads/`
- 当前前端通过 `next.config.ts` 允许读取仓库根目录下的 contract JSON
- 如需继续联调，优先对齐 `backend/app/models/schemas.py` 与 `frontend/types/report.ts`

## 验证说明

- `npm run typecheck` 已通过
- `npm run build` 已通过
- 直接在 `\\wsl.localhost\...` 路径上使用 Windows Node 构建会遇到路径兼容问题；如需稳定构建，优先在 WSL 内或 Windows 本机目录执行
