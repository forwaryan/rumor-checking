# Data

本目录用于存放开发期需要消费的数据副本、缓存和演示数据。

根目录 `evals/` 仍保留为原始评测资产入口；当后端或前端需要更贴近运行时的目录布局时，再把稳定资产映射到这里。

当前 mock 检索仍以 `evals/minimal_v1/retrieval_cases.json` 作为稳定输入资产；真实检索缓存已经开始落到 `data/cache/retrieval/`，默认格式为 `data/cache/retrieval/<provider>/<cache_key>.json`。

## 当前缓存约定

- 检索缓存 key：`sha256(v1|provider|compact_query)` 的前 24 位
- 默认 TTL：`RETRIEVAL_CACHE_TTL_SECONDS=43200`（12 小时）
- 正常路径：优先读 fresh cache，miss 后请求真实 provider，再把 `RetrievalBundle` 回写到缓存
- 失败回退：当 `RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR=true` 时，provider 失败可读 stale cache
- replay 预留入口：`request_context.retrieval_cache_only=true` 可强制只读缓存；如需允许 stale 命中，可同时传 `allow_stale_retrieval_cache=true`
- 跳过缓存：`request_context.bypass_retrieval_cache=true`

## 目录边界

- `evals/`
  - 运行时消费的测试样例、副本或软链接说明
- `cache/`
  - URL 抽取结果、检索缓存、重放缓存
- `demos/`
  - 稳定 demo case、replay 输入和演示辅助数据

## 并行协作约束

- 原始评测设计与说明继续放在根目录 `evals/` 与 `requirements/guides/`
- 运行时缓存只放这里，不散落到前后端实现目录

