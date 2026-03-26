# 演示脚本与口播提纲

更新时间：2026-03-26（Asia/Shanghai）

## 一句话介绍

> 这是一个新闻核查工作台。当前稳定交付的是默认 `off + mock + fallback=true` 基线上的结构化核查演示，以及 `backend_live / backend_mock / unknown` provenance 边界展示，而不是“真实检索已对随机新闻稳定较真”。

## 演示前先说清楚

- 当前对外最稳的是 `expired-yogurt` 这条主线
- `morningstar-question` 适合答辩补充，不适合默认开场
- `viral-death-ambiguous` 适合讲 `safe_mode` 边界
- 前端 demo 卡片只是填充输入，真正分析仍走后端 `analyze/stream`
- 当前没有 `replay` 接口，也没有本地 demo payload 回放路径
- 如果后端起不来，今天就不应讲“交互式演示已可运行”

## 推荐演示节奏

### 5 分钟产品版

1. 打开页面，说明输入方式和 provenance 标签。
2. 演示 `expired-yogurt`，重点讲结构化输出、claim、时间线和风险提示。
3. 指出当前这条结果来自 `backend_mock` 还是 `backend_live`，强调 provenance 不能省略。
4. 补一个 `safe_mode` 边界输入，说明系统在证据不足时会保守收口。

### 8 到 10 分钟答辩版

1. 开场先讲当前默认基线是 `mock` 路径，不承诺真实检索已收口。
2. 用 `expired-yogurt` 讲完整结构化输出。
3. 用 `morningstar-question` 讲 question-first 和 partial 边界。
4. 用 `viral-death-ambiguous` 讲为什么不能直接给真假概率。
5. 最后补工程点：stream、golden cases、Smoke、回归入口。

## 主线样例

### `expired-yogurt`

输入：

```text
3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。
```

建议讲法：

> 这条样例用来演示系统如何把一段新闻拆成结构化结果。页面会给事件摘要、claim、时间线、证据和风险提示，同时会明确标注 provenance，避免把 mock 结果讲成真实联网核查。

不要讲过头的地方：

- 不要说“这已经证明真实互联网检索稳定通过”
- 不要只讲 `complete_mode`，不讲 provenance
- 不要把时间线讲成完整传播链还原

### `morningstar-question`

输入：

```text
晨星生物裁员40%是真的吗？
```

建议讲法：

> 这条样例主要说明系统也能处理问句输入，会先把问句改写成待核查 claim，再结合 retrieval 结果决定哪些说法可以被反驳、哪些仍需要保留边界。

### `viral-death-ambiguous`

输入：

```text
最近有个女网红脑出血死了真的假的？
```

建议讲法：

> 这类输入的问题不在于模型有没有意见，而在于公开证据是否足够支持确定结论。系统宁可停在 `safe_mode`，也不会把模糊传闻包装成确定性判断。

## 常见追问

**Q：现在已经能查任意新闻了吗？**

建议回答：

> 还不能这么说。当前正式稳定的是 mock 基线下的结构化核查能力和 provenance 边界展示，真实检索链路仍只适合内部诊断。

**Q：如果后端挂了，页面还能完整演示吗？**

建议回答：

> 当前不再保留本地 demo payload 回放。后端起不来时，页面只能展示错误态和已有静态壳，不应把它讲成完整交互演示。

**Q：为什么不是直接让 LLM 给一个真假概率？**

建议回答：

> 因为题目要求的不只是结论，还包括传播链和内容核查两条可解释主流程。我们要先拆 claim、组织证据、标清 provenance，再谈可信度。

## 一句话结论

截至 2026-03-26，最稳的演示主线是：`expired-yogurt` + 默认 `off/mock` 基线 + provenance 边界；如果后端不可用，就不应继续讲“交互式演示仍可完整运行”。
