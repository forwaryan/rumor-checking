# 当前已核验状态

更新时间：2026-03-14（Asia/Shanghai）

这份文档只保留已经被项目代码核验过的事实，用来处理 README、overview、tasks 之间的状态冲突。

## 核验依据

已直接核对以下实现或测试文件：

- `backend/app/api/v1/router.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/services/input_normalizer.py`
- `backend/app/services/url_content_extractor.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/report_builder.py`
- `frontend/components/status-banner.tsx`
- `frontend/lib/report-utils.ts`
- `backend/tests/test_api.py`

## 已确认事实

### 1. 公开 API 只有 `health` 和 `analyze`

- 当前公开路由只有：
  - `GET /api/v1/health`
  - `POST /api/v1/analyze`
- 代码中没有公开的 `GET /api/v1/demo-cases` 或 `POST /api/v1/replay` 路由。

### 2. `C10` 已完成到“公开 HTML URL 抽取 + 清晰 fallback”这一阶段

- `InputNormalizer` 会在 URL 输入时调用 `UrlContentExtractor`。
- `UrlContentExtractor` 已实现公开 HTML 页面抽取，能从 title、meta、JSON-LD、`article/main` 中回填标题、摘要、来源、发布时间和正文片段。
- 非 HTML、抓取失败、超时、正文缺失都会进入明确的 fallback reason。
- `backend/tests/test_api.py` 已覆盖 URL 抽取成功、失败、超时三条路径。

当前仍不该宣称的部分：

- 不支持登录页、强反爬、浏览器渲染页面、PDF 或图片正文。
- 这不等于“任意 URL 都已稳定可抽取”。

### 3. `C11` 可推断已完成第一阶段，但还没有到开放场景稳定完成

这是基于代码的判断，不是单看任务文档得出的结论：

- `AnalyzePipeline` 已把 `InputNormalizer -> ProviderEnricher -> RetrievalService -> ClaimExtractor -> VerdictEngine -> TimelineBuilder -> ReportBuilder` 串成真实主链。
- `ReportProvenance` 已在主链中构建并进入最终 `Report`。
- `RetrievalService` 已支持真实 provider、cache、mock fallback 和 `question_only` 查询改写。
- `VerdictEngine` 与 `TimelineBuilder` 已消费 retrieval 结果，而不是只返回固定模板。

当前仍不该宣称的部分：

- `VerdictEngine` 仍以关键词重合、来源等级和启发式规则为主。
- `TimelineBuilder` 仍以启发式节点选取为主，不是完整传播链求解器。
- `F8` 随机 case 最终验收记录仍未完成，所以不能把系统表述成“开放新闻场景稳定较真已完成”。

### 4. 前端 provenance 展示已经真实落地

- `status-banner.tsx` 会展示 provenance pill、fallback 标签和细节 badges。
- `report-utils.ts` 已区分：
  - `backend_live`
  - `backend_mock`
  - `backend_replay`
  - `demo_payload`
  - `frontend_fallback`
  - `unknown`
- 前端当前不是“只能显示 demo payload 的页面壳”，而是在真实消费后端 `report.provenance`。

### 5. replay 当前是“内部能力 + 文件草案”，不是公开产品能力

- retrieval cache 已提供内部控制入口，如 `retrieval_cache_only`。
- `data/demos/README.md` 已有 replay 文件落点和草案结构。
- 但当前仍没有公开 replay HTTP 接口，也没有最终冻结的 replay 术语体系。

## 当前仍未完成的事项

- `F8`：随机新闻与稳定 demo 的最终验收记录。
- 公开 HTML 之外的 URL 抽取扩展。
- 更稳定的 verdict / timeline 回归闭环。
- replay 的正式对外操作说明与公开接口是否需要暴露的最终决策。

## 现行阅读顺序

1. [../../README.md](../../README.md)
2. [../README.md](../README.md)
3. [../../backend/README.md](../../backend/README.md)
4. [../../frontend/README.md](../../frontend/README.md)
5. [../../overview/06_current_code_implementation.md](../../overview/06_current_code_implementation.md)
6. [../../overview/09_stage-progress-and-task-audit.md](../../overview/09_stage-progress-and-task-audit.md)
7. [../../overview/10_unfinished-task-priority-and-parallel-analysis.md](../../overview/10_unfinished-task-priority-and-parallel-analysis.md)

## 冲突处理规则

- 若 README、overview、tasks 中出现状态冲突，以本文件和对应代码实现为准。
- 被替换下来的冲突旧稿统一保留在 [../archive/conflicts/](../archive/conflicts/)。
