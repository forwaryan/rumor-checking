# Data

本目录只保留运行时缓存和少量本地数据落点。

根目录 [evals/README.md](/home/forwaryan/mianshi/rumor-checking/evals/README.md) 仍是正式评测资产入口；这里不再承载独立的方案草稿或演示文档。

当前真实检索缓存会写到 `data/cache/retrieval/`，默认格式为 `data/cache/retrieval/<provider>/<cache_key>.json`。

## 当前缓存约定

- 检索缓存 key：`sha256(v1|provider|compact_query)` 的前 24 位
- 默认 TTL：`RETRIEVAL_CACHE_TTL_SECONDS=43200`（12 小时）
- 正常路径：优先读 fresh cache，miss 后请求真实 provider，再把 `RetrievalBundle` 回写到缓存
- 失败回退：当 `RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR=true` 时，provider 失败可读 stale cache
- 内部 cache-only 诊断入口：`request_context.retrieval_cache_only=true` 可强制只读缓存；如需允许 stale 命中，可同时传 `allow_stale_retrieval_cache=true`
- 跳过缓存：`request_context.bypass_retrieval_cache=true`

## 当前目录边界

- `cache/`
  - URL 抽取结果和检索缓存等运行时缓存

## 约束

- 运行时缓存只放这里，不散落到前后端实现目录
- 如果未来要新增演示资产或离线数据，先在根目录 README 和对应实现里确定真实用途，再补目录说明
