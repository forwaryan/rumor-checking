# W-F / Frontend

你现在负责线程 `W-F`。

你的职责是：

- 把双主流程和整体可信度表达成高分结果页

你不是后端逻辑线程。你的任务不是发明字段，而是把已经冻结的字段表达清楚。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `frontend/components/analyze-page.tsx`
- `frontend/components/status-banner.tsx`
- `frontend/lib/api-client.ts`
- `frontend/lib/report-utils.ts`
- `frontend/README.md`

## 2. 你允许修改的文件

- `frontend/components/*`
- `frontend/lib/*`
- `frontend/app/*`
- `frontend/README.md`

## 3. 你默认不要修改的文件

- `contracts/*`
- `backend/*`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`

## 4. 本线程核心目标

1. 首屏一句话说清输入和输出
2. 结果页一眼讲清双主流程
3. 整体可信度、传播链、内容核查都能快速扫读
4. 风险和局限明确展示

## 5. 当前优先任务

优先完成：

- `T08` 前端双主流程结果页

## 6. 本轮必须完成的事

1. 首屏明确“输入什么、输出什么”
2. 增加整体可信度卡片
3. 增加 `score_breakdown` 展示
4. 增加“传播链完成度”和“内容核查完成度”拆分展示
5. 增加“事实 / 观点 / 可能有误”摘要区
6. 增加“真假混杂”场景的 claim 贡献解释
7. 增加固定风险提示区和当前局限区

## 7. 不要做的事

1. 不要在页面里硬编码业务判断
2. 不要新增后端未冻结的字段
3. 不要改 backend schema

## 8. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 完成标准

你这轮完成的标准是：

1. 用户 10 秒内能理解产品干什么
2. 评委 30 秒内能理解结果页重点
3. safe / partial / complete 差异足够清楚
4. 页面不夸大 live 能力

## 10. 交付物

你结束时必须明确给出：

1. 页面结构说明
2. 依赖的 report 字段清单
3. 当前 UI 还依赖哪些后端能力
4. 推荐演示时怎么讲页面
