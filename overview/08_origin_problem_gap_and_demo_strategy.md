# 原始题意对照、当前完成度与演示策略

这份文件只回答两个问题：

1. 现在离原题还差什么。
2. 现阶段最稳的演示该怎么讲。

## 当前真正还差什么

- `F8` 已形成正式验收记录，但真实 `backend_live + retrieval_live` 路径当前仍未通过最终验收。
- URL 输入已支持公开 HTML 页面抽取，但不覆盖登录页、强反爬、浏览器渲染页面、PDF 和图片正文。
- verdict 与 timeline 已接入 retrieval 主链，但仍主要依赖启发式规则，不能宣称开放场景稳定完成。
- replay 仍是内部 cache-only 能力加文件草案，没有公开 replay 接口。
- 两条稳定 demo 仍存在模式漂移风险，口播需要跟随最新验收记录同步。

## 当前最稳的演示策略

- `complete_mode`
  - 用稳定 case 讲“主链能输出结构化结果”。
  - 但要讲清这不等于真实 live retrieval 已稳定通过。
- `partial_mode`
  - 用冲突或边界 case 讲“系统会保留冲突，不会硬判”。
- `safe_mode`
  - 用证据不足 case 讲“系统会保守收口，不伪造结论”。

## 推荐搭配阅读

1. [../docs/status/current-verified-state.md](../docs/status/current-verified-state.md)
2. [../overview/13_f8-random-acceptance.md](../overview/13_f8-random-acceptance.md)
3. [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md)
4. [../SMOKE_CHECKLIST.md](../SMOKE_CHECKLIST.md)
5. [../backend/README.md](../backend/README.md)
6. [../frontend/README.md](../frontend/README.md)

## 当前不应再继续使用的旧口径

- “URL 正文抽取还没接。”
- “provenance 展示尚未落地。”
- “后端现在依赖 `demo-cases` / `replay` 接口才能演示。”

这些表述都已经和当前代码实现冲突。
