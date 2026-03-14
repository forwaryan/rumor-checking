# Frontend

详细实现总结见：`frontend/IMPLEMENTATION_SUMMARY.md`

本目录提供 `Cluster-E / Experience Shell` 的 Next.js 单页前端壳，当前已经从“纯 mock 页面”推进到“优先走真实 `POST /api/v1/analyze`，失败时回退本地 demo payload”的状态。

## 已完成内容

- Next.js + TypeScript 工程配置
- 单页入口与全局样式
- `InputPanel / StatusBanner / EventCard / TimelinePanel / ClaimTable / EvidenceList / RiskPanel`
- `complete_mode / partial_mode / safe_mode` 三档页面表达
- 与当前后端对齐的 `analyze / health` API client
- 三条与后端 scenario 对齐的稳定 demo 输入
- 后端离线或请求失败时的本地 demo payload / safe fallback
- 顶部状态区 provenance UI 壳，可区分真实后端响应、本地 demo payload、前端 safe fallback 和来源不明结果
- 共享 contract schema 与 demo payload（位于 `contracts/`）
- 基于 Vitest 的最小单元测试覆盖（`parseReport / validateInput / getStatusFromMode / collectEvidence / getReportProvenanceMeta`）

## 当前接口假设

当前前端以这两个真实接口为准：

- `POST /api/v1/analyze`
- `GET /api/v1/health`

说明：

- 后端当前没有 `GET /api/v1/demo-cases` 和 `POST /api/v1/replay`。
- 因此前端示例区的 demo 输入会优先走真实 `analyze`；只有后端离线或请求失败时，才回退到本地 payload。

## 当前 provenance 展示策略

第一阶段的 provenance UI 壳只依赖前端运行时已知状态，不依赖后端本轮新增 schema：

- `真实后端响应`：本次 `POST /api/v1/analyze` 成功返回并完成前端解析。
- `本地 demo payload`：demo 输入在后端离线或请求失败时，回退到仓库内稳定 payload。
- `前端 safe fallback`：普通输入在接口失败时，由前端生成保守 `safe_mode` 报告壳。
- `来源不明`：旧 payload、缺字段结果或没有显式来源状态的数据，一律按保守标签展示，不伪装成真实分析。

这意味着当前页面已经能看见 provenance 位置和基本标签；等 `C11` 冻结后端 provenance 字段后，再进入第二阶段真实接线。

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
  - API client、demo 注册、模式和 fallback 辅助逻辑、单元测试
- `types/`
  - 前端消费的 Report 类型

## 协作约束

- 共享字段结构以 `contracts/*.schema.json` 为准
- 稳定 demo payload 放在 `contracts/demo_payloads/`
- 当前前端通过 `next.config.ts` 允许读取仓库根目录下的 contract JSON
- 如需继续联调，优先对齐 `backend/app/models/schemas.py` 与 `frontend/types/report.ts`

## 验证说明

- `npm test` 已通过（2 个测试文件，10 个测试）
- `npm run typecheck` 已通过
- `npm run build` 已通过
- 当前项目存在 Windows Node 直接操作 `\\wsl.localhost\...` 路径的兼容性问题；如需稳定执行 `test / build`，优先在 WSL 内或 Windows 本机目录执行
