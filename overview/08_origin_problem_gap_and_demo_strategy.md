# 原始题意对照、当前完成度与演示策略

这份文件现在只保留“原题还差什么、演示该怎么讲”这两个用途。

当前实现状态请先看：

- [../docs/status/current-verified-state.md](../docs/status/current-verified-state.md)

整理前的旧版分析已归档到：

- [../docs/archive/conflicts/overview-08_origin_problem_gap_and_demo_strategy.pre-verified-20260314.md](../docs/archive/conflicts/overview-08_origin_problem_gap_and_demo_strategy.pre-verified-20260314.md)

## 当前仍然成立的差距

- `F8` 随机新闻最终验收仍未完成。
- URL 输入只覆盖公开 HTML 页面，不覆盖登录页、强反爬、浏览器渲染页面、PDF 和图片正文。
- verdict 与 timeline 已接入 retrieval 主链，但仍主要依赖启发式规则，不能宣称开放场景稳定完成。
- replay 仍是内部 cache-only 能力加文件草案，没有公开 replay 接口。

## 当前最稳的演示策略

- `complete_mode`
  - 用稳定 demo case 讲“主链已打通、结构化结果可读”。
- `partial_mode`
  - 用冲突或边界 case 讲“系统会保留冲突，不会硬判”。
- `safe_mode`
  - 用证据不足 case 讲“系统会保守收口，不伪造结论”。

推荐直接搭配：

1. [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md)
2. [../SMOKE_CHECKLIST.md](../SMOKE_CHECKLIST.md)
3. [../backend/README.md](../backend/README.md)
4. [../frontend/README.md](../frontend/README.md)

## 不要继续沿用的旧口径

- “URL 正文抽取还没接。”
- “provenance 展示尚未落地。”
- “后端现在依赖 `demo-cases` / `replay` 接口才能演示。”

这些表述都已经和当前代码实现冲突。
