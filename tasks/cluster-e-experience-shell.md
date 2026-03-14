# Cluster-E / Experience Shell

## 这个子 task 是干什么的

这个工作包负责单页 Web Demo 的全部界面和交互层，是用户真正看到的系统外壳。

## 为什么要有这个子 task

即使后端逻辑完成，如果没有一个清晰的单页工作台，传播链、claim、evidence、风险提示就不能被直观展示，V1 的演示价值会大幅下降。

## 为什么这个子 task 可以并行

前端可以先基于 mock `Report` payload 独立开发，不必等真实后端全部完成。只要共享 schema 明确，前端就能和后端、检索、测试同时推进。

## 窗口执行 Prompt（全局）

```text
你现在负责 Cluster-E / Experience Shell。
当前这个 cluster 主体已完成，因此默认只处理本文件中仍需联调、验证、文档收口或用户明确重新打开的任务；如果重新打开实现，优先处理 `E9`，不重做已完成页面骨架。
请先完整阅读本文件、frontend/IMPLEMENTATION_SUMMARY.md、frontend/FILE_RECORD.md、frontend/README.md，再决定本轮是否真的需要改动前端实现。
执行时如果要继续处理残余任务，必须先把当前要处理的目标拆成 3 到 7 个更细步骤，并先把“本轮执行任务 / 执行步骤”写回本文件对应子任务下，再开始修改。
你可以修改 frontend/、对应的前端测试和前端文档，但不要越界去改后端检索系统或总控文档，除非只是同步前端侧说明。
完成后必须：
1. 回写本文件中对应子任务的状态，并补充本轮完成记录：改了哪些文件、怎么完成、验证如何、剩余问题是什么。
2. 给出前端验证结果。
3. 说明是否需要交给 Cluster-C、F 或 G 继续联调/收口。
如果用户要求 [log]，同步更新 prompt-history.md。
```

## 当前实现记录

- 详细实现总结：`frontend/IMPLEMENTATION_SUMMARY.md`
- 逐文件记录：`frontend/FILE_RECORD.md`
- 当前状态说明：`E1` 到 `E8` 已完成；新增的 `E9` 负责把“真实 analyze / mock retrieval / demo payload / 前端 fallback”在界面上明确区分开。

## 详细子任务

### E1 初始化 Next.js 项目骨架
状态：已完成
目标：创建前端项目结构、页面入口、基础样式和运行脚本。
产出：可运行的前端单页壳。
前置依赖：无。
子子任务清单：
- 初始化 Next.js 与 TypeScript 项目。
- 建立单页入口和基础布局文件。
- 确保本地可以启动前端页面。
实现备注：`frontend/` 已具备完整 Next.js 工程结构、运行脚本和全局样式。

### E2 定义前端类型与 API client
状态：已完成
目标：根据共享 schema 固定前端类型，并建立调用后端的 API client。
产出：前端类型层和请求层。
前置依赖：schema 初版可用。
子子任务清单：
- 根据 `Report` schema 定义前端类型。
- 封装 analyze、health、demo 等 API 调用。
- 处理请求异常和基础返回解析。
实现备注：前端已对齐真实 `GET /api/v1/health` 和 `POST /api/v1/analyze`；本地 demo 读取留在页面层，不再假设后端存在 `demo-cases / replay`。

### E3 实现输入区与提交状态
状态：已完成
目标：支持文本、URL、问题输入，并展示 loading、error 等状态。
产出：`InputPanel + StatusBanner`。
前置依赖：E1、E2。
子子任务清单：
- 实现输入框、示例按钮和提交按钮。
- 实现提交中、失败、重试等状态展示。
- 接好基础提交事件和前端校验。
实现备注：输入校验、提交、重试、错误提示和 fallback 提示均已接通。

### E4 实现事件概览与结论区
状态：已完成
目标：展示事件摘要、一句话结论、当前模式和风险概览。
产出：`EventCard + RiskPanel`。
前置依赖：E2。
子子任务清单：
- 渲染事件标题、摘要和来源信息。
- 渲染一句话结论和当前模式标识。
- 渲染风险提示与边界说明区域。
实现备注：事件概览、风险列表、统计信息和模式边界都已落地。

### E5 实现时间线面板
状态：已完成
目标：展示完整模式和部分模式下的时间线节点。
产出：`TimelinePanel`。
前置依赖：E2、mock payload。
子子任务清单：
- 设计时间线节点卡片或列表样式。
- 支持节点类型标签和时间排序展示。
- 处理无时间线或部分时间线的空态。
实现备注：当前已支持排序、空态和节点类型展示。

### E6 实现 claim 表与证据列表
状态：已完成
目标：展示 claim、claim_type、verdict、confidence 和 evidence 列表。
产出：`ClaimTable + EvidenceList`。
前置依赖：E2、mock payload。
子子任务清单：
- 渲染 claim 表格或卡片结构。
- 展示 claim_type、verdict、confidence 和 notes。
- 渲染 evidence 列表及来源信息。
实现备注：当前已支持 claim 表与证据聚合列表，并有基本排序与去重逻辑。

### E7 联通三档模式
状态：已完成
目标：把 `complete_mode / partial_mode / safe_mode` 在页面上完整区分开。
产出：模式联通后的完整页面。
前置依赖：E3、E4、E5、E6。
子子任务清单：
- 区分三种模式的页面结构和文案。
- 确保 safe 模式不会展示过度确定的结论。
- 确保 partial 模式不会伪装成完整结果。
实现备注：三档模式已经在状态条、风险区、空态和 fallback 文案中被清晰区分。

### E8 增加空态、失败提示和边界说明
状态：已完成
目标：补足失败提示、空态文案、demo 边界说明和 fallback 提示。
产出：演示更稳的前端状态表达。
前置依赖：E7。
子子任务清单：
- 为空结果、接口失败、部分结果设计空态。
- 明确展示 fallback 和边界化提示文案。
- 补充 demo 场景下的说明和重试入口。
实现备注：当前 demo 离线回退、接口失败安全回退和边界说明都已经接通。

### E9 明确结果来源与运行模式 provenance
状态：已完成（第一阶段 UI 壳 + 第二阶段真实接线）
目标：让用户能明确区分真实 analyze 结果、mock retrieval / replay、前端 demo payload 和 safe fallback，避免把任何缓存或样例渲染误判成真实推理。
产出：结果来源标识与 provenance 展示。
前置依赖：E7、E8，并需与 `Cluster-C`、`Cluster-D` 对齐 provenance 输入。
子子任务清单：
- 在顶部状态区或报告头部展示当前结果来源、运行模式和 fallback 原因。
- 区分“后端真实返回”“后端 mock / replay 返回”“前端本地 demo payload”“前端安全回退生成报告”四类来源。
- 对来源不明或字段不足的旧 payload 做保守展示，不伪装成真实分析。
- 补充前端测试与 README/说明，确保演示时口径一致。
本轮执行任务：
- 先基于当前前端已知状态、demo 入口和请求失败路径，搭好 provenance UI 壳与保守标签逻辑。
- 本轮只区分“真实后端响应”“本地 demo payload”“前端 safe fallback”“来源不明需保守展示”四类前端可识别状态，不等待 `C11` 冻结最终 provenance 字段。
- 同步补最小测试与前端说明，确保上线 UI 壳时不会把旧 payload 或字段不足结果误讲成真实分析。
执行步骤：
- 在 `frontend/components/analyze-page.tsx` 梳理真实 analyze、demo 回退和 safe fallback 的现有分叉，并把来源状态显式传给顶部状态区。
- 在 `frontend/components/status-banner.tsx` 增加 provenance 展示壳，展示来源类型、fallback 状态和保守说明。
- 在 `frontend/types/` 与前端工具函数中补最小 provenance 类型和兼容逻辑，确保旧 payload 或缺字段结果默认走保守标签。
- 补 provenance 相关最小单测与 `frontend/README.md` 说明文案，明确第一阶段只做 UI 壳，不依赖后端本轮改 schema。
实现备注：当前页面壳已经可运行，但同一套 UI 会渲染真实报告、本地 demo payload 和前端 fallback 结果；在没有 provenance 显示前，用户很容易误判系统已经完成真实推理。
本轮完成记录：
- `frontend/components/analyze-page.tsx`：新增前端来源状态编排，在真实 analyze 成功、本地 demo 回退、前端 safe fallback 三条路径上显式写入 provenance。
- `frontend/components/status-banner.tsx`、`frontend/app/globals.css`：在顶部状态区新增 provenance 展示壳，展示来源标签、模式 pill、fallback 状态和保守说明。
- `frontend/types/report.ts`、`frontend/lib/report-utils.ts`：新增前端 provenance state 类型和保守映射逻辑；缺来源信息的数据默认落到“来源不明”。
- `frontend/lib/__tests__/report-utils.test.ts`、`frontend/README.md`：补 provenance 单测和第一阶段说明文案，保证演示口径不把 demo 或 fallback 误讲成真实分析。
验证：
- `node .\node_modules\vitest\vitest.mjs run`（在 Windows 本地临时镜像目录运行）通过，2 个测试文件、10 个测试全部通过。
- `node .\node_modules\typescript\bin\tsc --noEmit`（在 Windows 本地临时镜像目录运行）通过。
- `node .\node_modules\next\dist\bin\next build`（在 Windows 本地临时镜像目录运行）通过。
剩余问题：
- 仍未接后端最终 provenance 字段，因此“后端 mock / replay 返回”暂无独立标签，当前缺字段结果统一保守落到“来源不明”。
- 等 `Cluster-C / C11` 冻结 provenance 字段后，需要进入 E9 第二阶段，把真实后端 source kind / fallback reason 接到前端类型与 UI。
交接建议：
- `Cluster-C`：冻结 `Report` provenance 字段，并说明 mock / replay 与 fallback 的区分边界。
- `Cluster-F`：后续随机 case / 演示验收时，确认页面标签与真实运行路径一致，不把 demo payload 或 safe fallback 讲成真实分析。

本轮执行任务：
- 把后端已冻结的 `report.provenance` 接到前端类型、解析层和页面状态区，正式消费 `backend_live / backend_mock / backend_replay`。
- 继续保留前端本地 `demo_payload / frontend_fallback` 两类本地来源，并把它们和后端三类来源统一成五类展示口径。
- 对旧 payload、缺 `provenance` 字段或字段不完整的结果维持保守路径，避免把任何可渲染数据误标成真实分析。
- 补最小前端测试与 `frontend/README.md` 第二阶段说明，并在本任务下回写完成记录或剩余问题。

执行步骤：
- 扩展 `frontend/types/report.ts` 的 `Report` 与 provenance 相关类型，对齐 `C11` 冻结字段，同时保留前端本地 fallback reason。
- 调整 `frontend/lib/api-client.ts` 与 `frontend/lib/report-utils.ts`，解析后端 provenance 并集中产出五类来源的 UI 元数据；字段不足时回退到保守标签。
- 修改 `frontend/components/analyze-page.tsx` 和 `frontend/components/status-banner.tsx`，让真实 analyze 成功时直接展示后端 provenance，本地 demo 与前端 fallback 继续走显式本地标签。
- 补 `frontend/lib/__tests__/api-client.test.ts`、`frontend/lib/__tests__/report-utils.test.ts` 的最小回归测试，并同步更新 `frontend/README.md` 和本任务记录。
实现备注（第二阶段）：前端已正式消费后端 `report.provenance`。真实 analyze 成功时会直接展示 `backend_live / backend_mock / backend_replay`，本地 demo 与前端安全回退分别固定为 `demo_payload / frontend_fallback`；旧 payload 或缺字段结果仍会保守落到 `unknown`，不会伪装成真实分析。
本轮完成记录（第二阶段）：
- `frontend/types/report.ts`、`frontend/lib/api-client.ts`：补齐 `report.provenance` 类型与解析逻辑，对齐 `C11` 冻结字段；字段缺失或不完整时不抛异常，直接保守落到 `provenance=null`。
- `frontend/lib/report-utils.ts`、`frontend/components/status-banner.tsx`、`frontend/app/globals.css`：把 provenance 展示从“四类前端状态”升级成“五类真实来源 + unknown 保守兜底”，并新增 `claims:* / evidence:* / timeline:* / provider:* / cache:*` 等 provenance 细节 badge。
- `frontend/components/analyze-page.tsx`：真实 analyze 成功时直接消费后端 `source_type`；demo 离线/失败回退固定标记为 `demo_payload`，普通输入失败回退固定标记为 `frontend_fallback`。
- `frontend/lib/__tests__/api-client.test.ts`、`frontend/lib/__tests__/report-utils.test.ts`、`frontend/README.md`：补解析/展示回归测试与第二阶段说明文档，明确页面如何区分 live/mock/replay/demo/fallback，以及旧 payload 的保守路径。
验证（第二阶段）：
- `cmd /c "pushd \\wsl.localhost\Ubuntu-20.04\home\forwaryan\mianshi\rumor-checking\frontend && npm run typecheck"` 通过。
- `cmd /c "pushd \\wsl.localhost\Ubuntu-20.04\home\forwaryan\mianshi\rumor-checking\frontend && npm test"` 通过，`2` 个测试文件、`13` 个测试全部通过。
- 基于 Windows 本地镜像目录的 `next build` 通过，可完成生产构建验证。
剩余问题（第二阶段）：
- 直接在 `\\wsl.localhost\...` 路径下运行 `next build` 仍会遇到 Windows `UNC/readlink` 兼容问题；需要稳定构建时，继续使用 `frontend/start-local-windows.ps1` 或本地镜像目录。
- 仓库内稳定 demo payload 目前仍是旧样例 JSON，本轮由前端本地来源状态显式标记为 `demo_payload`；如果后续希望在静态样例里也看到完整 provenance 字段，可再单独补合同步，但当前上线不依赖它。
交接建议（第二阶段）：
- `Cluster-F / F8`：最终验收时按页面标签和 `evidence_source` 一起归类；只有 `backend_live + retrieval_live` 才应算真实路径通过样本。
- `Cluster-C`：当前 schema 已足够前端上线，不需要再改字段；只有当 provenance 枚举或细节字段继续扩张时，才需要新一轮前端对齐。
