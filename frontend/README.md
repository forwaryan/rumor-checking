# Frontend

详细实现总结见：`frontend/IMPLEMENTATION_SUMMARY.md`

本目录提供 `Cluster-E / Experience Shell` 的 Next.js 单页前端壳。当前已经进入 `E9` 第二阶段：前端会优先走真实 `POST /api/v1/analyze`，并正式消费后端冻结的 `report.provenance`；只有在后端离线、请求失败或本地演示时，才回退到 `demo_payload / frontend_fallback` 等本地来源。

## 已完成内容

- Next.js + TypeScript 工程配置
- 单页入口与全局样式
- `InputPanel / StatusBanner / EventCard / TimelinePanel / ClaimTable / EvidenceList / RiskPanel`
- `complete_mode / partial_mode / safe_mode` 三档页面表达
- 与当前后端对齐的 `analyze / health` API client
- 三条与后端 scenario 对齐的稳定 demo 输入
- 后端离线或请求失败时的本地 `demo_payload / frontend_fallback`
- 顶部状态区真实 provenance 展示，可区分 `backend_live / backend_mock / backend_replay / demo_payload / frontend_fallback`
- 对旧 payload、缺 `provenance` 字段或字段不完整结果的保守展示路径
- 共享 contract schema 与 demo payload（位于 `contracts/`）
- 基于 Vitest 的最小单元测试覆盖（`parseReport / validateInput / getStatusFromMode / collectEvidence / getReportProvenanceMeta`）

## 当前接口假设

当前前端以这两个真实接口为准：

- `POST /api/v1/analyze`
- `GET /api/v1/health`

说明：

- 后端当前没有 `GET /api/v1/demo-cases` 和 `POST /api/v1/replay`。
- 前端示例区的 demo 输入仍会优先走真实 `analyze`；只有后端离线或请求失败时，才回退到仓库内稳定 payload。
- `backend_replay` 是否出现由后端 `report.provenance.source_type` 决定；前端只消费这个标签，不额外发 replay 请求。

## 当前 provenance 展示策略

前端现已直接消费 `report.provenance`，展示口径如下：

- `backend_live`：后端实时 analyze 返回。页面会额外展示 `claims:* / evidence:* / timeline:* / provider:* / cache:*` 等 provenance 细节；若 `evidence_source != retrieval_live` 或 `fallback_used=true`，仍会给出保守提示。
- `backend_mock`：后端 mock 联调结果。页面明确提示这不是 live 检索路径。
- `backend_replay`：后端 replay 回放结果。页面明确提示这不是针对当前输入的实时分析。
- `demo_payload`：前端本地稳定 demo payload，仅用于演示页面结构和三档模式。
- `frontend_fallback`：前端在请求失败时生成的保守 `safe_mode` 报告壳。
- `unknown`：旧 payload、缺 `provenance` 字段或字段不完整的结果，一律按保守标签展示，不伪装成真实分析。

这意味着页面现在已经能看见真实 provenance 标签；即使后端返回旧 payload 或缺字段结果，也不会被前端误标成 live 分析。

## 运行方式

标准方式：

```bash
cd frontend
npm install
npm run dev
```

如果仓库当前是通过 `\\wsl.localhost\...` 挂到 Windows 下运行，Next.js dev watcher 可能卡在文件监听上，页面长时间不返回。
这种情况下优先使用仓库内的 Windows 本地镜像启动脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1
```

这个脚本会：

- 把 `frontend/` 和 `contracts/` 镜像到 Windows 本地临时目录
- 自动设置 `NEXT_PUBLIC_API_BASE_URL`
- 在本地镜像目录里启动 `next dev`
- 避开 `\\wsl.localhost` / 映射盘下的 watcher 问题

默认前端地址是：

```text
http://127.0.0.1:3020
```

也可以自定义：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

常用验证命令：

```bash
npm test
npm run typecheck
npm run build
```

## 目录说明

- `app/`
  - 页面入口、布局、全局样式
- `components/`
  - 页面各个可复用展示模块
- `lib/`
  - API client、demo 注册、模式与 provenance/fallback 辅助逻辑、单元测试
- `types/`
  - 前端消费的 Report 与 provenance 类型

## 协作约束

- 共享字段结构以 `contracts/*.schema.json` 为准
- 稳定 demo payload 放在 `contracts/demo_payloads/`
- 当前前端通过 `next.config.ts` 允许读取仓库根目录下的 contract JSON
- 如需继续联调，优先对齐 `backend/app/models/schemas.py` 与 `frontend/types/report.ts`
- 本轮不改后端 schema；若 `report.provenance` 缺失或字段不足，前端必须走保守标签

## 验证说明

- `npm test` 通过：`2` 个测试文件，`13` 个测试全部通过
- `npm run typecheck` 通过
- `npm run build` 已在 Windows 本地镜像目录通过
- 直接在 `\\wsl.localhost\...` 路径下运行 `next build` 仍可能触发 Windows `UNC/readlink` 兼容问题；需要稳定构建时优先使用本地镜像目录