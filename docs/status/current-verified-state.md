# 当前已核验状态

更新时间：2026-03-26（Asia/Shanghai）

这份文档只保留已经被当前代码核验过的事实，用来约束 README 和现行运行文档的口径。

## 核验依据

已直接核对以下实现或测试文件：

- `backend/app/api/v1/endpoints/analyze.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/models/schemas.py`
- `backend/app/services/report_builder.py`
- `frontend/components/analyze-page.tsx`
- `frontend/components/status-banner.tsx`
- `frontend/lib/api-client.ts`
- `frontend/lib/report-utils.ts`
- `contracts/report.schema.json`

## 已确认事实

### 1. 当前公开 API

当前公开路由只有：

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`

当前没有公开的：

- `GET /api/v1/demo-cases`
- `POST /api/v1/replay`

### 2. provenance 已收敛

`report.provenance.source_type` 当前 contract 与实现只保留：

- `backend_live`
- `backend_mock`

前端缺失 provenance 时，会保守落到 `unknown` 展示，但这不是后端返回值枚举的一部分。

### 3. 前端不再消费本地报告 JSON

- demo 卡片当前只负责填充稳定输入样例
- 前端分析结果来自后端 `analyze` 或 `analyze/stream`
- `contracts/demo_payloads/*.json` 已移除
- 当前也不再生成本地 `frontend_fallback` 报告壳

### 4. 默认基线仍是 mock 路径

默认环境仍是：

- `ANALYSIS_PROVIDER=off`
- `RETRIEVAL_PROVIDER=mock`
- `RETRIEVAL_FALLBACK_TO_MOCK=true`

因此当前最稳的对外口径仍然是 `mock demo + provenance 边界`，而不是“真实检索已稳定通过”。

### 5. URL 抽取与检索边界

- URL 输入已支持公开 HTML 页面抽取
- 不支持登录页、强反爬页面、浏览器渲染页面、PDF 或图片正文
- live retrieval 仍未达到可对外交付的稳定口径

## 当前仍未完成的事项

- 真实 live retrieval 路径的稳定通过样本
- 公开 HTML 之外的 URL 抽取扩展
- 若未来确实需要 replay，是否公开接口和如何冻结术语体系

## 使用规则

- 若其他文档和当前代码实现冲突，以本文件和对应实现为准
- 这份文档只记录当前仍有效的事实，不再维护历史冲突登记表
