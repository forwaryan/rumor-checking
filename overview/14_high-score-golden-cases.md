# 高分路线 Golden Cases 与回归入口

更新时间：2026-03-15（Asia/Shanghai）

## 1. 这份文档解决什么问题

这份文档是 `W-G` 线程的样例、回归、smoke 与口播冻结表。

目标只有 3 个：

- 把“对外主线能讲什么”和“内部回归在看什么”拆开。
- 把 `complete / partial / safe` 三类 case 固定成一套统一说法。
- 给 README、Smoke、Demo Script 和测试入口一份共同引用的底表。

## 2. Golden Cases 总表

| 分组 | case_id | 场景 | 预期结果 | 当前用途 | 上台怎么讲 | 回归入口 |
| --- | --- | --- | --- | --- | --- | --- |
| 主 demo | `GC01 / expired-yogurt` | 海州新鲜屋过期酸奶抽检通报 | `complete_mode`；结构化输出完整；当前常见 provenance 是 `backend_mock + retrieval_mock` | 对外主线 | 可以讲“完整结构化核查演示”；不能讲成真实检索已通过最终验收 | `pytest backend/tests/test_high_score_golden_cases.py::test_complete_demo_case_remains_stage_safe -q` |
| 主 demo | `GC02 / morningstar-question` | “晨星生物裁员 40% 是真的吗”问句核查 | 受控回归下目标是 `partial_mode`；应体现 question-first 与反驳型 claim | 受控回归 / Q&A 补充 | 只能讲“受控 mock 回归样例”；不进入默认对外主线 | `pytest backend/tests/test_high_score_golden_cases.py::test_partial_demo_candidate_stays_question_first -q` |
| 主 demo | `GC03 / viral-death-ambiguous` | “最近有个女网红脑出血死了真的假的”这类证据不足问句 | `safe_mode`；列出多种可能性；不给强结论 | 边界演示 / fallback 话术 | 用来讲“不强判”和“为什么不能直接给概率”；不能讲成真假已判定 | `pytest backend/tests/test_high_score_golden_cases.py::test_safe_demo_candidate_refuses_to_overclaim -q` |
| 回归集 | `RG01 / claim-split-binhai-metro` | 复杂新闻拆 claim、拆 query、拆观点延伸 | 原子 claim 可拆开，且有 query hints | 输入理解回归 | 讲 claim-first，不讲“整段新闻一句话糊过去” | `pytest backend/tests/test_claim_extractor.py::test_claim_extractor_refines_provider_claims_into_atomic_claims_and_query_hints -q` |
| 回归集 | `RG02 / mixed-truth-viral-death` | 同一条新闻里既有真实片段也有错误扩展 | `content_check` 同时出现 `likely_true` 与 `likely_false` | 真假混杂回归 | 讲“半真半假”而不是二元真伪 | `pytest backend/tests/test_api.py::test_provider_mixed_claims_surface_true_false_split_and_answer_suggestions -q` |
| 回归集 | `RG03 / propagation-r01` | 检索结果里识别 origin / turn / why_selected | 时间线节点可解释，且能挑出关键源头与转折 | 传播链完整度回归 | 讲“关键传播节点”，不讲“已经拿到全网完整传播链” | `pytest backend/tests/test_retrieval.py::test_timeline_builder_uses_retrieval_candidates[R01] -q` |
| 回归集 | `RG04 / score-guardrail` | score 字段已进 contract，但实现可能尚未完成 | 字段要么完整计算，要么显式空值，不能伪造精确分 | score 标定守门 | 讲“分数能力在收口中”；不能拿 `null` 冒充算法结论 | `pytest backend/tests/test_high_score_golden_cases.py::test_score_fields_are_either_computed_or_explicitly_empty -q` |

## 3. 当前推荐讲法

### 可以放进默认主线的

- `GC01 / expired-yogurt`
- provenance 边界说明
- 后端离线时的 `demo_payload / frontend_fallback`

### 只适合受控回归或答辩补充的

- `GC02 / morningstar-question`
- `GC03 / viral-death-ambiguous`

原因不是它们没有价值，而是今天更重要的是稳定和诚实边界。它们适合拿来回答“你们如何处理证据不足/真假混杂/问句输入”，不适合作为默认开场主线。

## 4. 回归与 Smoke 入口

### 快速回归

```bash
pytest backend/tests/test_high_score_golden_cases.py -q
```

### 高分路线最小回归包

```bash
pytest \
  backend/tests/test_high_score_golden_cases.py \
  backend/tests/test_claim_extractor.py::test_claim_extractor_refines_provider_claims_into_atomic_claims_and_query_hints \
  backend/tests/test_api.py::test_provider_mixed_claims_surface_true_false_split_and_answer_suggestions \
  backend/tests/test_retrieval.py::test_timeline_builder_uses_retrieval_candidates[R01] \
  -q
```

### 前端 e2e 替代验收流程

在专门的前端 e2e 用例落地前，统一使用下面这条人工替代流程：

1. 后端在线，跑 `expired-yogurt`，确认结构化结果、来源标签和风险提示都正常。
2. 如果要讲边界，再用问句输入或后端离线路径跑一次 `safe_mode`，确认页面没有伪造完整结论。
3. 演示前再过一遍 `SMOKE_CHECKLIST.md`，确保主控和口播人对 `live / mock / replay / fallback` 的边界说法一致。

## 5. 使用约束

- 不要把 `受控回归` 讲成 `公开主线`。
- 不要把 `mock / replay / fallback` 讲成 `live`。
- 不要把 `score` 的 contract 字段存在，讲成“可信度算法已经全部收口”。
- 如果今天只能稳讲一条，就讲 `GC01 / expired-yogurt` 和 provenance 边界。
