# Tasks Index

本目录用于存放可独立并行推进的任务文件。

每个任务文件都对应一个可以单独分配给窗口或集群的工作包，而不是单个零散动作。

## 使用方式

1. 先看本目录，决定当前要开几个窗口。
2. 给每个窗口分配一个独立的任务文件。
3. 开始执行前，先在目标 `cluster-*.md` 的对应子任务下写明“本轮执行任务”和“执行步骤”。
4. 每个窗口只以自己负责的任务文件为主，不主动跨界修改其他工作包的核心文件。
5. 某个子任务完成后，必须把该任务文件中的状态、完成方式、验证结果和剩余问题一起回写，而不是只改一个状态词。

## 当前任务文件

- `cluster-a-control-tower.md`
- `cluster-b-contract-forge.md`
- `cluster-c-api-foundation.md`
- `cluster-d-retrieval-lab.md`
- `cluster-e-experience-shell.md`
- `cluster-f-quality-gate.md`
- `cluster-g-demo-ops.md`

## 当前最高优先级

当前如果目标是尽快把 V1 推到“可执行、可联调、不是只靠 demo / JSON 回放”的状态，建议优先级如下：

1. `Cluster-C / API Foundation`
   - 重点仍是 `C10` 与 `C11`，把 URL 正文抽取和 reasoning-grounded analyze 主链补起来。
2. `Cluster-F / Quality Gate`
   - 当前 `F7` 已完成，下一步应集中补 `F2 / F3 / F4 / F6 / F8`，把“有测试”推进到“可按 eval 资产验收”。
3. `Cluster-E / Experience Shell`
   - 页面壳已完成，但 `E9` 还需要把真实 analyze、demo payload、fallback provenance 讲清楚。
4. `Cluster-G / Demo Ops`
   - `G5 / G6` 已完成，下一步是 `G2 / G3 / G4`，把 replay、运行方式和边界说明继续收口。
5. `Cluster-D / Retrieval Lab`
   - `D5 ~ D7` 已完成最小可用版；当前更适合做真实 smoke 支撑和后续质量精修，而不是继续作为首要阻塞项。

## 窗口分配建议

### 窗口 1：`T-main`

对应文件：`cluster-a-control-tower.md`

负责什么：

- 负责全局节奏、优先级、冲突处理、里程碑验收
- 负责判断什么时候进入下一波开发
- 负责最终 go / no-go 决策

建议谁拿：

- 最了解全局方案的人
- 能做最终取舍和拍板的人
- 不适合交给纯实现窗口

### 窗口 2：`T-contract`

对应文件：`cluster-b-contract-forge.md`

负责什么：

- 负责共享 schema 和字段定义
- 负责 mock payload 和接口字段稳定
- 负责防止前后端字段漂移

建议谁拿：

- 最细心、最适合做协议定义的人
- 对接口、字段、数据结构敏感的人
- 不建议交给页面实现窗口兼任

### 窗口 3：`T-impl-api-foundation`

对应文件：`cluster-c-api-foundation.md`

负责什么：

- 负责后端主链路
- 负责输入、claim、verdict、report、主接口
- 负责真实 Kimi 和 URL fallback 的接入

建议谁拿：

- 最强的后端实现窗口
- 最适合做 API、服务编排、LLM pipeline 的人
- 这是第一波必须尽早启动的窗口

### 窗口 4：`T-impl-api-retrieval`

对应文件：`cluster-d-retrieval-lab.md`

负责什么：

- 负责检索、标准化、去重归并、时间线、缓存
- 负责传播链这条主线的实现

建议谁拿：

- 擅长检索、数据清洗、时间线逻辑的人
- 适合独立做后端子系统的人
- 不建议和主链路 API 混成一个窗口，除非窗口数量不够

### 窗口 5：`T-impl-web`

对应文件：`cluster-e-experience-shell.md`

负责什么：

- 负责单页 Demo 的输入区、状态条、时间线、claim 表、证据展示
- 负责 `complete / partial / safe_mode` 的页面表达

建议谁拿：

- 最擅长前端、组件、交互的人
- 能先用 mock payload 开发页面的人
- 不需要等待真实后端完全结束再开工

### 窗口 6：`T-test`

对应文件：`cluster-f-quality-gate.md`

负责什么：

- 负责最小测试集接入
- 负责 case 回归和阶段验收
- 负责演示前 smoke checklist

建议谁拿：

- 最适合做测试、回归、验收的人
- 细心、愿意记录问题和通过线的人
- 不建议交给主实现窗口兼任太多测试任务

### 窗口 7：`T-doc-demo`

对应文件：`cluster-g-demo-ops.md`

负责什么：

- 负责 demo case、回放能力、README、演示口径
- 负责把“能跑”变成“能演示”

建议谁拿：

- 最适合做 README、说明文档、演示脚本的人
- 擅长收口和整理的人
- 可以在后期承担更多交付包装工作

## 如果窗口不够怎么合并

### 3 个窗口

- `窗口 1`
  - 拿 `cluster-a-control-tower.md` + `cluster-b-contract-forge.md`
- `窗口 2`
  - 拿 `cluster-c-api-foundation.md` + `cluster-d-retrieval-lab.md`
- `窗口 3`
  - 拿 `cluster-e-experience-shell.md` + `cluster-f-quality-gate.md` + `cluster-g-demo-ops.md`

### 4 个窗口

- `窗口 1`
  - 拿 `cluster-a-control-tower.md` + `cluster-b-contract-forge.md`
- `窗口 2`
  - 拿 `cluster-c-api-foundation.md`
- `窗口 3`
  - 拿 `cluster-d-retrieval-lab.md` + `cluster-f-quality-gate.md`
- `窗口 4`
  - 拿 `cluster-e-experience-shell.md` + `cluster-g-demo-ops.md`

### 6 到 7 个窗口

- 每个窗口各拿一个 cluster 文件，最稳

## 任务结构说明

每个任务文件都包含：

- 这个子 task 是干什么的
- 为什么要有这个子 task
- 为什么这个子 task 可以并行
- 详细子任务
- 每个子任务下的“子子任务清单”
- 每轮执行时补充的“本轮执行任务 / 执行步骤 / 完成记录”

## 状态约定

- `未完成`
- `进行中`
- `已完成`
- `阻塞`

与总看板中的英文状态一一对应：

- `未完成` = `todo`
- `进行中` = `doing`
- `阻塞` = `blocked`
- `已完成` = `done`

任务文件初版曾以 `未完成` 初始化；当前应始终按真实进度持续回写，不要再把 task 状态当成静态模板。

## 执行记录要求

从现在开始，所有实际执行的任务都必须先写进对应 task 文件，再开始改代码或文档。

最低要求如下：

- 开始前：
  - 在对应子任务下写明本轮要做什么。
  - 把本轮工作拆成 `3` 到 `7` 个可执行步骤。
  - 标明本轮主要会改哪些目录或文件范围。
- 完成后：
  - 更新子任务状态。
  - 补充“怎么完成的”，至少说明改了哪些文件、核心做法是什么。
  - 补充验证结果，说明跑了什么测试、接口或联调。
  - 补充剩余问题和下一步交接建议。
- 如果中途阻塞：
  - 把状态改为 `阻塞` 或保留 `进行中` 并写清阻塞原因。
  - 写明当前停在第几步、需要哪个 cluster 或哪个前置条件继续推进。

推荐在子任务下使用以下固定格式：

```text
本轮执行任务：
- ...

执行步骤：
- ...
- ...

完成记录：
- 改动文件：...
- 完成方式：...
- 验证结果：...
- 剩余问题：...
```

不要只在聊天消息里描述任务执行情况；task 文件本身必须能独立说明“要做什么、做了什么、怎么做完的”。

## 配套执行手册

除了各个 `cluster-*.md` 状态文件外，当前还提供：

- `parallel-execution-playbook.md`
  - 用于说明“每个 task 文件一个全局 prompt”的执行模型，以及所有窗口共用的执行规则。

推荐用法：

1. 先在对应 `cluster-*.md` 中确认状态、边界和未完成项。
2. 直接复制该文件里的 `窗口执行 Prompt（全局）` 给执行窗口。
3. 执行窗口先在对应子任务下写入“本轮执行任务 / 执行步骤”。
4. 执行窗口按该文件中的未完成子任务开始工作。
5. 任务完成后，在同一处补“完成记录”与验证结论。
6. 只有在 cluster 内又要继续拆窗口时，才额外写更细 prompt。
