# Demo Replay Draft

更新时间：2026-03-14（Asia/Shanghai）

## 1. 这份文档现在负责什么

这份文档只做三件事：

- 给 `G2` 第一阶段固定 replay 资产的目录落点
- 给后续窗口提供一个可直接填写的 replay 文件格式草案
- 明确哪些字段现在不要提前冻结，避免 `C10 / C11 / F8` 还没收口时又写出第二套口径

当前不要把它理解成：

- 后端 replay 接口说明
- 已经正式生效的 schema
- 已经通过随机 case 验收的运行结论

## 2. 当前阶段结论

- 本轮先采用“文件级 replay bundle”草案，而不是先设计 `POST /api/v1/replay`
- replay 正式资产统一落到 `data/demos/replays/`
- 顶层 README 只负责给入口，不在 README 里重复写最终字段定义
- 前端当前稳定演示仍以 `contracts/demo_payloads/` 为主；`data/demos/replays/` 是后续补真实回放和验收记录的落点

## 3. 目录落点

当前先冻结成下面这一层：

```text
data/
  demos/
    README.md
    replays/
      .gitkeep
```

说明：

- `data/demos/replays/`：后续正式 replay 文件统一放这里
- 本轮不提前新增 `manifests/`、`artifacts/`、`screenshots/` 等目录，避免过度设计
- 如果后续 `F8` 需要把一批 replay 升级成正式验收记录，再根据真实需要补子目录

## 4. 建议命名规则

第一阶段先按下面的文件名模式收口：

```text
data/demos/replays/<case_id>--<mode>--<source_tag>--<yyyymmdd>.json
```

示例：

```text
data/demos/replays/expired-yogurt--complete-mode--backend-real--20260314.json
```

字段说明：

- `case_id`：稳定 demo 或验收 case 的短 id，例如 `expired-yogurt`
- `mode`：当前页面或报告期望表达的模式，例如 `complete-mode`
- `source_tag`：先用可读短标签，不在本轮提前冻结最终 provenance 术语
- `yyyymmdd`：生成日期；如果同日多次生成，可后续再补时间戳

## 5. 单文件 replay bundle 草案

当前建议每个 replay 用一个 JSON bundle 表示。第一阶段先按下面的形状理解：

```json
{
  "replay_version": "draft-v1",
  "replay_id": "expired-yogurt--complete-mode--backend-real--20260314",
  "case_id": "expired-yogurt",
  "captured_at": "2026-03-14T18:30:00+08:00",
  "scenario": {
    "input_type": "text_news",
    "expected_mode": "complete_mode",
    "usage": "demo"
  },
  "request": {
    "endpoint": "/api/v1/analyze",
    "payload": {
      "input": "[待补原始输入]",
      "input_type": "[待补]"
    },
    "request_context": {
      "bypass_retrieval_cache": false,
      "retrieval_cache_only": false,
      "allow_stale_retrieval_cache": false
    }
  },
  "response": {
    "status_code": 200,
    "body": "[待补真实 report 或 demo payload]"
  },
  "capture_notes": {
    "runner": "[待补]",
    "purpose": "demo",
    "notes": "[待补]"
  }
}
```

第一阶段只冻结最小层级：

- `scenario`
- `request`
- `response`
- `capture_notes`

这样后续无论是补真实后端结果、demo payload、还是 smoke 记录，都有同一层基本外壳可填。

## 6. 现在不要提前冻结的字段

下面这些字段或语义，本轮只留占位，不做最终命名承诺：

- `response.body.provenance` 的最终结构：等 `C11`
- URL 抽取相关字段：等 `C10`
- 真实检索命中、来源层级、fallback 分类的最终术语：等 `C11`
- 哪些 replay 能被认定为“正式验收记录”：等 `F8`
- 是否需要独立 `artifacts` 字段存截图、日志、smoke 引用：等 `F8`

## 7. 后续怎么补

建议后续窗口按这个顺序补：

1. `C10` 收口后，再补 URL 输入 replay 的最小字段和命名约束
2. `C11` 冻结 provenance 后，再补 `response.body` 中与来源、回退、检索命中的正式字段说明
3. `F8` 完成后，再决定哪些 replay 只用于演示，哪些要升级成正式验收记录

## 8. 当前一句话边界

截至 2026-03-14，这里只是 replay 的目录和格式草案，不是已经落地的 replay 能力说明。
