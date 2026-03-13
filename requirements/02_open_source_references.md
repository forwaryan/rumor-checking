# 开源参考与可借鉴思路

以下不是让项目直接照抄，而是帮助我们更快确定实现路径与技术边界。

## 1. FEVER

- 仓库：https://github.com/awslabs/fever
- 用途：经典事实核查 benchmark，强调“claim + evidence + verdict”
- 可借鉴点：
  - 核查任务必须证据先行
  - verdict 不能脱离 evidence 单独给
  - 适合作为 claim verifier 的任务建模参考

## 2. AVeriTeC

- 仓库：https://github.com/MichSchli/AVeriTeC
- 用途：真实世界 claim verification 数据集，证据来自开放 Web
- 可借鉴点：
  - 更接近本题真实场景
  - 可以参考其“真实 claim + 网络证据”的组织方式
  - 对我们设计 evidence schema 很有帮助

## 3. HerO

- 仓库：https://github.com/ssu-humane/HerO
- 用途：AVeriTeC 任务中的高排名开源 pipeline
- 可借鉴点：
  - 两阶段检索
  - 问题生成 / 证据组织 / verdict 预测分模块处理
  - 很适合借鉴成“多阶段 AI pipeline”讲法

## 4. AIC AVeriTeC

- 仓库：https://github.com/aic-factcheck/aic_averitec
- 用途：把 fact-checking 重构成一个 RAG 任务
- 可借鉴点：
  - 说明本题完全可以用 RAG 思路做
  - 检索、证据生成、分类器分离的结构值得借鉴

## 5. news-please

- 仓库：https://github.com/fhamborg/news-please
- 用途：新闻网页抓取与正文抽取
- 可借鉴点：
  - 可直接用于新闻正文抽取
  - 有利于统一 URL 输入体验
  - 比自己写规则更省时间

## 6. newspaper / newspaper4k

- 仓库：
  - https://github.com/codelucas/newspaper
  - https://github.com/AndyTheFactory/newspaper4k
- 用途：新闻文章标题、正文、元信息提取
- 可借鉴点：
  - 轻量，适合快速做原型
  - 可作为网页正文抽取的 fallback

## 7. gdeltdoc / GDELT 相关客户端

- 仓库：https://github.com/samswede/gdelt_api
- 用途：基于 GDELT 获取新闻时间线与文章列表
- 可借鉴点：
  - 传播链中的“热度高峰窗口”可用时间线方式表达
  - 比自己维护新闻库更现实

## 8. 如何正确借鉴

建议借鉴的是“任务拆解方法”，不是整套重系统：

- 从 FEVER / AVeriTeC 借 claim verification 的任务定义
- 从 HerO / AIC AVeriTeC 借多阶段 pipeline 和 RAG 思路
- 从 news-please / newspaper4k 借正文抽取
- 从 GDELT 相关工具借传播时间线表达

## 9. 对我们最有价值的结论

如果只保留三条开源启发，应该是：

1. fact-checking 一定要按 `claim -> evidence -> verdict` 组织
2. 传播链不必一开始就做成复杂图数据库，时间线 + 关键节点更适合 demo
3. 第一版重点是组合成熟能力，做出可信、稳定、可讲的产品闭环
