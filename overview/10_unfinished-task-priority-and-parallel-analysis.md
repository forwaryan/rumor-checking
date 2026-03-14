# 10 未完成任务优先级与并行分析

更新时间：2026-03-14 22:11（Asia/Shanghai）

## 1. 一句话判断

当前真正还需要继续推进的，不再是 `C10 / F2 / F4 / F6 / E9` 这些基础收口任务，而是：

1. `D5 ~ D7` 相关的真实 live retrieval 稳定性。
2. `C9 / C11` 相关的模式漂移与质量收口。
3. `G3 / G4` 根据 `F8` 结论做文档、README、演示口径同步。
4. `G2` replay 从文件草案走向最终定稿。

## 2. 当前离“任意新闻都能较真”还差什么

```mermaid
flowchart LR
    A["随机文本 / URL / 问题输入"] --> B["C10 已完成: 公开 HTML URL 抽取 + fallback"]
    B --> C["C11 第一阶段已完成: provenance + real analyze 主链"]
    C --> D["F2/F3/F4/F5/F6/F7 已完成"]
    D --> E["F8 已形成正式验收记录"]
    E --> F["当前最大缺口: real live retrieval 没有通过样本"]
    F --> G["下一步: D live retrieval 稳定性 + C 模式漂移收口 + G 文档同步"]
```

## 3. 当前优先级排序

| 优先级 | 任务 | 是否必须 | 为什么重要 |
| --- | --- | --- | --- |
| P0 | `Cluster-D` live retrieval 稳定性 | 是 | 没有 `backend_live + retrieval_live` 通过样本，就不能说真实路径已经稳定。 |
| P0 | `Cluster-C` demo 模式漂移与质量收口 | 是 | 稳定 demo 的 mode 漂移会直接影响演示可信度。 |
| P1 | `Cluster-G / G3 / G4` 最终文档同步 | 是 | 当前 README、演示稿和边界说明都要基于 `F8` 结论重新统一。 |
| P2 | `Cluster-G / G2` replay 定稿 | 建议 | 现在已有草案，但应等真实路径和最终术语更稳定后再冻结。 |
| P2 | `Cluster-A` 总控回写 | 建议 | 需要继续把最新状态同步到任务板和交付口径。 |

## 4. 当前最适合立刻并行的窗口

| 并行窗口 | 负责任务 | 主要文件范围 | 为什么适合并行 |
| --- | --- | --- | --- |
| `W-A` | live retrieval 稳定性 | `backend/app/services/retrieval_*.py`、`backend/tests/test_retrieval.py` | 直接解决真实路径无通过样本的问题。 |
| `W-B` | mode 漂移与质量收口 | `backend/app/services/verdict_engine.py`、`report_builder.py`、相关验收文档 | 直接影响稳定 demo 和随机 case 的讲法。 |
| `W-C` | 文档与演示口径同步 | `README.md`、`DEMO_SCRIPT.md`、`overview/11`、`overview/12` | 基于 `F8` 结论更新对外说法。 |
| `W-D` | replay 最终定稿 | `data/demos/README.md`、`overview/11`、相关说明文档 | 等前面结论稳定后再冻结。 |

## 5. 不建议现在重复开的窗口

| 任务 | 原因 |
| --- | --- |
| `C10` | 第一阶段已经完成，不是当前主阻塞。 |
| `F2 / F4 / F6` | 独立回归已经收口，不应继续把它们当默认主窗口。 |
| `E9` | 当前前端 provenance 主展示已落地，只需后续随口径做小同步。 |

## 6. 当前结论

当前最重要的不是“再补一个功能点”，而是把已经存在的主链证明成稳定、可讲、可交付的真实路径。
