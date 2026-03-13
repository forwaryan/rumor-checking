# Tasks Index

本目录用于存放可独立并行推进的任务文件。

每个任务文件都对应一个可以单独分配给窗口或集群的工作包，而不是单个零散动作。

## 使用方式

1. 先看本目录，决定当前要开几个窗口。
2. 给每个窗口分配一个独立的任务文件。
3. 每个窗口只以自己负责的任务文件为主，不主动跨界修改其他工作包的核心文件。
4. 某个子任务完成后，手动把该任务文件中的状态从“未完成”更新为“已完成”。

## 当前任务文件

- `cluster-a-control-tower.md`
- `cluster-b-contract-forge.md`
- `cluster-c-api-foundation.md`
- `cluster-d-retrieval-lab.md`
- `cluster-e-experience-shell.md`
- `cluster-f-quality-gate.md`
- `cluster-g-demo-ops.md`

## 任务结构说明

每个任务文件都包含：

- 这个子 task 是干什么的
- 为什么要有这个子 task
- 为什么这个子 task 可以并行
- 详细子任务
- 每个子任务下的“子子任务清单”

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

当前所有子任务默认都以 `未完成` 初始化。

