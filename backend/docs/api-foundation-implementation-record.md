# API Foundation Implementation Record

## 1. 文档目的

这份文档记录 `Cluster-C / API Foundation` 当前已经落地的实现，回答四个问题：

1. 当前已经做完了什么。
2. 当前 API 的真实请求和响应是什么。
3. 后端内部主链路是怎么串起来的。
4. 后续接手应该从哪里继续。

本文反映的是 2026-03-13 最新状态，已经包含两轮实现：

- 第一轮：完成 `C1` 到 `C8` 的最小可运行 FastAPI mock 主链路。
- 第二轮：完成共享 contract 对齐和前后端 integration 对齐。

## 2. 当前完成范围

### 已完成

- `C1` FastAPI 项目骨架。
- `C2` 统一配置、日志、异常处理。
- `C3` `GET /api/v1/health` 与统一错误响应。
- `C4` mock 版 `input_normalizer`。
- `C5` mock 版 `claim_extractor`。
- `C6` mock 版 `verdict_engine`。
- `C7` `report_builder` 与模式选择逻辑。
- `C8` `POST /api/v1/analyze` 编排接口。
- `contracts/` 已存在时，对齐后端 `Report` 输出结构。
- 对齐前端 `api-client` 的请求映射和响应解析。

### 未完成

- `C9` 真实 Kimi provider 接入。
- `C10` 真实 URL 正文抽取与 fallback 增强。
- `demo-cases / replay` 的后端正式接口仍未实现，前端暂走本地 fallback。

## 3. 这次实现后的关键结论

### 结论一：`POST /api/v1/analyze` 现在返回裸 `Report`

不再返回临时包装结构：

```json
{
  "request_id": "...",
  "report": { ... }
}
```

当前真实返回就是共享 contract 定义的 `Report` 本体。

### 结论二：后端已经兼容前端现有请求字段

后端现在同时接受：

- 新字段：`raw_input`
- 兼容字段：`input`

这意味着前端不需要先整体重写表单层，API client 可以平滑过渡。

### 结论三：后端内部仍保留 draft 模型，公共输出完全按 contract 组装

内部归一化阶段使用的是 `NormalizedEvent`，而对外输出时会再组装成 contract 要求的 `Event / ClaimResult / TimelineNode / Report`。

这样做的原因：

- 内部逻辑需要保留 `fallback_used`、`raw_input`、`mode_hint` 等调试和编排字段。
- 共享输出不能泄露这些内部字段，否则会破坏 `contracts/*.schema.json` 的边界。

## 4. 当前关键文件

### 4.1 应用入口与 API

- `backend/app/main.py`
  - 创建 FastAPI 应用。
  - 注册 request id 中间件。
  - 注册统一异常处理。
  - 以 `/api/v1` 为前缀挂载 API。
- `backend/app/api/v1/endpoints/health.py`
  - 健康检查。
- `backend/app/api/v1/endpoints/analyze.py`
  - 主分析接口，直接返回 `Report`。

### 4.2 基础设施

- `backend/app/core/config.py`
  - 环境变量与默认配置。
- `backend/app/core/logging.py`
  - 日志初始化。
- `backend/app/core/exceptions.py`
  - `AppError` 与统一错误返回结构。

### 4.3 数据模型

- `backend/app/models/schemas.py`
  - 公共 contract 模型：`Event / EvidenceItem / TimelineNode / ClaimResult / Report`
  - 内部 draft 模型：`NormalizedEvent`
  - 请求模型：`AnalyzeRequest`

### 4.4 服务层

- `backend/app/services/contract_utils.py`
  - 时间格式归一化、默认 source 生成。
- `backend/app/services/input_normalizer.py`
  - 输入类型映射、URL fallback、事件草稿归一化。
- `backend/app/services/claim_extractor.py`
  - mock claim 输出与基础分类。
- `backend/app/services/verdict_engine.py`
  - 规则型 verdict 生成。
- `backend/app/services/timeline_builder.py`
  - 最小 timeline 输出。
- `backend/app/services/report_builder.py`
  - mode 选择与最终 Report 组装。
- `backend/app/services/analyze_pipeline.py`
  - 总编排入口。
- `backend/app/services/scenario_library.py`
  - 最小 case 的固定模板库。

### 4.5 前端集成点

- `frontend/lib/api-client.ts`
  - 把前端的 `AnalyzeRequest` 映射到后端接口字段。
  - 兼容解析“裸 Report”和旧包装响应。
- `frontend/types/report.ts`
  - 前端消费的 Report 类型，当前与 contract 一致。
- `frontend/components/analyze-page.tsx`
  - 页面分析提交流程。

## 5. 当前 API 真实定义

### 5.1 根路由

- 路径：`GET /`
- 用途：暴露服务名、版本、docs 路径和 health 路径。

### 5.2 健康检查

- 路径：`GET /api/v1/health`
- 返回字段：
  - `status`
  - `service`
  - `environment`
  - `version`

### 5.3 主分析接口请求

- 路径：`POST /api/v1/analyze`

当前后端接受的最小请求体：

```json
{
  "raw_input": "..."
}
```

同时兼容前端旧字段：

```json
{
  "input": "...",
  "input_type": "text"
}
```

`input_type` 当前接受两套值：

- 前端风格：`auto / text / url / question`
- 后端内部风格：`text_news / url_news / url_unknown / question_only`

### 5.4 主分析接口响应

当前直接返回 `Report`：

```json
{
  "mode": "complete_mode",
  "event": { ... },
  "timeline": [ ... ],
  "claim_results": [ ... ],
  "final_summary": "...",
  "risks": [ ... ],
  "sources": [ ... ]
}
```

## 6. 统一错误响应

统一错误体定义在 `backend/app/core/exceptions.py`，格式如下：

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

当前覆盖：

- `validation_error`
- `http_error`
- `internal_server_error`
- 业务层 `AppError`

## 7. Contract 对齐是怎么做的

### 7.1 顶层字段从 `evidence` 改为 `sources`

最早的后端临时结构使用的是 `evidence`。现在已经改成和 `contracts/report.schema.json` 一致的 `sources`。

### 7.2 `Event` 不再暴露内部字段

内部仍然保留：

- `raw_input`
- `input_type`
- `mode_hint`
- `fallback_used`
- `fallback_reason`

但这些字段不会再出现在对外 `Report.event` 中。

### 7.3 `ClaimResult` 不再返回可空 verdict

共享 contract 要求：

- `verdict` 必填
- `confidence` 必填
- `notes` 必填

因此对 `opinion / prediction / unverifiable`，当前统一以：

- `verdict = insufficient`
- `confidence = low`
- `notes = 明确写清楚为什么不做强判`

### 7.4 `TimelineNode` 字段已经改成 contract 定义

当前对外字段是：

- `node_type`
- `title`
- `url`
- `source_name`
- `published_at`
- `summary`
- `why_selected`

不再使用旧的内部字段组合：

- `date`
- `description`
- `source_url`
- `confidence`

## 8. Input Normalizer 当前规则

### 8.1 输入类型映射

后端现在支持两层映射：

- `text -> text_news`
- `url -> url_news`
- `question -> question_only`
- `auto -> 自动推断`

### 8.2 URL 无正文时不再直接报错

之前 URL 输入没有 `mock_fetch_result` 会直接报错。现在改成：

- 生成一个保守的 `NormalizedEvent`
- 进入 fallback
- 最终通常输出 `safe_mode`

这样可以让前端在 URL 抽取链路还没接入时也拿到结构化回退结果，而不是直接 400。

### 8.3 时间字段统一转成 `date-time`

`contracts/` 要求 `published_at` 是 `date-time`。

因此现在：

- 如果原始数据只有 `YYYY-MM-DD`
- 会统一补成 `YYYY-MM-DDT00:00:00+08:00`

缺失时则回退到当前时间戳。

## 9. 主链路编排

`backend/app/services/analyze_pipeline.py` 当前执行顺序：

1. 接收 `AnalyzeRequest`
2. `InputNormalizer.normalize()` 输出 `NormalizedEvent`
3. `ClaimExtractor.extract()` 输出 claim
4. `VerdictEngine.evaluate()` 生成 claim results 和 sources 候选
5. `TimelineBuilder.build()` 生成 timeline
6. `ReportBuilder.build()` 组装最终 `Report`

## 10. 场景库的定位

`scenario_library.py` 当前不是长期架构终态，而是为最小测试集提供稳定输出的中间层。

它当前承担：

- 已知 case 的标题、摘要、关键词模板
- 固定 claim 模板
- mock evidence
- mock timeline

这样做的直接收益：

- 前端和测试可以在 provider 未接入前稳定联调
- 后续替换真实 provider 时，改造点集中

## 11. 当前已知边界

当前实现仍然是“可联调的 mock 后端”，不是生产级核查系统。

明确缺口：

- 没有真实 LLM provider
- 没有真实 URL 正文抽取
- 没有真实检索与时间线生成
- `demo-cases / replay` 仍未下沉到后端
- 当前规则覆盖的仍然是最小测试集和少量 generic fallback

## 12. 测试与验证

### 12.1 后端验证

已执行：

```text
python -m compileall backend\app backend\tests
pytest backend\tests -q
```

结果：

- `compileall` 通过
- `pytest backend\tests -q` 通过，当前为 `8 passed`

### 12.2 新增覆盖点

相比第一轮实现，这次新增验证了：

- `POST /api/v1/analyze` 返回的是裸 `Report`
- 返回顶层字段包含 `sources`
- 前端风格请求体 `input + input_type=text` 可以直接被后端接收

### 12.3 前端验证

已验证前端 TypeScript 类型检查通过，命令实际为：

```text
cmd /c "pushd \\wsl.localhost\Ubuntu-20.04\home\forwaryan\mianshi\rumor-checking\frontend && node node_modules\typescript\bin\tsc --noEmit && popd"
```

之所以不用直接 `npm run typecheck`，是因为当前环境存在两个独立问题：

- Windows `npm` 无法直接以 UNC 路径作为当前目录
- WSL 内 Node 版本过旧，无法执行当前 TypeScript 版本

这些都属于环境问题，不是这次改动引入的代码错误。

## 13. 当前环境问题记录

运行验证时观察到的环境问题：

- Python 全局环境有既有依赖冲突告警
- WSL 内 Node 版本偏旧
- 直接在 Windows 上对 WSL UNC 路径跑 `npm` 会失败

这些问题没有阻断当前联调，但后续如果继续深入前后端开发，建议尽快补两件事：

1. 后端使用独立 venv
2. 前端固定 Node 版本并统一在单一环境中执行

## 14. 下一步建议

技术上最合理的下一阶段顺序是：

1. 先实现后端 `demo-cases / replay` 正式接口，去掉前端本地 fallback 的不一致来源
2. 再接 `C9`，把事件理解和 claim 抽取替换为真实 provider
3. 再接 `C10`，补真实 URL 抽取和降级说明
4. 最后把 timeline 与 evidence 从固定模板迁移到真实检索输出

## 15. 接手时最值得先看的文件

- `backend/app/models/schemas.py`
- `backend/app/services/input_normalizer.py`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `backend/app/services/analyze_pipeline.py`
- `frontend/lib/api-client.ts`
- `backend/tests/test_api.py`

## 16. 当前状态结论

到这一版为止，`Cluster-C / API Foundation` 已经不是“目录骨架”，而是一个可以直接给前端调用、并且与共享 contract 对齐的最小后端实现。

它当前已经具备：

- 可启动的 FastAPI 服务
- 健康检查
- 统一错误结构
- 裸 `Report` 输出
- 前端兼容请求输入
- mock 分析主链路
- 回归测试与类型验证

后续工作重点不再是“先把 API 壳搭起来”，而是“在不破坏 contract 的前提下，逐步把 mock 能力替换成真实能力”。
