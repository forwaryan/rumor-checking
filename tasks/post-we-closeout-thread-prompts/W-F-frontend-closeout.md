# W-F / Frontend Closeout

你现在负责线程 `W-F`。

你的身份是：

- 前端 formal type sync owner
- 真实输出 UI closeout owner

## 1. 先读这些文件

- `tasks/post-we-closeout-plan.md`
- `frontend/types/report.ts`
- `frontend/lib/api-client.ts`
- `frontend/lib/report-high-score.ts`
- `frontend/components/report-overview-panel.tsx`
- `frontend/README.md`

## 2. 你允许修改的文件

- `frontend/types/*`
- `frontend/lib/*`
- `frontend/components/*`
- `frontend/README.md`

## 3. 你默认不要修改的文件

- `backend/app/services/*`
- `contracts/*`
- `README.md`
- `SMOKE_CHECKLIST.md`

## 4. 本线程核心目标

1. 把冻结 contract 正式映射到前端主类型
2. 保证 complete / partial / safe 三类页面都消费真实 score 字段
3. 保持缺字段时的保守降级

## 5. 当前优先任务

优先完成：

- `C04` 前端 formal type sync
- `C05` 前端真实输出 UI 核对

## 6. 当前重点缺口

当前前端运行没问题，但 `frontend/types/report.ts` 的主 `Report` 类型仍未正式声明：

- `overall_credibility_score`
- `overall_credibility_label`
- `score_breakdown`
- `claim_contributions`
- `timeline_confidence`
- `independent_source_count`

## 7. 本轮必须完成的事

1. 正式把 score 字段接进主类型
2. 核对 `api-client`、`report-high-score`、`report-overview-panel` 的字段消费逻辑
3. 保证空值或缺字段时页面不伪造分数
4. 更新 `frontend/README.md` 里的字段依赖说明

## 8. 不要做的事

1. 不要重做页面结构
2. 不要改后端 contract
3. 不要改文档主口径

## 9. 验收命令

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

## 10. 交付物

你结束时必须给出：

1. formal type sync 摘要
2. 真实输出 UI 核对结果
3. 保守降级路径是否仍成立
