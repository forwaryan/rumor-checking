# 11 当前运行路径与环境变量

更新时间：2026-03-14 21:46（Asia/Shanghai）
对应验收：`overview/13_f8-random-acceptance.md`

## 1. 这份文档的定位

这份文档是当前可交付的运行说明终稿，不再只是骨架。

它只回答三件事：

- 今天有哪些真实可跑的路径
- 每条路径分别依赖哪些环境变量
- 哪条路径可以交付，哪条路径只能保留为内部诊断或保底降级

如果本文与更早的 README、波次文档或历史口播冲突，以 `F8` 验收记录和当前实现为准。

## 2. 四类运行路径总表

| 路径 | 启动方式 | 关键变量 | 预期来源标签 | 当前定位 |
| --- | --- | --- | --- | --- |
| `mock demo` | 后端 `uvicorn` + 前端 `npm run dev` 或 `start-local-windows.ps1` | `ANALYSIS_PROVIDER=kimi`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`、`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` | 以 `backend_mock / retrieval_mock` 为主 | 当前推荐的可交付演示路径 |
| `live probe` | 同上，但强制 live retrieval | `RETRIEVAL_PROVIDER=gdelt`、`RETRIEVAL_FALLBACK_TO_MOCK=false` | 目标是观察 `backend_live + retrieval_live` 是否出现 | 仅内部诊断；`F8` 未通过 |
| `replay` | 当前没有公开启动链路 | 不新增公开变量 | 只有后端显式返回时才会出现 `backend_replay` | 不是当前交付路径 |
| `frontend fallback` | 前端启动即可；后端离线或请求失败时自动触发 | 无新增变量 | `demo_payload` 或 `frontend_fallback` | 只做保底演示，不算真实 analyze |

## 3. 当前推荐路径：`mock demo`

### 3.1 启动命令

后端：

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

Windows 通过 `\\wsl.localhost\...` 访问仓库时，优先用：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

### 3.2 环境变量建议

`F8` 默认环境快照如下：

- `ANALYSIS_PROVIDER=kimi`
- `RETRIEVAL_PROVIDER=mock`
- `RETRIEVAL_FALLBACK_TO_MOCK=true`
- 前端指向 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`

说明：

- 这组变量可以复现实测口径，但它产出的主要是 `mock/demo` 路径，不是 `real_live` 验收路径。
- `ANALYSIS_PROVIDER=off|kimi` 仍以 `backend/README.md` 为准；如果不开 provider，系统仍可运行，但本文不把未经过 `F8` 单独验收的新组合写成推荐默认口径。
- 当前最稳的演示素材只有 `expired-yogurt`；不要把 `chemical-odor` 和 `morningstar-layoff` 排进默认演示主线。

### 3.3 这条路径能交付什么

- 可交付前后端可运行、页面 provenance 标签、`mock/demo/fallback` 边界。
- 可交付 `expired-yogurt` 的稳定 mock 演示。
- 不可交付“真实检索已对随机新闻稳定较真”的结论。

## 4. `live probe` 只作为内部诊断

启用方式：

- 保持前后端启动方式不变。
- 将后端变量改为 `RETRIEVAL_PROVIDER=gdelt`、`RETRIEVAL_FALLBACK_TO_MOCK=false`。
- 重点观察返回的 `report.provenance` 是否出现 `source_type=backend_live` 且 `evidence_source=retrieval_live`。

`F8` 对这条路径的正式结论：

- 实测样本 `0/4 real_live`
- 全部停在 `fallback_or_none`
- 常见失败信号包括 `ConnectError`、`HTTP 429`、`JSONDecodeError` 和 provider `ReadTimeout`

因此：

- 这条路径今天只能用于内部排障或可用性观察。
- 不允许把它写成“推荐默认演示路径”或“已通过最终验收的真实链路”。

## 5. `replay` 当前不是公开运行方式

- 后端当前没有公开的 `demo-cases` 或 `replay` HTTP 接口。
- `backend/README.md` 提到的 request-level 开关，只能视为内部 smoke / replay 预留，不是外部交付流程。
- 可以继续保留文件落点与数据草案，但不要在 README 或 overview 里伪造“如何跑 replay”的正式步骤。

## 6. `frontend fallback` 的使用边界

- demo 卡片在后端离线或请求失败时，会退到本地 `demo_payload`。
- 普通自定义输入在同样场景下，会退到 `frontend_fallback` 的保守 `safe_mode` 报告壳。
- 这条路径的价值是保住页面结构演示，不是替代后端实时分析。
- 演示时必须主动说明这是保底路径，不能把它讲成 live 结果。

## 7. 环境变量矩阵

| 分组 | 变量 | 当前建议 | 备注 |
| --- | --- | --- | --- |
| 后端 provider | `ANALYSIS_PROVIDER` | 保持 `kimi` 或按 `backend/README.md` 明确关闭 | `F8` 默认快照使用 `kimi` |
| 后端 provider | `KIMI_API_KEY`、`KIMI_BASE_URL`、`KIMI_MODEL`、`PROVIDER_TIMEOUT_SECONDS` | 仅在需要 provider 时配置 | 实测仍存在 `ReadTimeout` 风险 |
| 后端 retrieval | `RETRIEVAL_PROVIDER` | 对外交付保持 `mock`；内部 live probe 才切 `gdelt` | 当前默认不是 live 验收路径 |
| 后端 retrieval | `RETRIEVAL_FALLBACK_TO_MOCK` | 对外交付保持 `true`；内部 live probe 才设 `false` | 设为 `false` 后 `F8` 未拿到 `real_live` |
| 前端 API | `NEXT_PUBLIC_API_BASE_URL` | 指向 `http://127.0.0.1:8000` | Windows 脚本会自动设置 |
| replay / 调试 | request-level 开关 | 不写入对外交付文档 | 只保留内部说明 |

## 8. 演示前最低检查

按顺序执行：

1. `GET /api/v1/health` 返回 `status = ok`
2. 页面能打开，并正确显示在线状态标签
3. `expired-yogurt` 能按当前路径完成演示
4. 演示者能说清 `live / mock / replay / fallback` 的区别
5. 如果要尝试 live probe，必须把结果视为内部诊断，不纳入对外通过口径

更完整的操作清单见 `SMOKE_CHECKLIST.md`。

## 9. 一句话结论

截至 2026-03-14，当前推荐交付的是 `mock demo + provenance 边界清楚` 的演示路径；`live probe`、`replay` 和 `frontend fallback` 都不能被讲成已经通过最终验收的真实能力。
