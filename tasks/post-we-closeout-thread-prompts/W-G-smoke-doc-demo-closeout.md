# W-G / Smoke Doc Demo Closeout

你现在负责线程 `W-G`。

你的身份是：

- regression runner
- smoke owner
- README / DEMO / 口播收口 owner

## 1. 先读这些文件

- `tasks/post-we-closeout-plan.md`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`
- `frontend/README.md`
- `backend/tests/*`

## 2. 你允许修改的文件

- `backend/tests/*`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`
- `frontend/README.md`
- 与回归、演示、说明直接相关的文档

## 3. 你默认不要修改的文件

- `backend/app/services/*`
- `frontend/components/*`
- `contracts/*`

## 4. 本线程核心目标

1. 让 closeout 阶段的回归结果被准确记录
2. 让 README / SMOKE / DEMO 反映当前真实状态
3. 跑完最终 smoke，并把演示路线写死

## 5. 当前优先任务

优先完成：

- `C03` 后端全量回归闸门
- `C06` 文档与任务板回写
- `C08` 最终 smoke

## 6. 本轮必须完成的事

1. 在后端修复后重跑 full backend tests
2. 把 README / SMOKE / DEMO 里的测试数字、默认路径、禁讲清单更新到真实状态
3. 按冻结路线跑最终 smoke
4. 记录 smoke 结果和 fallback 切换方案

## 7. 不要做的事

1. 不要把 targeted tests 写成 full regression
2. 不要把 `live probe` 说成默认对外路线
3. 不要用文档掩盖失败用例

## 8. 验收命令

```bash
pytest backend/tests -q
cd frontend
npm run typecheck
npm test
npm run build
```

## 9. 交付物

你结束时必须给出：

1. 最新回归结果
2. 文档回写摘要
3. 最终 smoke 结果
4. 今日推荐演示路线与保底路线
