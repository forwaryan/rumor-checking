# Origin Problem Goal Matrix

这份表继续作为全局任务状态矩阵使用，后续应直接在本文件内维护最新状态。

维护规则：

- 先核对代码与测试，再回写总表。
- 若某个主 task 依赖多个 task id，除更新主矩阵外，还要同步更新下方“多子 task 联动记录表”。
- 需要时直接按规则名唤醒 `task_overview_progress_rules`。
- 详细规则见 `../rules/task_overview_progress_rules.md`。

核验优先级：

1. 代码与测试。
2. `tasks/cluster-*.md` 的完成记录。
3. `overview/09`、`overview/10`、`README.md` 等入口说明。

若发现冲突，先在 `../docs/status/document-conflict-register.md` 登记，再直接更新本文件。

## 多子 task 联动记录表

| 主 task | 完成该 task 需要的子 task | 子 task 当前进度 | 主 task 汇总状态 | 备注 |
| --- | --- | --- | --- | --- |
| A6 | `C10 / C11 / E9 / F8 / G3 / G4` | `C10` 已完成；`C11` 第一阶段完成；`E9` 已完成；`F8` 已完成但 live 未通过；`G3 / G4` 已完成 | 进行中（约70%） | 已有阶段验收与文档收口，但还不能给出最终 go |
| A7 | `A6 / F8 / G2 / G3 / G4` | `A6` 进行中；`F8` 已完成但 live 未通过；`G2` 进行中；`G3 / G4` 已完成 | 未完成（0%） | 仍等待 live retrieval 通过样本与 replay 定稿 |
| C11 | `C9 / C10 / D5 / D6 / D7 / E9 / F8` | `C9` 进行中；`C10` 已完成；`D5-D7` 最小可用版完成；`E9` 已完成；`F8` 已完成但 live 未通过 | 进行中（第一阶段完成，约45%） | 主链去占位和 provenance 已落地，live 稳定性与最终验收仍未收口 |
| E9 | `C11 / G3 / G4 / F8` | `C11` 第一阶段完成；`G3 / G4` 已完成；`F8` 已完成并给出验收口径 | 已完成（当前主展示） | 后续只需跟随最终验收和文案继续同步 |
| F8 | `C11 / D5 / D6 / D7 / E9 / G1 / G5` | `C11` 第一阶段完成；`D5-D7` 最小可用版完成；`E9 / G1 / G5` 已完成 | 已完成（记录已落库） | 正式记录已完成，但结论是“真实 live 路径未通过最终验收” |
| G2 | `C11 / D6 / F8` | `C11` 第一阶段完成；`D6` 最小可用版完成；`F8` 已完成 | 进行中（约45%） | replay 目录骨架已落地，最终字段、读取方式和公开接口仍未定稿 |
| G3 | `F8 / G2 / G4` | `F8` 已完成；`G2` 进行中；`G4` 已完成 | 进行中（约75%） | 运行说明已收口到当前事实，但 replay 仍保留预留口径 |
| G4 | `F8 / C11 / E9` | `F8` 已完成；`C11` 第一阶段完成；`E9` 已完成 | 进行中（约75%） | 限制说明已同步，后续仍需跟随 live 验收继续更新 |

## 主任务矩阵

| Cluster | 子任务 | 对应终目标 | 完成 | 当前进度 | 难度 | 主要缺口 |
| --- | --- | --- | --- | --- | --- | --- |
| A | A1 | 范围治理 | ✓ | 100% | 中 | 已冻结第一阶段范围与非目标 |
| A | A2 | 工程边界 | ✓ | 100% | 中 | 已冻结目录结构与命名边界 |
| A | A3 | 全局推进 |  | 进行中（约75%） | 中 | 仍需持续把 live retrieval、验收结论和多子 task 联动进度回写到总表 |
| A | A4 | 协议治理 |  | 进行中（约60%） | 中 | schema 变更流程仍缺最后制度化约束 |
| A | A5 | 冲突治理 |  | 进行中（约75%） | 中 | 仍需继续清理旧口径并保持原文件与总表联动更新 |
| A | A6 | 里程碑验收 |  | 进行中（约70%） | 中高 | 已有阶段性验收与 `F8` 正式记录，但真实 live 路径未通过 |
| A | A7 | 最终冻结判断 |  | 未完成（0%） | 高 | 还未达到 go / no-go 冻结条件 |
| B | B1 | 协议稳定 | ✓ | 100% | 低 | `Event` schema 已完成 |
| B | B2 | 协议稳定 | ✓ | 100% | 低 | `TimelineNode` schema 已完成 |
| B | B3 | 协议稳定 | ✓ | 100% | 低 | `ClaimResult` schema 已完成 |
| B | B4 | 协议稳定 | ✓ | 100% | 中 | `Report` schema 已完成 |
| B | B5 | 协议联调 | ✓ | 100% | 低 | mock payload 示例已完成 |
| B | B6 | 协议可交接 |  | 进行中（约70%） | 中 | 部分字段边界仍需跟随最终口径继续收口 |
| B | B7 | 协议变更控制 |  | 未完成（0%） | 中 | schema 变更流程还没制度化 |
| C | C1 | 后端基础 | ✓ | 100% | 低 | FastAPI 骨架已完成 |
| C | C2 | 后端基础 | ✓ | 100% | 低 | 统一配置与日志已完成 |
| C | C3 | 可观测性 | ✓ | 100% | 低 | health 与统一错误响应已完成 |
| C | C4 | 内容核查主链 | ✓ | 100% | 中 | 规则版 input normalizer 已完成 |
| C | C5 | 内容核查主链 | ✓ | 100% | 中 | 规则版 claim extractor 已完成 |
| C | C6 | 内容核查主链 | ✓ | 100% | 中 | 规则版 verdict engine 已完成 |
| C | C7 | 输出主链 | ✓ | 100% | 中 | report builder 已完成 |
| C | C8 | API 主接口 | ✓ | 100% | 中 | `/api/v1/analyze` 已完成 |
| C | C9 | 真实理解增强 |  | 进行中（第一阶段完成，约75%） | 高 | Kimi 已接线，但在线帮助性、限流和超时问题仍需继续收口 |
| C | C10 | URL 新闻输入 | ✓ | 100%（第一阶段） | 中高 | 公开 HTML 抽取与 fallback 已完成；公开 HTML 之外仍未扩展 |
| C | C11 | 真正的 reasoning-grounded analyze |  | 进行中（第一阶段完成，约45%） | 很高 | provenance 与 retrieval 已接入主链，但启发式 verdict/timeline 与 live 稳定性仍未最终收口 |
| D | D1 | 传播链内部对象 | ✓ | 100% | 中 | `SearchResult / RetrievalBundle` 已完成 |
| D | D2 | 检索基础 | ✓ | 100% | 中 | mock retrieval 已完成 |
| D | D3 | 传播链质量 | ✓ | 100% | 中高 | 去重归并已完成 |
| D | D4 | 传播链还原 | ✓ | 100% | 中高 | timeline 候选识别已完成 |
| D | D5 | 真实公开来源检索 | ✓ | 100%（最小可用版） | 高 | 已接 GDELT，但 live 路径稳定性与通过样本仍缺 |
| D | D6 | 缓存 / replay 基础 | ✓ | 100%（最小可用版） | 高 | cache-only 能力已完成，但 replay 仍未形成公开接口 |
| D | D7 | 真实时间线 | ✓ | 100%（最小可用版） | 高 | explainable timeline 已有，但仍是启发式而非语义重排 |
| E | E1 | 产品壳 | ✓ | 100% | 低 | Next.js 工程骨架已完成 |
| E | E2 | 前后端联调 | ✓ | 100% | 中 | 前端类型与 API client 已完成 |
| E | E3 | 输入体验 | ✓ | 100% | 中 | 输入区与提交状态已完成 |
| E | E4 | 结论展示 | ✓ | 100% | 中 | 事件概览与结论区已完成 |
| E | E5 | 传播链展示 | ✓ | 100% | 中 | 时间线面板已完成 |
| E | E6 | 内容核查展示 | ✓ | 100% | 中 | claim 表与证据列表已完成 |
| E | E7 | 模式表达 | ✓ | 100% | 中 | 三档模式 UI 已完成 |
| E | E8 | 边界展示 | ✓ | 100% | 中 | 空态、失败提示、fallback 文案已完成 |
| E | E9 | provenance 可信展示 | ✓ | 100%（当前主展示） | 中高 | live/mock/replay/demo/fallback 已能区分，后续主要是随最终口径做文案同步 |
| F | F1 | 测试基础 | ✓ | 100% | 低 | 最小测试集目录已接入 |
| F | F2 | 输入回归 | ✓ | 100% | 中 | `input_cases.json` 已收口，6/6 通过 |
| F | F3 | claim 分类回归 | ✓ | 100% | 中 | 独立 claim 分类回归已完成 |
| F | F4 | verdict 回归 | ✓ | 100% | 中高 | `verdict_cases.json` 已收口，8/8 通过 |
| F | F5 | retrieval / timeline 回归 | ✓ | 100% | 中高 | retrieval/timeline case 已完成 |
| F | F6 | report mode 回归 | ✓ | 100% | 中 | `report_mode_cases.json` 已收口，4/4 通过 |
| F | F7 | 演示 smoke checklist | ✓ | 100% | 中 | checklist 已完成 |
| F | F8 | 随机 case 最终通过记录 | ✓ | 100%（记录已落库） | 高 | 正式记录已完成，但结论是当前真实 live 路径未通过最终验收 |
| G | G1 | 演示稳定性 | ✓ | 100% | 低 | 稳定 demo case 已完成 |
| G | G2 | replay 体系 |  | 进行中（约45%） | 中 | 目录与文件草案已落地，但最终字段、读取方式和公开接口仍未定稿 |
| G | G3 | 运行说明 |  | 进行中（约75%） | 中 | 主体结构已在，需根据 `F8` 结论继续同步最终运行口径 |
| G | G4 | 限制说明 |  | 进行中（约75%） | 中 | 需要把 live 路径未通过和 demo 边界同步到最终说明 |
| G | G5 | 演示脚本 | ✓ | 100% | 中 | 演示顺序与口播要点已完成 |
| G | G6 | 顶层 README 收口 | ✓ | 100%（当前入口版） | 中 | README 当前已更新，后续只需继续跟随验收结论同步 |

## Retrieval-First V1 转向联动总表

> 本节用于承接新的目标：从“面试演示型工作台”转向“Retrieval-First V1 核查器”。本节状态不覆盖上方历史任务，只描述接下来要推进的新总目标。

### 多子 task 联动记录表（Retrieval-First V1）

| 主 task | 完成该 task 需要的子 task | 子 task 当前进度 | 主 task 汇总状态 | 备注 |
| --- | --- | --- | --- | --- |
| `RV1` | `R1 / R2 / R3 / R4 / R5 / R6 / R7 / R8 / R9 / R10 / R11 / R12` | `R1` 方案已完成但 contract 未冻结；`R2-R12` 未开始；其中 `R2 / R3 / R4 / R6 / R7` 已有现成代码基础 | 未开始（0%） | Retrieval-First V1 总目标 |
| `RV1-BE` | `R2 / R3 / R4 / R5 / R6` | `R2 / R3 / R4 / R6` 有基础待重构；`R5` 未开始 | 未开始（0%） | 后端主链收缩与能力重建 |
| `RV1-FE` | `R7 / R8` | `R7` 有现成页面骨架；`R8` 未开始 | 未开始（0%） | 前端从工作台收缩为核查器 |
| `RV1-MIG` | `R9 / R10` | `R9 / R10` 未开始 | 未开始（0%） | 删除废代码、迁移 demo/mock/replay |
| `RV1-QA` | `R11 / R12` | `R11` 有旧测试基础；`R12` 未开始 | 未开始（0%） | 新验收与最终冻结 |

### 子任务矩阵（Retrieval-First V1）

| Cluster | 子任务 | 对应终目标 | 完成 | 当前进度 | 难度 | 主要缺口 |
| --- | --- | --- | --- | --- | --- | --- |
| R | R1 | 冻结最小 contract |  | 已完成（方案层） | 中 | 方案已写入 `proposal/`，但还没冻结为正式 contract/schema |
| R | R2 | claim-first 输入理解 |  | 未开始 | 高 | 当前 `input_normalizer / question_resolver / kimi_provider` 仍偏关键词与 mode hint |
| R | R3 | 多 query 搜索主链 |  | 未开始 | 高 | 当前 `retrieval_service` 仍以单 query 为主 |
| R | R4 | 证据去重/分级/筛选 |  | 未开始 | 中高 | 现有 deduper 可复用，但还缺 claim 级相关性筛选 |
| R | R5 | evidence-grounded judge |  | 未开始 | 很高 | 当前 `verdict_engine` 仍以启发式重合为主 |
| R | R6 | 精简 report 与 API contract |  | 未开始 | 中高 | 当前 runtime contract 与 `contracts/` 已漂移，字段过重 |
| R | R7 | 极简核查前端 |  | 未开始 | 中 | 当前 `analyze-page` 主要在维护 demo/fallback/provenance 状态机 |
| R | R8 | demo/mock/replay 迁出主路径 |  | 未开始 | 中 | 当前 demo payload、mock retriever、replay 草案仍占主叙事 |
| R | R9 | 删除运行时闲置代码 |  | 未开始 | 低 | 已确认 `google_news_rss_provider / result_merger / scenario_library` 无主链引用 |
| R | R10 | 下线 provenance/timeline 重逻辑 |  | 未开始 | 中 | 当前前后端都对 replay/demo/fallback/timeline 有较重分支 |
| R | R11 | 新测试与 eval 集 |  | 未开始 | 中高 | 现有测试口径主要服务旧工作台 |
| R | R12 | 最终验收与文档冻结 |  | 未开始 | 中 | 必须基于新主链重新做 go/no-go 验收 |
