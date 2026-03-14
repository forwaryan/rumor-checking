# Origin Problem Goal Matrix

这份矩阵整理为“当前仍有决策价值的高层状态”，不再继续承载已经被代码推翻的旧阶段口径。

代码核验入口：

- [../docs/status/current-verified-state.md](../docs/status/current-verified-state.md)

整理前的冲突版本已归档：

- [../docs/archive/conflicts/tasks-origin-problem-goal-matrix.pre-verified-20260314.md](../docs/archive/conflicts/tasks-origin-problem-goal-matrix.pre-verified-20260314.md)

## 当前高层矩阵

| 主题 | 当前状态 | 代码或文档依据 | 说明 |
| --- | --- | --- | --- |
| `C10` URL 新闻输入 | 已完成第一阶段 | `backend/app/services/input_normalizer.py`、`backend/app/services/url_content_extractor.py`、`backend/tests/test_api.py` | 已支持公开 HTML 抽取和清晰 fallback。 |
| `C11` reasoning-grounded analyze | 已完成第一阶段（基于代码推断） | `backend/app/services/analyze_pipeline.py`、`retrieval_service.py`、`verdict_engine.py`、`timeline_builder.py`、`report_builder.py` | retrieval 与 provenance 已接入主链，但 verdict/timeline 仍偏启发式。 |
| `E9` provenance 展示 | 已完成当前主展示 | `frontend/components/status-banner.tsx`、`frontend/lib/report-utils.ts` | 页面已区分 live/mock/replay/demo/fallback。 |
| `G2` replay 体系 | 进行中 | `backend/app/services/retrieval_cache.py`、`data/demos/README.md` | 当前有内部 cache-only 能力和文件草案，但没有公开 replay 接口。 |
| `F8` 随机 case 最终验收 | 未完成 | `docs/status/current-verified-state.md` | 仍缺最终通过记录。 |
| `G3 / G4` 文档最终收口 | 进行中 | `README.md`、`overview/`、`docs/README.md` | 当前已完成结构整理，最终口径仍要跟随验收记录。 |

## 使用方式

- 判断“当前代码已经做到哪里”时，先看这份矩阵和 `docs/status/current-verified-state.md`。
- 需要具体执行分工时，再看 [README.md](README.md) 和各 `cluster-*.md`。
