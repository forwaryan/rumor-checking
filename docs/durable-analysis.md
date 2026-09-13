# 可恢复的核查任务

网页提交问题后创建独立的分析任务，并将地址替换为 `?run=<run_id>`。刷新页面或暂时断网后会连接同一任务，不会再次创建分析。已完成的任务直接取回报告。页面仅在内存保留原始输入，地址不再携带问题正文；旧的 `?q=` 链接仍可启动一次分析。

## 接口

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/v1/analysis-runs` | 接收 `AnalyzeRequest`，返回 HTTP 202 和 `AnalysisRun`；编号由服务端生成 |
| `GET /api/v1/analysis-runs/{run_id}` | 查询执行状态、事件游标和已完成报告 |
| `GET /api/v1/analysis-runs/{run_id}/events?after=0` | 从指定游标之后读取 NDJSON；每行是 `{event_id, event}` |
| `POST /api/v1/analysis-runs/{run_id}/resume` | 继续已中断任务，保持编号与原始请求不变 |

事件编号从 1 开始递增。断线后传最后已处理的编号，重复事件可忽略，跳号需要重新补读。心跳使用 `{type: "heartbeat", run_id}`，不消耗事件编号。完成事件与最终报告持久化后可重新查询。

原有 `/analyze`、`/analyze/stream` 保持请求和响应结构兼容；恢复能力通过新接口提供。所有 HTTP 创建入口都由服务端分配编号并覆盖客户端的 `request_context.run_id`，防止旧接口绕过执行锁写入已有任务的检查点。

## 执行与恢复

状态为 `queued`、`running`、`completed`、`failed`、`interrupted`。`completed` 表示成功产出报告；报告内的 `insufficient`、`conflicting` 是合法核查结果。运行完成不会使事实结论变得更确定。

后台运行与浏览器订阅分离。关闭页面只结束订阅，不会取消核查。前端对临时断连最多自动重连三次，之后可手动“重新连接”。创建响应丢失时不自动重发创建请求，以避免重复任务。

SQLite 中的原子事务控制创建、容量和恢复；运行持有 30 秒租约，执行期间续租。进程退出后，租约过期的任务在下次访问时标记为 `interrupted`，页面提供“继续核查”。活动或完成任务的恢复请求是幂等的，失败任务返回 409，需要新建。

每个 run 还持有覆盖整个 Pipeline 生命周期的操作系统文件锁：POSIX 使用 `flock`，Windows 使用 `msvcrt.locking`。锁获取和数据库所有权变更在同一个数据库事务内协调。租约过期但旧进程仍在执行或暂停时，恢复返回可重试的 `409 run_still_executing`；旧 Pipeline 退出后才能开始新一代执行。进程死亡由操作系统释放锁。因此旧一代尚未返回的调用或检查点写入不会与恢复后的 Pipeline 并行覆盖同一检查点。

恢复使用同一个 `run_id` 调用现有 Pipeline。设置 `AGENT_CHECKPOINT_ENABLED=true`，并启用深度 Agent 编排后，可以恢复已有步骤检查点；没有可用检查点时会重新执行原请求。恢复不是恰好一次的外部调用保证：已经发出的网络/模型请求无法撤销。执行层租约防止失效任务写入新事件或覆盖最终报告。

## 存储与部署

| 配置 | 默认值 |
| --- | --- |
| `ANALYSIS_RUN_DIR` | `data/analysis_runs` |
| `ANALYSIS_RUN_RETENTION_SECONDS` | `86400`，终态记录保留一天 |
| `ANALYSIS_RUN_MAX_ACTIVE` | `4`，共享数据库中的活动任务上限 |

容量满返回 429。过期清理在接口访问时执行，活动任务不会被清理；已经标记中断但仍持有执行锁的旧任务也不会被删除，且继续占用活动容量。锁释放后，已过保留期的请求及锁文件才会清理；不存在或过期的编号返回 404。数据库保存恢复所需的请求、事件、报告，目录权限为 0700，数据库和执行锁文件为 0600，默认目录已被 Git 忽略。

这是本机持久化执行层，同机 worker 需要共享 SQLite、执行锁和 checkpoint 目录，存储需要支持本机文件锁语义。租约失效不强制终止旧 Pipeline；若旧调用一直不返回，需要终止对应进程后再恢复。多主机分布式执行、严格终止正在执行的网络调用、完整用户身份与权限管理不在本次实现范围。

`run_id` 是不可枚举的随机编号，也是当前访问记录的凭据；请将任务链接视为私有链接。接口不提供所有用户的全局任务列表。公开部署需由现有网关提供访问控制；恢复功能不会自动新增账号系统。

私有 run 响应包含 `raw_input` 完整原始请求，用于刷新后恢复核查入口；`input_preview` 仅供列表式摘要展示，最多 140 字符，不能用作重新核查的输入。原始请求不写入任务 URL。

## 验证入口

```bash
python -m pytest backend/tests/test_analysis_runs.py backend/tests/test_analysis_run_api.py -q
cd frontend && npm test -- lib/__tests__/run-session.test.ts lib/__tests__/analysis-runs-api.test.ts
```

验证包含断开后游标回放、报告持久化、租约失效与恢复、并发恢复幂等、旧 Pipeline 延迟检查点写入与新一代隔离、真实子进程死亡后解锁、执行中任务的容量/过期保护、完整原始请求恢复、错误脱敏、StrictMode 创建复用及旧订阅隔离。
