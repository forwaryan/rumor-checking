# 演示脚本与口播提纲

更新时间：2026-03-15（Asia/Shanghai）

## 1. 这份文档给谁用

这份文档给两类人用：

- 第一次接手这个仓库、需要快速准备 demo 的人
- 面试现场负责口播和操作的人

目标不是把实现讲全，而是把当前冻结的默认演示路径、三类 case 和边界讲准确。

## 2. 先记住一句话介绍

> 这是一个新闻核查工作台。当前我们稳定交付的是默认 `off + mock + fallback=true` 基线上的结构化核查演示，以及 `live / mock / replay / fallback` 边界的清晰展示，而不是“真实检索已对随机新闻稳定较真”。

## 3. 演示前先说明的边界

正式操作前，建议先主动说明这 6 点：

- 当前对外最稳的是 `expired-yogurt` 这条 `complete` mock demo，不是三条 demo 全部稳定通过。
- `morningstar-question` 是受控 `partial` 回归，适合答辩补充，不是默认开场主线。
- `viral-death-ambiguous` 是 `safe` 边界 case，用来讲“不强判”，不是为了给真假结论。
- 前端会优先调用真实 `POST /api/v1/analyze`；如果后端离线或请求失败，会回退到本地 `demo_payload` 或 `frontend_fallback`。
- `complete / partial / safe_mode` 必须结合 provenance 一起讲，不能只看 mode 名称。
- live probe 在 `F8` 中是 `0/4 real_live`，所以今天不能承诺“任意新闻都能真实较真”。

## 4. 推荐的两种演示节奏

### 4.1 5 分钟产品版

| 时间 | 操作 | 口播重点 |
| --- | --- | --- |
| 0:00 - 0:40 | 打开页面，说明输入方式和来源标签 | “今天重点演示 mock/demo 路径，以及系统如何把 live、mock、fallback 分开标识。” |
| 0:40 - 3:10 | 演示 `expired-yogurt` | 先建立信任：结构化结果完整、claim 和时间线可读，但 provenance 仍要按 mock 路径讲。 |
| 3:10 - 4:10 | 展示 provenance 与风险提示 | 解释 `backend_mock / backend_live / demo_payload / frontend_fallback` 的区别。 |
| 4:10 - 5:00 | 讲 fallback 或 `safe_mode` 边界 | 说明系统在证据不足时会保守，不会强行给真假结论。 |

### 4.2 8 到 10 分钟答辩版

| 时间 | 操作 | 口播重点 |
| --- | --- | --- |
| 0:00 - 0:40 | 开场与边界 | 明确今天讲的是结构化核查 + provenance，不是 live 全量较真通过。 |
| 0:40 - 3:20 | `expired-yogurt` | 讲完整结构化输出和可复核结果。 |
| 3:20 - 5:00 | `morningstar-question`（只讲受控回归定位） | 讲 question-first、反驳型 claim、partial 边界。 |
| 5:00 - 6:30 | `viral-death-ambiguous` 或 fallback | 讲证据不足时如何停在 `safe_mode`。 |
| 6:30 - 8:00 | 为什么不是直接给真假概率 | 讲 claim-first、retrieval-first、provenance-first。 |
| 8:00 - 10:00 | 关键实现与测试入口 | 讲 golden cases、Smoke、回归入口和工程取舍。 |

## 5. 对外主线：`expired-yogurt`

### 输入

```text
3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。
```

### 建议操作顺序

1. 先看状态条和来源标签，说明当前是可交付的 mock/demo 路径。
2. 再看事件卡片，讲“一句话总结 + 关键词”。
3. 然后看时间线，点出关键节点。
4. 最后看 claim 表和证据列表，说明哪些说法有支持、哪些仍是边界提示。

### 推荐讲法

> 这条 case 用来演示系统在当前默认基线下怎么把一段新闻拆成结构化结果。它能给出事件摘要、claim、时间线和风险提示，同时页面会明确告诉你这次结果来自哪条路径，避免把 mock 或 fallback 误看成 live 检索通过。

### 不要说过头的地方

- 不要说“这已经证明真实互联网检索稳定通过”。当前默认环境主要还是 mock 路径。
- 不要把时间线节点讲成“完整传播链还原”。当前更接近可展示的关键节点摘要。
- 不要把 provenance 省略掉，只讲 `complete_mode`。

## 6. 受控回归：`morningstar-question`

### 输入

```text
晨星生物裁员40%是真的吗？
```

### 这条怎么定位

- 它是 `partial` 路线的受控回归，不是默认对外主线。
- 它适合回答“question-only 输入怎么做 claim-first 核查”。
- 它适合放在 Q&A 或实现讲解里，不适合拿来当第一条 demo 开场。

### 推荐讲法

> 这条样例主要用来说明系统不是只会吃整段新闻，也能处理“XX 是真的吗”这类问句输入。它会先把问句转成待核查 claim，再基于 retrieval 结果决定哪些说法可以被反驳、哪些仍然要保留边界。

### 不要说过头的地方

- 不要把它讲成今天的公开主线样例。
- 不要把它讲成 `real_live` 通过样本。
- 不要把 `partial_mode` 讲成“传播链已经完整还原”。

## 7. 边界 case：`viral-death-ambiguous`

### 输入

```text
最近有个女网红脑出血死了真的假的？
```

### 这条怎么定位

- 它是 `safe` 边界 case，用来证明系统知道什么时候不能强判。
- 它非常适合回答“为什么不是直接给一个真假概率”。
- 如果后端离线，也可以用前端 fallback 路径讲同样的保守边界。

### 推荐讲法

> 这类输入的问题不在于模型有没有意见，而在于公开证据是否足够支持一个确定结论。我们宁可停在 `safe_mode`，列出多种可能性和当前缺口，也不把模糊传闻包装成确定性判断。

### 不要说过头的地方

- 不要把 `safe_mode` 讲成“系统已经判断它是假的”。
- 不要把多可能性列表讲成最终事实。
- 不要把 fallback 或 demo payload 讲成真实联网结果。

## 8. 当前不应放进默认主线的两个 case

### `chemical-odor`

- `F8` 中已从预期 `partial_mode` 漂移到 `safe_mode`。
- 当前不能继续把它当作稳定 partial demo 使用。
- 如果必须展示，只能先说明这是待复核样本，不是通过样本。

### `morningstar-layoff`

- `F8` 中已从预期 `safe_mode` 漂移到 `complete_mode`。
- 当前存在把本该保守的 case 讲成确定性结论的风险。
- 演示主线里不要使用它。

## 9. 如果被追问，建议怎么答

**Q：你们现在已经能查任意新闻了吗？**

建议回答：

> 还不能这么说。当前正式验收通过的是 mock/demo 路径和边界展示能力；真实检索链路在 `F8` 的 live probe 里还没有通过最终验收。

**Q：现在的 verdict 是真实证据驱动的吗？**

建议回答：

> 不能一概这么说。当前要同时看 mode 和 provenance：默认演示仍主要是 mock 路径，只有出现 `backend_live + retrieval_live` 时，才可以讲成真实后端加真实检索。

**Q：如果后端挂了，为什么页面还可以演示？**

建议回答：

> 当前前端是“真实 analyze 优先、demo payload 和 frontend fallback 保底”。这能保证页面结构和边界讲法稳定，但不等于真实链路已经全部完成。

**Q：为什么不是直接让 LLM 给一个真假概率？**

建议回答：

> 因为题目要求的不只是一个结论，而是两条可解释主流程：传播链还原和内容核查。我们要先拆 claim、再组织 evidence、再标明 provenance，最后才谈可信度；如果证据不足，就宁可停在 `safe_mode`，也不伪造一个看起来很精确的概率。

## 10. 讲稿模板

### 10.1 5 分钟产品讲稿

1. “这不是一个单纯给真假标签的页面，而是一个把新闻拆成结构化核查流程的工作台。”
2. “我们把题目要求拆成两条主线：传播链还原和内容核查。结果页会同时给时间线、claim 结论、证据和风险提示。”
3. “今天我先演示 `expired-yogurt` 这条最稳的 mock demo。它可以稳定展示事件摘要、claim、时间线和 provenance。”
4. “这里最关键的不是 mode 名称，而是 provenance。系统会明确标出这是 `backend_mock`、`backend_live`，还是前端 fallback。”
5. “如果证据不足，系统会停在 `safe_mode`，而不是强行给结论。这也是我们为什么没有直接让 LLM 给一个真假概率。”

### 10.2 10 分钟实现讲稿

1. “输入侧我们走的是 claim-first：文本、URL、问句都会先被归一化，再拆成 claim，而不是整段文本直接出结论。”
2. “检索侧我们走 retrieval-first：传播链和内容核查共用一层 evidence / timeline 候选，避免两个主流程各写一套逻辑。”
3. “输出侧我们强制 provenance-first：每条结果都标明是 live、mock、replay 还是 fallback，避免把保守结果讲成真实较真成功。”
4. “工程上我们没有把所有精力花在追 live，而是先冻结 golden cases、Smoke 和 Demo Script，保证主线可演示、可回归、可答辩。”
5. “可信度分字段已经进 contract，但在未计算完成前允许显式空值，这比伪造精确分更适合当前题目和答辩场景。”

## 11. 一句话结论

截至 2026-03-15，最稳的演示主线是：`expired-yogurt` + 默认 `off/mock` 基线 + provenance 边界 + fallback 说明；`morningstar-question` 和 `viral-death-ambiguous` 作为受控回归或答辩补充，不再沿用“三条稳定 demo 全部通过”或“真实检索已收口”的旧口径。
