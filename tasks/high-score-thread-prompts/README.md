# High-Score Thread Prompts

更新时间：2026-03-15（Asia/Shanghai）

本目录把 [high-score-final-execution-plan.md](../high-score-final-execution-plan.md) 拆成 `W-A ~ W-G` 七个独立启动 prompt 文件。

使用方式：

1. 先读 [high-score-final-execution-plan.md](../high-score-final-execution-plan.md)
2. 再按当前批次，选择对应线程 prompt
3. 把整个 prompt 文件内容直接发给对应 Codex 线程
4. 线程开始前，必须先确认自己允许修改的文件域
5. 线程完成后，必须回写“本轮执行任务 / 执行步骤 / 完成记录 / 交接建议”

## 文件列表

- `W-A-main-contract.md`
- `W-B-runtime-baseline.md`
- `W-C-input-claims.md`
- `W-D-retrieval-timeline.md`
- `W-E-verdict-score.md`
- `W-F-frontend.md`
- `W-G-qa-doc-demo.md`

## 推荐启动顺序

### Wave-0

- `W-A-main-contract.md`
- `W-B-runtime-baseline.md`
- `W-G-qa-doc-demo.md`

### Wave-1

- `W-C-input-claims.md`
- `W-D-retrieval-timeline.md`
- `W-F-frontend.md`
- `W-G-qa-doc-demo.md`

### Wave-2

- `W-E-verdict-score.md`
- `W-D-retrieval-timeline.md`
- `W-G-qa-doc-demo.md`

### Wave-3

- `W-F-frontend.md`
- `W-G-qa-doc-demo.md`
- `W-A-main-contract.md`

### Wave-4

- `W-A-main-contract.md`
- `W-G-qa-doc-demo.md`

## 高冲突文件 owner

| 文件 | owner |
| --- | --- |
| `contracts/report.schema.json` | `W-A` |
| `backend/app/models/schemas.py` | `W-A` |
| `backend/app/services/report_builder.py` | `W-E` |
| `backend/app/services/verdict_engine.py` | `W-E` |
| `backend/app/services/timeline_builder.py` | `W-D` |
| `frontend/components/analyze-page.tsx` | `W-F` |
| `README.md` | `W-G` |

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
