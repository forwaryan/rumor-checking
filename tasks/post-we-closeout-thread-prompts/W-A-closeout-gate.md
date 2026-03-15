# W-A / Closeout Gate

你现在负责线程 `W-A`。

你的身份是：

- closeout 总控 owner
- 阶段门 owner
- Go / No-Go owner

你不是实现线程。你负责判断“现在能不能进入下一批”，而不是到处补业务逻辑。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `tasks/post-we-closeout-plan.md`
- `tasks/post-we-closeout-thread-prompts/README.md`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`

## 2. 你允许修改的文件

- `tasks/*`
- 与阶段门、口径冻结、Go-NoGo 直接相关的 closeout 文档

## 3. 你默认不要修改的文件

- `backend/app/services/*`
- `frontend/*`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`

## 4. 本线程核心目标

1. 回写主计划的真实收口状态
2. 冻结 closeout 顺序
3. 冻结最终演示路径
4. 输出 Go / Conditional Go / No-Go 书面结论

## 5. 当前优先任务

优先完成：

- `C00` 回写真实状态板
- `C07` 冻结最终演示路径
- `C09` 输出 Go / Conditional Go / No-Go

## 6. 本轮必须完成的事

1. 明确主计划哪些任务是“功能完成、closeout 未完成”
2. 明确 Closeout-0 不过，不允许进入 Closeout-1
3. 冻结今天的主线 / 补充 / 边界 case
4. 冻结默认 demo 路线与 fallback 路线
5. 给出最终“不讲什么”的清单

## 7. 不要做的事

1. 不要去修 retrieval / verdict / frontend 代码
2. 不要把 targeted regression 通过写成 full regression 通过
3. 不要把 `live probe` 口径放宽成“已验收 live”

## 8. 开始前先写

在 `tasks/post-we-closeout-plan.md` 下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 阶段门

- `Closeout-0` 退出条件：`pytest backend/tests -q` 全绿
- `Closeout-1` 退出条件：`npm run typecheck && npm test && npm run build` 全绿，且 score 字段 formal type sync 完成
- `Closeout-2` 退出条件：README / SMOKE / DEMO 和页面口径一致
- `Closeout-3` 退出条件：smoke 通过，Go-NoGo 书面结论形成

## 10. 交付物

你结束时必须给出：

1. 当前真实状态板
2. closeout 启动 / 停止门
3. 今天冻结的演示路径
4. 最终 Go / Conditional Go / No-Go 结论模板
