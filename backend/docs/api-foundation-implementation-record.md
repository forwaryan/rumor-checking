# API Foundation Implementation Record

## 1. 文档目的

这份文档记录 `Cluster-C / API Foundation` 当前已经落地的实现，回答三个问题：

1. 已经做了什么。
2. 具体是怎么做的。
3. 当前边界和后续接手点在哪里。

本文对应的是 2026-03-13 完成的后端最小可运行版本，覆盖 `C1` 到 `C8`，但仍停留在 mock / rule-based 阶段，还没有进入 `C9` 和 `C10` 的真实 provider 与 URL 抽取阶段。

## 2. 本次交付范围

### 已完成范围

- `C1` FastAPI 项目骨架。
- `C2` 统一配置、日志、异常处理。
- `C3` `GET /api/v1/health` 与统一错误响应。
- `C4` mock 版 `input_normalizer`。
- `C5` mock 版 `claim_extractor`。
- `C6` mock 版 `verdict_engine`。
- `C7` `report_builder` 与模式选择逻辑。
- `C8` `POST /api/v1/analyze` 编排接口。

### 未完成范围

- `C9` 真实 Kimi provider 接入。
- `C10` 真实 URL 正文抽取与 fallback 增强。

## 3. 新增或修改的关键文件

### 应用入口与 API

- `backend/app/main.py`
  - 创建 FastAPI 应用。
  - 注入 request id 中间件。
  - 注册统一异常处理。
  - 以 `/api/v1` 为前缀挂载 API 路由。
- `backend/app/api/router.py`
  - 聚合 v1 路由。
- `backend/app/api/v1/endpoints/health.py`
  - 提供健康检查接口。
- `backend/app/api/v1/endpoints/analyze.py`
  - 提供主分析接口。

### 基础设施

- `backend/app/core/config.py`
  - 定义环境变量读取和默认配置。
- `backend/app/core/logging.py`
  - 初始化日志级别和格式。
- `backend/app/core/exceptions.py`
  - 定义 `AppError`。
  - 统一 4xx / 5xx JSON 响应结构。

### 数据模型

- `backend/app/models/schemas.py`
  - 定义请求体、响应体、`EventDraft`、`ClaimResult`、`TimelineNode`、`Report` 等最小 schema。

### 服务编排

- `backend/app/services/scenario_library.py`
  - 存放最小 case 的事件模板、claim、evidence、timeline。
- `backend/app/services/input_normalizer.py`
  - 做输入类型识别、标题/摘要/关键词抽取和 fallback 判断。
- `backend/app/services/claim_extractor.py`
  - 输出 claim 列表，并做基础 claim type 分类。
- `backend/app/services/verdict_engine.py`
  - 根据规则与 mock evidence 输出 verdict 和 confidence。
- `backend/app/services/timeline_builder.py`
  - 构建最小 timeline 节点。
- `backend/app/services/report_builder.py`
  - 决定 `complete_mode / partial_mode / safe_mode`。
  - 组装统一 `Report`。
- `backend/app/services/analyze_pipeline.py`
  - 串联全部服务，形成主链路。

### 测试与依赖

- `backend/tests/conftest.py`
  - 读取 `evals/minimal_v1` 数据。
  - 创建 `TestClient`。
- `backend/tests/test_api.py`
  - 覆盖 health、422、500、complete、partial、safe 这几类主链路。
- `backend/requirements.txt`
  - 运行依赖。
- `backend/requirements-dev.txt`
  - 测试依赖。
- `backend/.env.example`
  - 环境变量示例。

## 4. API 设计

### 4.1 根路由

- 路径：`GET /`
- 用途：暴露服务名、版本、docs 路径和 health 路径。

### 4.2 健康检查

- 路径：`GET /api/v1/health`
- 返回字段：
  - `status`
  - `service`
  - `environment`
  - `version`

### 4.3 主分析接口

- 路径：`POST /api/v1/analyze`
- 请求体最小字段：
  - `raw_input`
- 可选字段：
  - `input_type`
  - `mock_fetch_result`
  - `mock_evidence`
  - `request_context`

### 4.4 主分析接口返回

最外层结构：

- `request_id`
- `report`

`report` 当前最小字段：

- `mode`
- `event`
- `claim_results`
- `timeline`
- `evidence`
- `final_summary`
- `risks`
- `unknowns`
- `next_steps`
- `boundary`
- `fallback`

## 5. 统一错误响应设计

统一错误体定义在 `backend/app/core/exceptions.py`，结构如下：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "trace_id": "...",
    "details": {}
  }
}
```

当前覆盖的错误类型：

- `validation_error`
  - FastAPI 请求体验证失败。
- `http_error`
  - Starlette / FastAPI 标准 HTTP 错误。
- `internal_server_error`
  - 未捕获异常。
- 业务层自定义 `AppError`
  - 例如不支持的输入类型、URL 输入缺少 `mock_fetch_result`。

设计原因：

- 前端不需要分散处理多种不一致错误体。
- 测试可以稳定断言 `code / message / trace_id`。
- 后续接入真实 provider 时可以继续沿用同一结构。

## 6. 配置与日志

### 6.1 配置

当前从环境变量读取以下配置：

- `APP_NAME`
- `APP_ENV`
- `APP_VERSION`
- `APP_LOG_LEVEL`
- `APP_DEBUG`
- `API_V1_PREFIX`

默认值写在 `backend/app/core/config.py`，示例写在 `backend/.env.example`。

### 6.2 日志

日志格式：

```text
%(asctime)s | %(levelname)s | %(name)s | %(message)s
```

当前日志重点：

- 应用启动日志。
- 业务错误日志。
- 未捕获异常日志。

## 7. Analyze 主链路怎么工作的

`backend/app/services/analyze_pipeline.py` 是总编排入口，执行顺序如下：

1. 接收 `AnalyzeRequest`。
2. `InputNormalizer.normalize()`
   - 判断输入类型：`text_news / url_news / url_unknown / question_only`。
   - 输出最小 `EventDraft`。
3. `ClaimExtractor.extract()`
   - 输出 1 到 4 条 claim。
   - 为 claim 标注 `fact / opinion / prediction / unverifiable`。
4. `VerdictEngine.evaluate()`
   - 对可判定的事实 claim 输出 `supported / refuted / insufficient / conflicting`。
5. `TimelineBuilder.build()`
   - 输出最小 timeline 节点。
6. `ReportBuilder.build()`
   - 根据证据强度、可判定 claim 数量、timeline 完整度和 fallback 状态决定模式。
   - 拼装最终 `Report`。

## 8. Input Normalizer 的具体规则

### 8.1 输入类型推断

推断规则：

- 以 `http://` 或 `https://` 开头，默认认为是 URL 输入。
- 以 `? / ？` 结尾，或含有“真的吗”，认为是 `question_only`。
- 其他默认作为 `text_news`。

### 8.2 URL 输入处理

- 如果传入的是 URL 类输入，当前 mock 后端要求同时提供 `mock_fetch_result`。
- `mock_fetch_result.status != ok`，或者正文为空时，判为 fallback。
- fallback 时会写入：
  - `event.fallback_used = true`
  - `event.fallback_reason = url_content_incomplete`

### 8.3 问题输入处理

对于 `question_only`：

- 不伪造 `source_name`。
- 不伪造 `published_at`。
- 模式提示直接向 `safe` 倾斜。

这个约束来自最小测试集中的明确边界。

## 9. Claim Extractor 的具体规则

当前是规则型实现，不做真实 NLP 抽取。

实现方式：

- 先用 `scenario_library` 把已知 case 映射到固定 claim 模板。
- 对未知 case，至少返回一条从摘要派生的保守 claim。
- 用关键词规则区分：
  - `opinion`
  - `prediction`
  - `unverifiable`
  - 默认 `fact`

这样做的原因：

- 当前目标是先把 API 主链路和返回结构跑通。
- 在 `contracts/` 和真实 provider 冻结之前，不应过早把抽取逻辑复杂化。

## 10. Verdict Engine 的具体规则

当前 verdict 不是通用推理引擎，而是最小 case 的规则映射。

### 可输出的 verdict

- `supported`
- `refuted`
- `insufficient`
- `conflicting`

### 当前判定原则

- `opinion / prediction / unverifiable`
  - 不进入标准 verdict，保留为不可判定。
- 无证据链时
  - 不允许硬判 `supported / refuted`。
- 冲突证据并存时
  - 优先输出 `conflicting`。
- 只有低质量、片段化信息时
  - 保守输出 `insufficient`。

### 当前已编码的场景

- 海州新鲜屋过期酸奶通报。
- 清河渡轮停航与大雾。
- 晨星生物裁员 40% 传闻。
- 北川中学停课传闻。
- 北城区化工厂异味投诉。
- 未匹配 case 的 generic 保守场景。

## 11. Timeline Builder 的当前策略

当前 timeline 也是最小可运行策略：

- 对已知 case 使用固定 timeline 模板。
- 对 `question_only` 且无明确传播链的 case，允许返回空 timeline。
- 对 generic case，返回一个 placeholder 节点，避免结构完全缺失。

这里没有做真实检索筛选，也没有做时间排序纠偏，这一部分仍属于后续增强点。

## 12. Report Builder 的模式选择逻辑

当前模式选择依据四个变量：

- `evidence_grade`
- 可判定 claim 数量
- timeline 节点数量
- 是否使用 fallback

### `complete_mode`

进入条件偏严格：

- 证据等级高。
- 至少有 2 条可判定 claim。
- 至少有 2 个 timeline 节点。
- 没有 fallback。

### `partial_mode`

适用情形：

- 已经有部分可核验结论。
- 但传播链、证据完整度或一致性还不够。

### `safe_mode`

适用情形：

- `question_only` 且缺少可判定证据。
- fallback 后仍无法形成可判定证据链。
- 整体只能给出下一步建议，不能给强结论。

## 13. 为什么引入 `scenario_library`

这不是长期架构终态，但对当前阶段是必要的。

目的：

- 让最小测试集可以稳定跑通。
- 把“事件模板 / claim / evidence / timeline”先集中管理。
- 避免把 case 规则分散硬编码在多个 service 文件里，后续替换 provider 时更容易清理。

后续演进方向：

- 先把 `scenario_library` 中的理解逻辑替换为真实模型调用。
- 再逐步把固定 evidence / timeline 模板替换为真实检索结果。

## 14. 测试怎么做的

### 14.1 测试来源

测试数据直接读取根目录：

- `evals/minimal_v1/input_cases.json`

没有把数据复制到 `backend/`，保持和仓库边界一致。

### 14.2 覆盖项

`backend/tests/test_api.py` 当前覆盖：

- `GET /api/v1/health` 成功返回。
- 请求体为空时返回统一 422 错误结构。
- 文本新闻输入进入 `complete_mode`。
- 问题输入进入 `safe_mode`。
- URL fallback 输入保持保守输出。
- 化工厂冲突 case 进入 `partial_mode` 且出现 `conflicting`。
- 主链路内部异常进入统一 500 错误结构。

### 14.3 测试中实际处理过的问题

在首次测试中遇到两个问题：

1. `evals/minimal_v1/*.json` 带 BOM。
   - 修正方式：测试夹具读取时改用 `utf-8-sig`。
2. `TestClient` 默认会重新抛出服务端异常。
   - 修正方式：`raise_server_exceptions=False`，这样才能断言统一 500 错误体。

这两个修正已经记录在 `backend/tests/conftest.py`。

## 15. 实际验证结果

本次实现完成后执行过以下验证：

```text
python -m compileall backend\app backend\tests
pytest backend\tests -q
```

结果：

- `compileall` 通过。
- `pytest backend\tests -q` 结果为 `7 passed`。

## 16. 安装依赖时的环境情况

为跑测试，实际安装了：

- `fastapi==0.109.2`
- `uvicorn==0.30.6`
- `httpx==0.27.2`
- `pytest==8.3.5`

安装过程中，当前机器的全局 Python 环境还提示了已有包冲突告警，例如：

- `selenium` 对 `typing_extensions` 的版本要求不同。
- `tensorflow-intel` 对 `numpy / protobuf` 的版本要求不同。

这些告警没有阻断本次后端测试，但说明当前环境不是隔离虚拟环境。后续如果要稳定开发，建议切到独立 venv。

## 17. 当前明确边界

当前方案是“把 API 骨架和最小报告链路跑通”，不是“已经完成生产级核查引擎”。

明确缺口：

- 没有真实 LLM provider。
- 没有真实 URL 抽取。
- 没有真实检索与 timeline 生成。
- `contracts/` 还在演进中，字段后续可能需要再对齐。
- 当前规则库只覆盖最小测试集及少量保守 fallback。

## 18. 后续接手建议

### 下一阶段优先级

1. 先冻结 `contracts/` 的 schema。
2. 把 `AnalyzeRequest / AnalyzeResponse / Report` 字段与 schema 对齐。
3. 接 `C9`，优先替换事件理解和 claim 抽取。
4. 接 `C10`，补 URL 正文抽取和降级提示。
5. 最后把 timeline 和 evidence 从固定模板迁移到真实检索输出。

### 接手时最值得先看的文件

- `backend/app/main.py`
- `backend/app/core/exceptions.py`
- `backend/app/models/schemas.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/services/scenario_library.py`
- `backend/app/services/report_builder.py`
- `backend/tests/test_api.py`

## 19. 结论

当前 `Cluster-C / API Foundation` 已经具备以下能力：

- 服务可启动。
- 有 health 接口。
- 有统一错误结构。
- 有可被前端直接调用的 `POST /api/v1/analyze`。
- 能基于最小测试集输出结构化 `Report`。
- 有基础自动化测试兜底。

这意味着后续前端、合同 schema、真实 provider、检索模块都已经有了一个明确的后端落点，而不是继续围绕空目录协作。
