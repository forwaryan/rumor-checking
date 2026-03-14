# 已完成子任务文档索引

这份索引不是新的任务看板，而是给后续 AI / 接手者用的“文档导航页”。

目标只有两个：

1. 让人从 `tasks/` 出发，能快速定位每个已完成子任务对应的实现说明。
2. 避免后续继续靠翻全仓库代码来判断“这个功能到底是怎么做的”。

## 当前结论

当前仓库已经完成的内容，主要集中在 6 个方向：

- 目录边界和并行工作包拆分已经稳定。
- `contracts/` 已经形成前后端共享协议与 demo payload 基线。
- 后端最小 `analyze` 闭环已经跑通，并接入了第一阶段 Kimi enrichment。
- 后端最小真实检索、缓存和真实 bundle 时间线已经落地。
- 前端单页工作台已经跑通真实 analyze 优先、本地 demo 回退和三档模式展示。
- 最小测试集入口、基础 API 回归、retrieval 回归、smoke checklist 和稳定 demo case 已经建立。

还没有真正完成的部分主要是：

- URL 正文抽取
- reasoning-grounded analyze 主链收口
- 按 eval 文件分层的系统性回归与最终通过记录
- provenance 展示、replay 资产和边界说明最终收口

## 已完成子任务 -> 对应文档

| Cluster | 已完成子任务 | 推荐先读文档 | 关键代码入口 | 说明 |
| --- | --- | --- | --- | --- |
| Cluster-A | `A2` 冻结目录结构与命名边界 | `overview/06_current_code_implementation.md`、`overview/02_folder_rationale.md` | 仓库根目录、`README.md` | 当前目录边界已经进入“按实际代码说话”的阶段。 |
| Cluster-B | `B1 ~ B5` schema 与 demo payload | `contracts/contract-forge-implementation-record.md` | `contracts/*.schema.json`、`contracts/demo_payloads/*.json`、`backend/app/models/schemas.py`、`frontend/types/report.ts` | 这是前后端共享协议的事实基线。 |
| Cluster-C | `C1 ~ C8`、`C9` 第一阶段 | `backend/docs/api-foundation-implementation-record.md` | `backend/app/main.py`、`backend/app/services/analyze_pipeline.py` | 后端主链路、provider 接线和回退逻辑都在这里解释。 |
| Cluster-D | `D1 ~ D7` 最小真实检索与时间线 | `tasks/cluster-d-retrieval-lab.md`、`backend/README.md`、`data/README.md` | `backend/app/services/retrieval_service.py`、`backend/app/services/retrieval_provider.py`、`backend/app/services/retrieval_cache.py`、`backend/tests/test_retrieval.py` | 当前已经有 GDELT provider、缓存、query rewrite、真实 bundle timeline 和 mock fallback。 |
| Cluster-E | `E1 ~ E8` | `frontend/IMPLEMENTATION_SUMMARY.md` | `frontend/components/analyze-page.tsx`、`frontend/lib/api-client.ts` | 前端页面状态流、真实接口优先和 demo fallback 都已落地。 |
| Cluster-F | `F1`、`F5`、`F7` | `overview/07_quality-and-demo-baseline.md`、`SMOKE_CHECKLIST.md` | `backend/tests/conftest.py`、`backend/tests/test_retrieval.py`、`evals/minimal_v1/*` | 当前已经有统一 eval 读取入口、retrieval 回归和独立 smoke checklist。 |
| Cluster-G | `G1`、`G5`、`G6` | `README.md`、`DEMO_SCRIPT.md`、`overview/07_quality-and-demo-baseline.md` | `frontend/lib/demo-cases.ts`、`contracts/demo_payloads/*.json` | 当前 3 条稳定 demo、演示脚本和顶层 README 已对齐。 |

## 推荐阅读顺序

如果是第一次接手当前仓库，建议按这个顺序读：

1. `overview/06_current_code_implementation.md`
2. `overview/09_stage-progress-and-task-audit.md`
3. `contracts/contract-forge-implementation-record.md`
4. `backend/docs/api-foundation-implementation-record.md`
5. `tasks/cluster-d-retrieval-lab.md`
6. `overview/07_quality-and-demo-baseline.md`
7. `README.md`

如果只需要快速改一个点，按下面的路径读：

- 改响应字段、字段命名、模式枚举：
  先读 `contracts/contract-forge-implementation-record.md`
- 改后端 analyze 主链路、provider、输入标准化：
  先读 `backend/docs/api-foundation-implementation-record.md`
- 改检索、缓存、时间线：
  先读 `tasks/cluster-d-retrieval-lab.md`
- 改前端交互、fallback、页面状态：
  先读 `frontend/IMPLEMENTATION_SUMMARY.md`
- 改测试基线、demo case、回归入口：
  先读 `overview/07_quality-and-demo-baseline.md`

## 现在的实际主链路

```mermaid
flowchart LR
    U["用户输入 / Demo 输入"] --> FE["frontend AnalyzePage"]
    FE --> API["frontend/lib/api-client.ts"]
    API --> BE["POST /api/v1/analyze"]
    BE --> PIPE["AnalyzePipeline"]
    PIPE --> N["InputNormalizer"]
    PIPE --> PE["ProviderEnricher / KimiProvider"]
    PIPE --> R["RetrievalService"]
    R --> RP["GdeltNewsProvider"]
    R --> RC["RetrievalCache"]
    R --> MR["MockRetriever Fallback"]
    PIPE --> C["ClaimExtractor"]
    PIPE --> V["VerdictEngine"]
    PIPE --> T["TimelineBuilder"]
    PIPE --> RB["ReportBuilder"]
    RB --> REPORT["Report"]
    REPORT --> FE
    FE --> UI["Event / Risk / Timeline / Claim / Evidence 组件"]
```

这条链路已经真实存在于代码里，而且“前半段真实 provider + 最小真实检索”都已经接通。

当前仍然是：

- 输入标准化：规则优先
- provider enrichment：第一阶段已接入
- 检索：真实 GDELT + cache + mock fallback
- verdict：规则驱动为主
- timeline：真实 retrieval bundle + 启发式节点选择
- demo：本地 payload 回退

## 后续维护建议

- 每新增一个“已完成”子任务，优先补对应实现记录，而不是只改任务状态。
- 如果某个 cluster 已经有实现总结，优先更新原文档，不再在别处复制一份平行说明。
- 如果字段、接口或模式有变化，先更新 `contracts/` 说明，再改前后端实现。
- 如果顶层 README、overview 和 task 文件口径出现漂移，优先以任务文件和当前测试结果为准，再向上同步。
