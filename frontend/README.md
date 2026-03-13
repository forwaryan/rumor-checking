# Frontend

本目录现在提供一套可交给前端继续联调的 Next.js 单页壳，实现了 `Cluster-E / Experience Shell` 的主要交付内容。

## 已完成内容

- Next.js + TypeScript 工程配置
- 单页入口与全局样式
- `InputPanel / StatusBanner / EventCard / TimelinePanel / ClaimTable / EvidenceList / RiskPanel`
- `complete_mode / partial_mode / safe_mode` 三档页面表达
- `analyze / health / demo-cases / replay` API client
- 本地 demo 回放与接口失败时的安全模式 fallback
- 共享 contract schema 与 demo payload（位于 `contracts/`）

## 运行方式

```bash
cd frontend
npm install
npm run dev
```

默认会请求 `http://localhost:8000/api/v1/*`。
如果后端地址不同，可设置：

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
