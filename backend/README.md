# Backend

本目录承载 rumor-checking 的后端主链路。当前已经提供：

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- 统一配置、`request_id` 中间件、统一错误响应
- 与 `contracts/` 对齐的裸 `Report` 输出
- 规则链路 + 可选 Kimi provider enrichment

## 当前状态

- `C1` 到 `C8` 已完成并稳定可测
- `C9` 已进入第一阶段：Kimi provider 配置、调用封装、事件/claim enrichment、安全回退与测试已完成
- `C10` 尚未开始，URL 正文抽取仍未接入

## 快速框架图

```mermaid
flowchart LR
    Client["Frontend / Test"] --> API["FastAPI /api/v1"]
    API --> Pipeline["AnalyzePipeline"]
    Pipeline --> Normalizer["InputNormalizer"]
    Pipeline --> Enricher["ProviderEnricher"]
    Enricher --> Kimi["KimiProvider"]
    Pipeline --> Verdict["VerdictEngine"]
    Pipeline --> Timeline["TimelineBuilder"]
    Pipeline --> Report["ReportBuilder"]
    Report --> Output["Report"]
```

更完整的架构图、时序图、provider 回退流程图、请求/响应样例和演进路线图见 [backend/docs/api-foundation-implementation-record.md](/home/forwaryan/mianshi/rumor-checking/backend/docs/api-foundation-implementation-record.md)。

## Provider 开关

当前真实 provider 默认关闭，只有显式配置后才会调用：

- `ANALYSIS_PROVIDER=off|kimi`
- `KIMI_API_KEY`
- `KIMI_BASE_URL`，默认 `https://api.moonshot.cn/v1`
- `KIMI_MODEL`，默认 `moonshot-v1-8k`
- `PROVIDER_TIMEOUT_SECONDS`，默认 `20`

当前 provider 只负责“事件理解 + claim 抽取”增强，不负责 verdict、timeline、URL 抽取或检索。
如果 provider 未配置、超时、返回非法 JSON，后端会自动退回既有规则链路，不中断 `analyze` 请求。
## 真实检索开关

当前检索支持三种模式：

- `RETRIEVAL_PROVIDER=mock`：只走本地 mock retrieval，适合稳定回归
- `RETRIEVAL_PROVIDER=gdelt`：走公开 GDELT provider，失败时可回退到 mock
- `RETRIEVAL_PROVIDER=off`：关闭检索，只保留保守链路

相关环境变量：

- `RETRIEVAL_TIMEOUT_SECONDS`，默认 `12`
- `RETRIEVAL_GDELT_BASE_URL`，默认 `https://api.gdeltproject.org/api/v2/doc/doc`
- `RETRIEVAL_MAX_RESULTS`，默认 `8`
- `RETRIEVAL_CACHE_ENABLED`，默认 `true`
- `RETRIEVAL_CACHE_TTL_SECONDS`，默认 `43200`
- `RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR`，默认 `true`
- `RETRIEVAL_FALLBACK_TO_MOCK`，默认 `true`
- `RETRIEVAL_CACHE_DIR`，默认 `data/cache/retrieval`

当 `RETRIEVAL_PROVIDER=gdelt` 时，`question_only` 输入会先做查询改写，再走“真实检索 -> 去重归并 -> evidence / timeline”主链路。
内部还预留了三个 request-level 开关，供 replay 或 smoke 使用：

- `request_context.bypass_retrieval_cache=true`
- `request_context.retrieval_cache_only=true`
- `request_context.allow_stale_retrieval_cache=true`

注意：当前“真实检索”解决的是公开来源候选抓取，不是完整的 agent 上网调查；verdict 和 timeline 仍是基于已检索证据的规则/启发式判断。

## 如何提供你的 Kimi Key

当前后端会在读取进程环境变量之前，先尝试读取以下文件中的配置：

1. 仓库根目录 `.env`
2. `backend/.env`

进程环境变量优先级更高；如果 shell 里已经设置了同名变量，会覆盖 `.env` 文件中的值。

推荐做法：

1. 复制 `backend/.env.example` 为 `backend/.env`
2. 在 `backend/.env` 中填写：

```text
ANALYSIS_PROVIDER=kimi
KIMI_API_KEY=你的真实 key
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-8k
PROVIDER_TIMEOUT_SECONDS=20
```

3. 启动后端：

```bash
uvicorn backend.app.main:app --reload
```

这样就不需要每次在终端里手动 `set` 环境变量。

## 最小联调方式

先检查服务是否启动：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

再发送一条文本新闻输入：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "input": "网传某地出台新规，要求周末全面停工整顿，相关图片正在社交平台传播。",
    "input_type": "text_news"
  }'
```

如果 `ANALYSIS_PROVIDER=kimi` 且 `KIMI_API_KEY` 有效，后端会尝试调用 Kimi 做事件理解与 claim 抽取；如果 provider 失败，接口仍会返回规则链路结果。

## 如何判断当前是否真的走了 Kimi

当前最实用的判断方式是：

- 使用 `text_news` 输入，而不是 URL 输入
- 在日志中观察 provider 是否有超时、网络或 JSON 解析回退
- 对比开启和关闭 `ANALYSIS_PROVIDER` 时，事件摘要和 claim 抽取结果是否发生变化

注意：当前 provider 还没有完成“线上真实 key 小样本验收”和“prompt/输出质量调优”，所以“能调用”不等于“质量已收口”。

## 目录边界

- `app/api/`
  路由与接口编排入口。
- `app/core/`
  配置、日志、异常处理等基础设施。
- `app/models/`
  后端内部 schema 与对外 contract 模型。
- `app/services/`
  输入标准化、provider enrichment、claim、verdict、timeline、report 编排。
- `tests/`
  pytest、主链路回归与 provider 回退测试。
- `docs/`
  实现记录、交接文档与补充说明。

## 本地运行

1. `python -m pip install -r backend/requirements-dev.txt`
2. 如需启用真实 provider，按上文在 `backend/.env` 或 shell 中配置环境变量
3. `uvicorn backend.app.main:app --reload`
4. 访问 `http://127.0.0.1:8000/docs`

## 当前已知边界

- 已支持 `RETRIEVAL_PROVIDER=gdelt` 的公开来源检索、缓存与 `question_only` 取证；但 verdict 和 timeline 仍是基于检索结果的规则/启发式判断，不是完整 RAG / agent 搜证系统
- URL 输入仍未接入正文抽取，`C10` 尚未开始
- `demo-cases / replay` 后端接口仍未实现，但当前前端已不依赖这两个接口
- 共享协议仍以 `contracts/` 为准，后续 schema 冻结变更仍需同步更新后端与前端
- 测试数据仍优先读取根目录 `evals/minimal_v1/`
