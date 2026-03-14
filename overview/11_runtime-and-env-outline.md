# 11 运行方式与环境变量章节骨架

更新时间：2026-03-14（Asia/Shanghai）

## 1. 这份文档的定位

这不是新的最终 README，而是 `G3` 第一阶段的收口骨架。

目标只有两个：

- 把“怎么跑 / 环境变量在哪 / 演示前怎么检查”拆成固定章节
- 明确哪些章节现在可以先填，哪些必须等 `C10 / C11 / F8` 再最终落笔

本轮不要做的事：

- 不重新发明前端或后端自己的 README
- 不提前给出“推荐默认链路已完全验证”的口径
- 不写尚未落地的 replay 操作步骤

## 2. 最终文档角色边界

后续建议按下面的角色分工收口：

| 文档 | 角色 | 当前来源 |
| --- | --- | --- |
| `README.md` | 第一次进仓库的总入口，只放路线和链接 | 根目录 README |
| `frontend/README.md` | 前端启动、页面行为、Windows/WSL 启动方式 | 前端 README |
| `backend/README.md` | 后端启动、provider/retrieval 环境变量、最小 API 联调 | 后端 README |
| `SMOKE_CHECKLIST.md` | 演示前检查与 go / no-go | 根目录 smoke checklist |
| 本文 | 章节骨架与待冻结段落清单 | `G3` 第一阶段新增 |

## 3. 建议最终章节顺序

后续正式收口时，建议按下面顺序组织运行说明：

### 3.1 先说今天想跑哪条路径

[待补骨架]

- 完整联调模式：前后端都启动，优先走真实 `analyze`
- 保底演示模式：前端 + 本地 demo payload
- 后续 URL / retrieval / replay 扩展路径：等 `C10 / C11 / F8`

### 3.2 环境准备

[待补骨架]

- Python / Node / npm 的最低要求
- 端口约定：后端 `8000`、前端 `3020`
- Windows 通过 `\\wsl.localhost` 访问仓库时的 watcher 注意事项

### 3.3 后端启动章节

[待补骨架]

- 安装依赖
- `uvicorn backend.app.main:app --reload`
- 如何确认 `GET /api/v1/health`
- 哪些是可选能力，不应写成默认必开

### 3.4 前端启动章节

[待补骨架]

- 标准 `npm install` / `npm run dev`
- Windows 本地镜像脚本路径
- 页面启动后的在线/离线状态提示

### 3.5 环境变量矩阵

[待补骨架]

建议最终按“默认不开启 / 可选开启 / 仅调试使用”三组收口：

| 分组 | 变量 | 当前来源 | 最终是否需要定稿 |
| --- | --- | --- | --- |
| 后端 provider | `ANALYSIS_PROVIDER`、`KIMI_*`、`PROVIDER_TIMEOUT_SECONDS` | `backend/README.md` | 是 |
| 后端 retrieval | `RETRIEVAL_PROVIDER`、`RETRIEVAL_*` | `backend/README.md` | 是 |
| 前端 API | `NEXT_PUBLIC_API_BASE_URL` | `frontend/start-local-windows.ps1`、前端 README | 是 |
| replay / 调试 | `request_context.*`、缓存绕过参数 | `backend/README.md`、`data/demos/README.md` | 等 `C11` |

### 3.6 演示前检查入口

[待补骨架]

- 何时引导读者去 `SMOKE_CHECKLIST.md`
- 哪些检查属于“必须过”
- 哪些只是可选增强项

### 3.7 demo 与 replay 的运行章节

[待补骨架]

- demo：当前已经存在稳定 case，可直接按 `DEMO_SCRIPT.md` 和页面 demo 卡片操作
- replay：当前只冻结文件落点与格式草案，正式使用方式待后续补

### 3.8 常见启动失败与保守路径

[待补骨架]

- 后端启动失败怎么办
- 前端 watcher 不稳怎么办
- 演示当天如何切到保底模式

## 4. 后续填写时的来源顺序

后续窗口补文案时，建议按这个优先级引用现有事实：

1. `backend/README.md`
2. `frontend/README.md`
3. `SMOKE_CHECKLIST.md`
4. `DEMO_SCRIPT.md`
5. `F8` 最终验收记录

如果这些来源冲突，以最新验收记录为准，不以更早的 README 描述为准。

## 5. 必须等后续任务的章节

下面这些段落现在只允许留占位：

- URL 输入该如何跑、哪些地址可视为“真实链路已打通”：等 `C10`
- analyze 主链、retrieval、provenance 的推荐开关组合：等 `C11`
- 哪条路径可以被写成“推荐默认演示路径”：等 `F8`
- replay 的正式运行步骤、是否需要专用接口或脚本：等 `C11 / F8`

## 6. 当前一句话结论

截至 2026-03-14，运行说明和环境变量还不该在一个地方直接定稿；本轮先把章节结构和责任边界固定下来。
