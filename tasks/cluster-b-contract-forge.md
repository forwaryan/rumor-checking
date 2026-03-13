# Cluster-B / Contract Forge

## 这个子 task 是干什么的

这个工作包是前后端共享协议的唯一 owner，负责固定 `Event`、`TimelineNode`、`ClaimResult`、`Report` 这些核心对象。

## 为什么要有这个子 task

如果 schema 没有唯一 owner，前端会按页面想象字段，后端会按实现方便定义字段，测试又会按 case 自己理解字段，最后会出现三套协议。

## 为什么这个子 task 可以并行

它主要产出共享协议和示例 payload，不需要等待真实前端界面或真实后端 provider 完成。只要先锁住字段和结构，其他 cluster 就可以基于这套 schema 并行开发。

## 建议谁拿

- 最细心、最适合管字段和接口的人。
- 对共享 schema、字段约束、接口稳定性足够敏感的人。
- 不建议交给页面实现窗口兼任。

## 当前实现判断

- `contracts/` 目录已经形成事实上的共享协议中心。
- 核心 schema 与三份 demo payload 都已存在，并被前后端实际消费。
- 当前剩余缺口主要不是结构本身，而是字段说明深度和正式变更流程。

## 详细子任务

### B1 定义 `Event` schema
状态：已完成
目标：固定事件对象的字段、可空规则、时间字段格式和 mode 字段位置。
产出：`Event` 正式 schema。
前置依赖：无。
子子任务清单：
- 列出事件对象必填字段、可选字段和默认值。
- 明确 `published_at`、`source_url`、`keywords` 的格式要求。
- 给出至少一个完整 `Event` 示例。
实现备注：`contracts/event.schema.json` 已存在并被前后端使用。

### B2 定义 `TimelineNode` schema
状态：已完成
目标：固定时间线节点字段、节点类型枚举和值域说明。
产出：`TimelineNode` 正式 schema。
前置依赖：B1。
子子任务清单：
- 固定 `node_type` 的可选值集合。
- 定义 `why_selected`、`summary` 等说明性字段的规则。
- 给出 origin、turn 两种节点示例。
实现备注：`contracts/timeline_node.schema.json` 已存在，并已被前后端时间线层对齐消费。

### B3 定义 `ClaimResult` schema
状态：已完成
目标：固定 claim、claim_type、verdict、confidence、evidence、notes 的结构与约束。
产出：`ClaimResult` 正式 schema。
前置依赖：规则文档已冻结。
子子任务清单：
- 固定 `claim_type` 与 `verdict` 的枚举范围。
- 定义 `evidence[]` 内每个对象的必需字段。
- 给出 supported 和 insufficient 两类示例。
实现备注：`contracts/claim_result.schema.json` 与 `contracts/evidence.schema.json` 已存在并实际生效。

### B4 定义 `Report` schema
状态：已完成
目标：固定完整报告的根结构。
产出：`Report` 正式 schema。
前置依赖：B1、B2、B3。
子子任务清单：
- 固定 `mode`、`event`、`timeline`、`claim_results` 等根字段。
- 明确完整模式、部分模式、安全模式下哪些字段允许为空。
- 输出一版统一的 `Report` 响应结构。
实现备注：`contracts/report.schema.json` 已存在，当前前后端返回/消费结构都围绕它对齐。

### B5 产出 mock payload 示例
状态：已完成
目标：根据 schema 写出完整模式、部分模式、安全模式的示例 payload。
产出：给前端和测试使用的 mock 示例数据。
前置依赖：B4。
子子任务清单：
- 写一份 `complete_mode` 示例 payload。
- 写一份 `partial_mode` 示例 payload。
- 写一份 `safe_mode` 示例 payload。
实现备注：`contracts/demo_payloads/*.json` 已存在，并已被前端本地 demo 回退链路使用。

### B6 写字段说明与边界注释
状态：进行中
目标：给每个核心字段补充含义、是否必填、失败时如何降级的说明。
产出：字段说明文档或 schema 注释。
前置依赖：B1 ~ B5。
子子任务清单：
- 给每个字段补充中文语义说明。
- 标注哪些字段在失败模式下允许为空。
- 标注哪些字段不能被前后端擅自改名。
实现备注：当前 `contracts/README.md` 已说明 owner 和基本协作约束，但字段语义说明仍偏薄，更多说明分散在前后端实现记录里。

### B7 约束 schema 变更流程
状态：未完成
目标：规定后续 schema 变更必须先通知 `Cluster-A`，再通知前后端 owner。
产出：统一变更口径。
前置依赖：B4。
子子任务清单：
- 约定 schema 变更的提出、审核、落地流程。
- 明确哪些变更属于破坏性变更。
- 明确变更后需要通知的 cluster 列表。
实现备注：当前靠人工协同保持一致，尚未形成显式变更流程文档。