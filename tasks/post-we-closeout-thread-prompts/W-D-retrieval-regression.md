# W-D / Retrieval Regression

你现在负责线程 `W-D`。

你的身份是：

- retrieval closeout owner
- canonicalization / diagnostics owner
- raw retrieval hit 保守展示 owner

## 1. 先读这些文件

- `tasks/post-we-closeout-plan.md`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/services/retrieval_models.py`
- `backend/tests/test_kimi_only_pipeline.py`
- `backend/tests/test_retrieval.py`

## 2. 你允许修改的文件

- `backend/app/services/retrieval_service.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/services/retrieval_models.py`
- retrieval 相关测试

## 3. 你默认不要修改的文件

- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `frontend/*`
- `README.md`

## 4. 本线程核心目标

1. 修 retrieval diagnostics 与 canonical count 口径漂移
2. 保住弱命中场景下 raw hits 可见、但结论不被误抬高
3. 把 Closeout-0 的 retrieval 阻塞清掉

## 5. 当前优先任务

优先完成：

- `C01` kimi-only canonical count 回归
- `C02` safe mode 保守收束回归中 retrieval 相关部分

## 6. 当前已知失败

1. `backend/tests/test_kimi_only_pipeline.py::test_analyze_request_uses_kimi_only_path`
   - 期望：`canonical_result_count == 2`
   - 实际：`1`
2. `backend/tests/test_retrieval.py::test_safe_mode_keeps_raw_retrieval_hits_visible`
   - 期望：`safe_mode`
   - 实际：`partial_mode`

## 7. 本轮必须完成的事

1. 确认 `canonical_result_count` 的真实口径，并让 diagnostics 与合并逻辑一致
2. 确认 follow-up query / canonical merge 不会把应该可见的命中错误折叠
3. 如果 `safe_mode` 回归根因在 retrieval relevance / hit ranking / bundle combine，就在本线程修掉
4. 如果根因已经进入 verdict / mode 选择层，明确交接给 `W-E`

## 8. 不要做的事

1. 不要改 score 公式
2. 不要改前端
3. 不要顺手重构 retrieval 全链路

## 9. 验收命令

```bash
pytest backend/tests/test_kimi_only_pipeline.py -q
pytest backend/tests/test_retrieval.py::test_safe_mode_keeps_raw_retrieval_hits_visible -q
pytest backend/tests -q
```

## 10. 交付物

你结束时必须给出：

1. retrieval 根因判断
2. 修复点摘要
3. targeted regression 结果
4. 是否还需要 `W-E` 继续接手
