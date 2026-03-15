> 本目录主要记录执行分工和回写状态，不是代码事实的唯一来源。若与代码实现冲突，先看 `../docs/status/current-verified-state.md`；冲突问题统一登记在 `../docs/status/document-conflict-register.md`，原文件直接更新。

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
- `multi-agent-execution-board.md`
- `high-score-final-execution-plan.md`
- `post-we-closeout-plan.md`
- `high-score-thread-prompts/README.md`
- `post-we-closeout-thread-prompts/README.md`

## 当前全局状态

截至 `2026-03-14 22:11`，当前已经确认：

- `C10` 已完成第一阶段。
- `C11` 已完成第一阶段。
- `E9` 当前 provenance 展示已落地。
- `F2 / F3 / F4 / F5 / F6 / F7` 已完成。
- `F8` 已形成正式验收记录，但结论是“真实 live 路径当前未通过最终验收”。

因此当前真正还没收口的，不再是“主链有没有”，而是：

- live retrieval 稳不稳定。
- 稳定 demo 是否存在模式漂移。
- README / 演示稿 / 边界说明是否已经同步最新结论。
- replay 草案何时适合冻结为最终口径。

## 当前最高优先级

1. `Cluster-D / Retrieval Lab`
   - 核心是 live retrieval 稳定性。
   - 当前没有 `backend_live + retrieval_live` 的通过样本，这是最直接的阻塞。
2. `Cluster-C / API Foundation`
   - 核心是稳定 demo 的模式漂移、provider / retrieval 质量与主链边界收口。
3. `Cluster-G / Demo Ops`
   - 核心是把 `F8` 的正式结论同步到 README、演示脚本和边界文档。
4. `Cluster-G / G2`
   - replay 仍应继续保留为草案，等真实路径和术语更稳定后再定稿。

## 当前建议窗口

| 窗口 | 建议任务 | 主要文件范围 | 为什么现在适合并行 |
| --- | --- | --- | --- |
| `W-A` | live retrieval 稳定性 | `backend/app/services/retrieval_*.py`、`backend/tests/test_retrieval.py` | 直接解决真实路径无通过样本的问题。 |
| `W-B` | demo 模式漂移与质量收口 | `backend/app/services/verdict_engine.py`、`report_builder.py`、相关验收文档 | 直接影响稳定 demo 与最终演示口径。 |
| `W-C` | 文档与演示口径同步 | `README.md`、`DEMO_SCRIPT.md`、`overview/11`、`overview/12` | 需要基于 `F8` 结论同步当前说法。 |
| `W-D` | replay 最终定稿 | `data/demos/README.md`、相关说明文档 | 适合在前几项稳定后继续推进。 |

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
