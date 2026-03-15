# Post Closeout Thread Prompts

更新时间：2026-03-16（Asia/Shanghai）

本目录把 [tasks/post-we-closeout-plan.md](../post-we-closeout-plan.md) 拆成 closeout 阶段可直接启动的线程 prompt。

## 使用方式

1. 先读 [tasks/post-we-closeout-plan.md](../post-we-closeout-plan.md)
2. 再按当前批次选择对应线程 prompt
3. 把整个 prompt 文件直接发给对应 Codex 线程
4. 线程开始前先确认自己允许修改的文件域
5. 线程结束后必须回写“本轮执行任务 / 执行步骤 / 完成记录 / 交接建议”

## 文件列表

- `W-A-closeout-gate.md`
- `W-B-runtime-smoke.md`
- `W-D-retrieval-regression.md`
- `W-E-verdict-score-closeout.md`
- `W-F-frontend-closeout.md`
- `W-G-smoke-doc-demo-closeout.md`

## 推荐启动顺序

### Closeout-0

- `W-A-closeout-gate.md`
- `W-D-retrieval-regression.md`
- `W-E-verdict-score-closeout.md`
- `W-G-smoke-doc-demo-closeout.md`

### Closeout-1

- `W-F-frontend-closeout.md`
- `W-A-closeout-gate.md`

### Closeout-2

- `W-G-smoke-doc-demo-closeout.md`
- `W-A-closeout-gate.md`

### Closeout-3

- `W-G-smoke-doc-demo-closeout.md`
- `W-B-runtime-smoke.md`
- `W-A-closeout-gate.md`

## 当前高冲突文件 owner

| 文件 | owner |
| --- | --- |
| `backend/app/services/retrieval_service.py` | `W-D` |
| `backend/app/services/analyze_pipeline.py` | `W-D` |
| `backend/app/services/verdict_engine.py` | `W-E` |
| `backend/app/services/report_builder.py` | `W-E` |
| `frontend/types/report.ts` | `W-F` |
| `README.md` | `W-G` |
| `SMOKE_CHECKLIST.md` | `W-G` |
| `DEMO_SCRIPT.md` | `W-G` |
| `tasks/post-we-closeout-plan.md` | `W-A` |

## 当前已知阻塞

1. `pytest backend/tests -q` 当前 `67 passed, 2 failed`
2. 失败用例：
   - `backend/tests/test_kimi_only_pipeline.py::test_analyze_request_uses_kimi_only_path`
   - `backend/tests/test_retrieval.py::test_safe_mode_keeps_raw_retrieval_hits_visible`
3. 前端功能验证已过，但 `frontend/types/report.ts` 还没把 score 字段正式镜像进主 `Report` 类型

## 统一回写模板

```text
本轮执行任务：
- 

执行步骤：
- 
- 
- 

计划修改文件：
- 

完成记录：
- 改动文件：
- 完成方式：
- 验证结果：
- 交接对象：
- 剩余问题：
```
