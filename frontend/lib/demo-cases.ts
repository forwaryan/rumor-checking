import type { DemoCaseSummary } from "@/types/report";

const demoCases: DemoCaseSummary[] = [
  {
    id: "expired-yogurt",
    title: "示例输入 / 海州酸奶抽检",
    description: "适合测试较完整的文本新闻核查链路。",
    input_type: "text",
    sample_input:
      "3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。",
    mode: "complete_mode",
  },
  {
    id: "chemical-odor",
    title: "示例输入 / 化工厂异味核查",
    description: "适合测试真假混杂、说法冲突的文本输入。",
    input_type: "text",
    sample_input:
      "北城区化工厂夜间异味被居民连续投诉，区生态环境局已经进场核查，但媒体称工厂停产整顿，公司又回应只暂停一条产线。",
    mode: "partial_mode",
  },
  {
    id: "morningstar-layoff",
    title: "示例输入 / 裁员传闻追问",
    description: "适合测试问题型输入是否能被 Kimi 正常收束。",
    input_type: "question",
    sample_input: "晨星生物已经宣布裁员40%了吗？",
    mode: "safe_mode",
  },
];

export function getLocalDemoCaseSummaries(): DemoCaseSummary[] {
  return demoCases;
}
