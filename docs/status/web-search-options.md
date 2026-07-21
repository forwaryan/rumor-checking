# 联网检索方案调查与选型

更新时间：2026-07-21（Asia/Shanghai）

这份文档记录"为真实用户核查当下热点"这一目标下，联网检索（web search）的方案调查、各入口结论和推荐方向，作为后续接入的决策依据。

## 为什么联网检索是核心功能，而不是可选项

- 产品目标是给真实用户核查**当下热点事件**的真假。
- 判定模型的知识有训练截止日期，对截止之后发生的新事件**无从判断**，只能答 `insufficient` 或产生幻觉。历史上"京东造游轮"（真实事件）被误判为 `refuted`，根因就是无证据时模型硬下结论。
- 没有真实联网，证据链机制（`evidence_result_id` grounding、来源 tier 分级、`independence_key`、provenance）都是挂在 mock 数据上的空壳。
- 结论：**要核查"当下"，联网检索绕不过去。** 唯一不联网也能判的是训练时就已学过的老谣言/常识谣言，但那不是本产品的目标场景。

## 一个必须分清的区分

选型时反复踩到的坑，是把下面两组概念混为一谈：

1. **App/网页版的"联网搜索"按钮 ≠ 官方 API 的联网能力。** 很多厂商聊天界面能联网，但通过代码调 API 时并不暴露该能力。
2. **内部判定网关 ≠ 厂商官方平台。** 当前判定模型走的是一层 OpenAI 兼容的**内部网关**，它只转发聊天补全（chat/completions），**不带任何搜索工具**。同名模型在**厂商官方平台**上才可能提供联网工具。二者是两个不同的入口、两套不同的密钥。

## 各入口调查结论（2026-07，基于官方文档）

| 入口 | API 能否联网 | 形式 | 中文覆盖 | 备注 |
| --- | --- | --- | --- | --- |
| 内部判定网关 | ❌ 否 | 只做 chat/completions | — | 纯判定代理，物理上不带搜索 |
| DeepSeek 官方 API | ❌ 否 | 联网仅在 App，API 不暴露 | — | 官方建议自行接第三方搜索作为 tool |
| 智谱 GLM 官方平台 | ✅ 是 | ①对话内嵌 `web_search` 工具 ②**独立 Web Search API**（纯搜索、不生成） | 好（国产） | 成熟稳定；按次计费约 0.01–0.05 元/次 |
| Kimi（月之暗面）官方平台 | ✅ 是 | `builtin_function` 的 `$web_search` | 好 | 官方标注"功能升级中，近期不建议使用"；生产暂排除 |
| Anthropic Claude API | ✅ 是 | 服务端 `web_search` 工具（`web_search_20260209`） | 待验证（大概率不如国产源） | 判定+联网一站式；全付费；对中文小众源覆盖存疑 |
| GDELT（代码已内置） | ✅ 是（免费无 key） | 独立新闻检索 HTTP 接口 | 弱（英文为主） | 中文小众源覆盖差，当下国内热点基本抓不到 |
| 境外 RAG 搜索（Tavily/Brave/Serper 等） | ✅ 是（有免费额度） | 独立搜索 API | 弱（中文小众源差） | 适合快速验证链路，不适合中文核查主场 |

## 架构取向：判定与检索解耦（B 方案）

不追求"一个模型既判定又联网"，而是让**独立搜索源**返回结构化结果（标题/摘要/URL）喂给**任意**判定模型：

- 判定层：继续用内部网关的现有模型，**不动**。
- 检索层：接一个独立搜索 provider，返回的 URL/来源/tier 复用现有证据分级与 grounding。
- 这正是当前代码已有的形状：`retrieval_provider.py` 里 `GdeltNewsProvider` 与 `LlmWebSearchProvider` 并列，新增一个搜索 provider 是顺着现有抽象走。
- 对核查产品的关键好处：证据**可追溯**（拿到原始 URL 与来源），而不是模型内部黑箱联网。

## 推荐方案

**判定：内部网关现有模型（不动） + 检索：智谱独立 Web Search API。**

理由：
- 中文热点核查，搜索源的**中文覆盖**是命根子，国产源明显强于境外 API 与 Claude 底层引擎。
- 判定层零改动，投入最小。
- 按次计费极低（1–5 分/次），对核查产品完全可接受；比"免费但中文弱"务实，比"付费又赌中文覆盖"的一站式方案更稳。
- 备选：博查（Bochaai）等其他国产 AI 搜索 API，同样中文覆盖好、可比较。
- Kimi 能力等价但官方自标"别用"，生产先排除。

## 需要人工确认/待办

- 智谱独立 Web Search API 走**厂商官方公网平台**（`open.bigmodel.cn`），需单独注册一个官方 key（后端已确认可出公网）。此 key 与内部判定网关是两个入口。
- 待确认：内部网关自身是否另挂了搜索类端点；若有，可优先用内部服务，省去外部注册。
- 接入方式：照官方文档新增独立搜索 provider，接进 `retrieval_service.py` 的 provider 选择逻辑，判定层不动，检索失败自动回落 mock。

## 出处

- DeepSeek API 文档：https://api-docs.deepseek.com
- 智谱对话内嵌搜索：https://docs.bigmodel.cn/cn/guide/tools/web-search.md
- 智谱独立 Web Search API：https://docs.bigmodel.cn/api-reference
- Kimi 联网搜索指南：https://platform.kimi.com/docs/guide/use-web-search
- Anthropic web search 工具：https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool
