# Requirements

本目录用于沉淀题目需求、评分拆解、方案设计和实现规划。

## analysis

- `analysis/01_scope_and_v1_design.md`：对题目与评分标准的详细分析，以及第一版产品和技术方案
- `analysis/02_prototype_review_and_alignment.md`：对当前仓库内所有原型文档的实现逻辑、实现思路、实现技术和需求对齐总结
- `analysis/03_high_score_gap_analysis.md`：从高分目标出发，对当前规则与内容的缺口分析，以及建议新增的规则清单
- `analysis/04_implementation_difficulty_analysis.md`：对当前项目真正的实现难点、风险优先级以及两天内可落地策略的分析
- `analysis/05_difficulty_summary_and_boundary_confirmation.md`：面向沟通场景汇总实现难点、待确认边界、默认口径与流程图
- `analysis/06_propagation_vs_verification_depth_review.md`：复盘“传播链还原”和“内容核查”两大核心任务目前分析到了什么深度、还缺什么规则，以及薄弱点的根因
- `analysis/07_v1_execution_plan.md`：从当前文档阶段进入实现阶段的开工顺序、验证任务、首批模块和完成标准

## research

- `research/01_open_source_references.md`：可借鉴的开源项目、可复用思路和取舍建议
- `research/02_product_benchmark_and_design_goals.md`：同类产品 / 开源实现调研、能力对比，以及反推出的自有设计目标

## guides

- `guides/01_bracket_trigger_commands_guide.md`：统一整理 `[Log]`、`[scores]`、`[Commit]` 等方括号触发指令、参数位和执行逻辑图
- `guides/02_prompt_asset_templates.md`：兼容旧引用的 Prompt 模板入口，模板内容已并入 `04_prompt_inventory.md`
- `guides/03_random_news_eval_template.md`：随机新闻输入下的评测表模板、通过标准与 case 配比建议
- `guides/04_prompt_inventory.md`：当前仓库已使用 Prompt 的总清单、可复用 Prompt 家族，以及合并后的 Prompt 资产模板附录
- `guides/05_validation_execution_checklist.md`：输入验证、检索验证、verdict 验证的执行清单、case 配置与通过标准
- `guides/06_input_sample_bank_template.md`：20 条输入样本骨架，覆盖标准新闻 URL、抽取不稳定 URL 和文本输入
