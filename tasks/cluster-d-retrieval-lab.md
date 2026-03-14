# Cluster-D / Retrieval Lab

## 这个子 task 是干什么的

这个工作包负责检索、结果标准化、去重归并、时间线构建和缓存。它是 V1 中“传播链关键时间线”这一条主线的 owner。

## 为什么要有这个子 task

主链路后端能输出 claim/verdict 还不够，题目还要求有关键来源时间线。如果没有单独的检索与时间线 owner，这部分很容易被主链路吞掉，最后只能做成一个没有传播链的核查器。

## 为什么这个子 task 可以并行

它和 `Cluster-C` 一样属于后端，但关注点不同。它可以在 schema 固定后独立实现 mock 检索、真实检索和 timeline 逻辑，只在 `Report` 集成点和测试环节汇合。

## 窗口执行 Prompt（全局）

```text
你现在负责 Cluster-D / Retrieval Lab。
你的目标是把当前规则型时间线/证据占位链路推进成真正可复用的检索、标准化、去重和时间线能力，优先处理本文件中“进行中/未完成”的子任务。
请先完整阅读本文件、backend/app/services/、evals/minimal_v1/retrieval_cases.json、data/README.md，以及与它直接耦合的 Cluster-C、Cluster-F、Cluster-G 状态说明。
执行时必须先把当前要处理的子任务拆成 3 到 7 个更细步骤，并先把“本轮执行任务 / 执行步骤”写回本文件对应子任务下，再开始编码。
你可以修改检索、时间线、缓存相关的后端代码与测试，也可以补必要的数据目录说明，但不要顺手重写前端或 analyze 主接口框架。
如果需要改 contracts 或跨 cluster 核心文件，先按 Cluster-A 的边界口径处理。
完成后必须：
1. 回写本文件中对应子任务的状态，并补充本轮完成记录：改了哪些文件、怎么完成、验证如何、剩余问题是什么。
2. 给出检索/时间线验证结果。
3. 说明后续应交给 Cluster-F 还是 Cluster-G。
如果用户要求 [log]，同步更新 prompt-history.md。
```

## 当前实现判断

- 当前后端已经有 `timeline_builder.py`、`scenario_library.py` 和规则化 evidence/timeline 结果，因此“最小时间线展示”并非空白。
- 但当前实现更接近“规则型占位链路”，不等于真实检索系统。
- 真实公开来源检索、去重归并、缓存与 replay 入口目前还没有形成真正闭环，因此 `Cluster-D` 仍是当前最关键的功能缺口之一。

## 详细子任务

### D1 定义 `SearchResult` 与 `Evidence` 内部结构
状态：已完成
目标：统一检索结果和证据对象的内部结构，确保后续标准化容易复用。
产出：检索层内部数据模型。
前置依赖：共享 schema 基本稳定。
子子任务清单：
- 列出 `SearchResult` 内部字段和来源等级字段。
- 统一内部 `Evidence` 结构与 verdict 模块的对接方式。
- 给出检索层内部对象的最小示例。
实现备注：已新增 `backend/app/services/retrieval_models.py`，定义了内部 `SearchResult` 与 `RetrievalBundle`，并使用 `to_evidence()` / `to_evidence_items()` 稳定映射到对外 `EvidenceItem` 结构。

### D2 实现 mock 检索读取与标准化
状态：已完成
目标：基于 `retrieval_cases.json` 输出统一格式的检索结果。
产出：mock `retriever`。
前置依赖：D1。
子子任务清单：
- 从最小 case 中读取 mock 搜索结果。
- 把原始 case 结构转成统一内部对象。
- 输出可供 timeline 和 report 使用的标准化结果。
实现备注：已新增 `backend/app/services/mock_retriever.py`，可从 `evals/minimal_v1/retrieval_cases.json` 载入 mock 检索集，按 query / event 进行匹配，并在 `AnalyzePipeline` 中作为独立检索层接入。

### D3 实现去重归并规则
状态：已完成
目标：根据题目规则实现标题相似、转载链、近重复结果的归并逻辑。
产出：去重与归并逻辑。
前置依赖：D2。
子子任务清单：
- 定义重复、转载、弱重复的判断规则。
- 对 mock 数据实现归并和保留策略。
- 输出归并后的结果列表与被归并说明。
实现备注：已在 `MockRetriever` 中实现显式 `is_duplicate_of` 、标题弱重复、转载前缀识别与 canonical 保留策略，归并结果会附带 `merged_result_ids` / `merged_notes` 供后续 timeline 和验证使用。

### D4 实现时间线候选识别
状态：已完成
目标：识别 `origin / amplification / peak / turn / clarification` 的候选节点。
产出：mock `timeline_builder`。
前置依赖：D2、D3。
子子任务清单：
- 实现 origin 候选识别。
- 实现 turn 或 clarification 候选识别。
- 为每一个被选中节点补 `why_selected` 说明。
实现备注：`timeline_builder.py` 已优先基于 `RetrievalBundle` 输出时间线，可识别 origin / amplification / peak / turn / clarification 节点，并保留无检索命中时的 scenario fallback。

### D5 接真实公开来源检索 provider
状态：已完成（最小可用版本，待真实公网 smoke）
目标：接一个不额外依赖复杂 key 的公开来源检索能力，并做结果标准化。
产出：真实检索 provider。
前置依赖：主链路真实模式基本稳定。
子子任务清单：
- 选定可用的公开来源检索方案。
- 封装 provider 调用与超时处理。
- 把真实返回结果映射到统一结构。
本轮执行任务：
- 接入 `GdeltNewsProvider`，把公开新闻搜索结果映射到统一 `SearchResult`。
- 把真实 provider 通过 `RetrievalService` 接入 analyze 主链路，并支持 `question_only` 查询改写。
- 对齐真实检索相关配置、环境变量和失败回退行为。
执行步骤：
1. 回读 `mock_retriever / retrieval_models / timeline_builder / analyze_pipeline / test_retrieval`，确认现有内部结构和 fallback 边界。
2. 选择不依赖额外 key 的公开 provider 路线，先落 `GDELT ArtList` 的调用、超时处理和统一字段映射。
3. 用 `RetrievalService` 把真实 provider 接到 `AnalyzePipeline`，保留 mock fallback，并让 `question_only` 输入能改写成搜索 query。
4. 对齐 `config.py` 与 `.env.example` 的检索配置命名，避免 provider/runtime 读错字段。
5. 补 provider 配置、失败回退、缓存命中和 question-only 主链路测试，再跑回归验证。
实现备注：已新增并接通 `backend/app/services/retrieval_provider.py` 中的 `GdeltNewsProvider`；当 `RETRIEVAL_PROVIDER=gdelt` 时，系统会调用公开 GDELT 新闻接口，把结果标准化为现有 `SearchResult / RetrievalBundle`，并通过 `RetrievalService` 接入 `AnalyzePipeline`。
本轮完成记录：
- `backend/app/services/retrieval_provider.py`：封装 GDELT 调用、超时、发布时间解析与来源分级。
- `backend/app/services/retrieval_service.py`：统一真实 provider、cache、mock fallback 与 `question_only` 查询改写。
- `backend/app/core/config.py`、`backend/.env.example`：补齐真实检索配置并修正字段名漂移。
- `backend/tests/test_retrieval.py`：新增 provider 配置对齐测试、失败回退测试和 `question_only` 真实检索链路测试。
验证结果：
- `python -m compileall backend\app backend\tests` 通过。
- `pytest backend\tests\test_retrieval.py -q` 通过，`11 passed`。
- `pytest backend\tests -q` 通过，`26 passed`。
剩余问题：
- 还没有带真实公网请求的 smoke 记录；当前 provider 通过 mocked HTTP 夹具完成本地验证。
交接建议：
- 下一步优先交给 `Cluster-F / F7` 做演示前 smoke，把 `RETRIEVAL_PROVIDER=gdelt` 的真实联调结果补齐；演示文档再交给 `Cluster-G` 收口。

### D6 接本地缓存与 replay 支持
状态：已完成（最小可用版本）
目标：缓存检索结果，减少演示波动，并为 replay 提供基础。
产出：检索缓存层。
前置依赖：D5。
子子任务清单：
- 设计检索缓存 key 和缓存格式。
- 接入写缓存与读缓存逻辑。
- 为 demo replay 预留固定缓存读取入口。
本轮执行任务：
- 把真实检索结果落到 `data/cache/retrieval/` 下，形成稳定可复用缓存。
- 支持正常命中、stale 命中、跳过缓存和 cache-only 读取。
- 给 replay 预留内部入口，不要求这轮就暴露独立 HTTP 接口。
执行步骤：
1. 复用现有 `RetrievalBundle` 结构设计可序列化缓存格式，避免发明第二套 replay 结构。
2. 基于 `provider + compact_query` 生成稳定 cache key，并按 provider 分目录存储。
3. 在 `RetrievalService` 中接入读缓存、写缓存、失败时 stale 回退与 cache-only 模式。
4. 用测试覆盖缓存 round-trip、cache-only miss 和 provider 失败 fallback。
实现备注：`backend/app/services/retrieval_cache.py` 现在会把缓存写到 `data/cache/retrieval/<provider>/<cache_key>.json`；`RetrievalService` 支持 `bypass_retrieval_cache`、`retrieval_cache_only`、`allow_stale_retrieval_cache` 这几个内部控制入口，供后续 replay 或 smoke 固定命中使用。
本轮完成记录：
- 缓存 key 使用 `sha256(v1|provider|compact_query)` 的前 24 位，便于稳定命中与版本升级。
- 支持 TTL、stale 命中和 provider 失败时的 stale fallback。
- 预留 `request_context.retrieval_cache_only=true` 作为 replay 的内部只读入口；未命中时会按配置回退到 mock 或空 bundle。
验证结果：
- `backend/tests/test_retrieval.py::test_retrieval_cache_round_trip` 验证缓存读写通过。
- `backend/tests/test_retrieval.py::test_retrieval_service_cache_only_mode_returns_empty_without_fallback` 验证 cache-only 入口通过。
剩余问题：
- 目前 replay 还是内部能力，没有单独的 `/api/v1/replay` 路由；后续如果 `Cluster-G` 需要演示级 replay，可以直接复用这套 cache-only 入口继续往外包一层。
交接建议：
- 如果演示方要固定复现“随机新闻较真”结果，优先由 `Cluster-F` 用现有 cache-only 能力设计 smoke 和 replay 操作说明，而不是重新设计缓存格式。

### D7 强化真实时间线构建
状态：已完成（最小可用版本）
目标：在真实检索结果上完成时间线节点选择、排序和 `why_selected` 说明。
产出：真实模式时间线构建。
前置依赖：D5、D6。
子子任务清单：
- 对真实结果做去重、排序和节点筛选。
- 输出 2 到 10 个关键时间线节点。
- 验证部分模式下的时间线降级策略。
本轮执行任务：
- 让真实 provider 返回的 `RetrievalBundle` 直接走既有去重和时间线节点筛选逻辑。
- 验证 `question_only` 和真实 bundle 都能产出带 `why_selected` 的时间线。
- 保留真实检索失败时的降级路径，不让 analyze 因 timeline 失败而崩掉。
执行步骤：
1. 复核 `TimelineBuilder` 当前的 origin / amplification / peak / turn / clarification 选择条件，确认它吃的是 `canonical_results` 而非 mock case 特例。
2. 确保真实 provider 结果也会先做 `merge_search_results` 去重归并，再进入 timeline 选择。
3. 用 `question_only` 场景补一条真实 bundle 测试，验证 open-ended 输入不再停在空时间线。
4. 回归 mock retrieval case，确保已有时间线逻辑没有被真实检索路径打坏。
实现备注：`TimelineBuilder` 无需额外分叉逻辑，已经能直接消费真实 provider 产生的 `canonical_results`；随着 `RetrievalService` 把真实 bundle 接入 `AnalyzePipeline`，真实问题输入现在也能产出 `timeline + why_selected`，并在证据不足时继续安全降级。
本轮完成记录：
- 真实 provider 结果在进入 timeline 前统一经过 `merge_search_results` 去重归并。
- `question_only` 输入现在会走“问题改写 -> 真实检索 -> canonical_results -> TimelineBuilder”。
- `why_selected` 继续保留“为什么被选成 origin / turn / clarification”这一层解释，没有退化成纯时间排序。
验证结果：
- `backend/tests/test_retrieval.py` 中的 `test_timeline_builder_uses_retrieval_candidates` 和 `test_question_only_pipeline_uses_real_retrieval_bundle` 均通过。
- `pytest backend\tests -q` 全量通过，说明真实时间线接线没有破坏现有 API 回归。
剩余问题：
- 目前时间线节点仍基于启发式规则，不是语义重排或事件聚类；当真实结果噪声较高时，节点质量仍有提升空间。
交接建议：
- 下一阶段如果要继续提升“随机新闻较真”的可解释性，先让 `Cluster-F` 做真实 smoke，再决定是否需要新开一轮 `Cluster-D` 做语义重排或来源可信度精修。
