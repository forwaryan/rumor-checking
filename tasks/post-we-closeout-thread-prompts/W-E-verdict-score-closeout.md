# W-E / Verdict Score Closeout

你现在负责线程 `W-E`。

你的身份是：

- mode / verdict / score closeout owner
- 保守边界 owner

## 1. 先读这些文件

- `tasks/post-we-closeout-plan.md`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `backend/tests/test_retrieval.py`
- `backend/tests/test_verdict_engine.py`
- `backend/tests/test_high_score_golden_cases.py`

## 2. 你允许修改的文件

- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- verdict / score 相关测试

## 3. 你默认不要修改的文件

- `backend/app/services/retrieval_service.py`
- `backend/app/services/analyze_pipeline.py`
- `frontend/*`
- `README.md`

## 4. 本线程核心目标

1. 锁死“证据不足时必须保守”的边界
2. 保证 `safe_mode / partial_mode / complete_mode` 不会被弱证据误抬高
3. 在不改 contract 的前提下完成 closeout

## 5. 当前优先任务

优先完成：

- `C02` safe mode 保守收束回归中 verdict / mode 相关部分
- `C03` 后端全量回归闸门 support

## 6. 本轮必须完成的事

1. 判断 `test_safe_mode_keeps_raw_retrieval_hits_visible` 的根因是不是 verdict / mode 选择
2. 如果是，就修 `verdict_engine.py` 或 `report_builder.py`
3. 保证 raw hits 可见不等于形成 partial verdict
4. 保证 score 字段在 `safe_mode` 下继续保守

## 7. 不要做的事

1. 不要去改 retrieval combine 口径
2. 不要重做 score contract
3. 不要顺手改前端展示

## 8. 验收命令

```bash
pytest backend/tests/test_retrieval.py::test_safe_mode_keeps_raw_retrieval_hits_visible -q
pytest backend/tests/test_verdict_engine.py -q
pytest backend/tests/test_high_score_golden_cases.py -q
pytest backend/tests -q
```

## 9. 交付物

你结束时必须给出：

1. 是否是 verdict / mode 根因
2. 保守边界修复摘要
3. 回归结果
4. 是否还存在 score / mode 漂移风险
