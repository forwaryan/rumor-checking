# 09 Stage Progress And Task Audit

更新时间：2026-03-14 22:11（Asia/Shanghai）

## 一句话结论

当前最准确的阶段判断是：

- `C10` 已完成第一阶段。
- `C11` 已完成第一阶段。
- 前端 `E9` 的当前 provenance 展示已经落地。
- `F2 / F3 / F4 / F5 / F6 / F7` 已完成。
- `F8` 已形成正式验收记录，但结论是“真实 live 路径当前未通过最终验收”。
- 当前主问题已经从“功能有没有”转到“真实 live 路径稳不稳定、demo 模式漂不漂、文档口径是否同步”。

## 当前已完成的关键项

| 主题 | 当前状态 | 依据 |
| --- | --- | --- |
| `C10` URL 抽取 | 已完成第一阶段 | `backend/app/services/input_normalizer.py`、`url_content_extractor.py`、`backend/tests/test_api.py` |
| `C11` 主链去占位 + provenance | 已完成第一阶段 | `analyze_pipeline.py`、`retrieval_service.py`、`report_builder.py` |
| `E9` provenance 展示 | 已完成当前主展示 | `frontend/components/status-banner.tsx`、`frontend/lib/report-utils.ts` |
| `F2` 输入回归 | 已完成 | `tasks/cluster-f-quality-gate.md` 记录为 `6/6` 通过，且当前 `backend/tests/test_api.py` 通过 |
| `F3` claim 分类回归 | 已完成 | `tasks/cluster-f-quality-gate.md`、`tasks/completed-subtask-doc-index.md` |
| `F4` verdict 回归 | 已完成 | `tasks/cluster-f-quality-gate.md` 记录为 `8/8` 通过 |
| `F5` retrieval / timeline 回归 | 已完成 | `backend/tests/test_retrieval.py` |
| `F6` report mode 回归 | 已完成 | `tasks/cluster-f-quality-gate.md` 记录为 `4/4` 通过 |
| `F7` smoke checklist | 已完成 | `SMOKE_CHECKLIST.md` |
| `F8` 随机 case 验收记录 | 已完成 | `overview/13_f8-random-acceptance.md` |

## 当前没有完成的不是“功能”，而是这些问题

| 主题 | 当前状态 | 具体问题 |
| --- | --- | --- |
| 真实 live retrieval 稳定性 | 未完成 | `F8` 记录显示 `backend_live + retrieval_live` 当前没有通过样本。 |
| 稳定 demo 模式漂移收口 | 未完成 | `chemical-odor`、`morningstar-layoff` 仍需复核 mode 漂移。 |
| `G2` replay 最终定稿 | 进行中 | 当前只有文件草案和内部 cache-only 能力。 |
| `G3 / G4` 最终口径同步 | 进行中 | 需要基于 `F8` 结论统一 README、演示稿和边界说明。 |
| `C9` provider 在线稳定性 | 进行中 | 在线帮助性与超时/限流问题仍需继续收口。 |

## 当前验证面

| 验证项 | 结果 | 结论 |
| --- | --- | --- |
| `pytest backend/tests/test_api.py -q` | `16 passed` | API 主链当前稳定。 |
| `pytest backend/tests/test_retrieval.py -q` | `15 passed` | retrieval/timeline 当前稳定。 |
| `pytest backend/tests/test_kimi_provider.py backend/tests/test_kimi_provider_quality.py -q` | `6 passed` | provider 质量基线当前可跑。 |
| `overview/13_f8-random-acceptance.md` | 已落正式记录 | 当前真实 live 路径未通过最终验收。 |

## 下一波最值得开的窗口

| 优先级 | 窗口 | 为什么现在最值当 |
| --- | --- | --- |
| 1 | `W-A / Cluster-D` | 先修 live retrieval 的 `ConnectError / 429 / JSONDecodeError`，否则真实路径永远没有通过样本。 |
| 2 | `W-B / Cluster-C` | 复核稳定 demo 的模式漂移与 provider / retrieval 质量问题。 |
| 3 | `W-C / Cluster-G` | 把 `F8` 结论同步进 README、演示稿和边界说明。 |
| 4 | `W-D / Cluster-G` | 在真实路径稳定后，再决定 `G2` replay 的最终字段和使用方式。 |

## 当前结论

当前不能再把项目描述成“还有一堆基础功能没做”，也不能把它描述成“真实开放场景已经稳定通过”。

更准确的说法是：基础功能和回归层已经基本齐了，但真实 live 路径仍未通过最终验收，后续重点应放在 live retrieval 稳定性、模式漂移收口和文档口径同步。
