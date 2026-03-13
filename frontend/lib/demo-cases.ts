import completeReport from "../../contracts/demo_payloads/complete_mode_report.json";
import partialReport from "../../contracts/demo_payloads/partial_mode_report.json";
import safeReport from "../../contracts/demo_payloads/safe_mode_report.json";
import type { DemoCase, DemoCaseSummary, Report } from "@/types/report";

const demoCases: DemoCase[] = [
  {
    id: "expired-yogurt",
    title: "完整模式 / 海州酸奶抽检",
    description: "命中后端的完整模式场景，适合演示 2 个时间线节点与多条 supported claim。",
    input_type: "text",
    sample_input:
      "3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。",
    mode: "complete_mode",
    report: completeReport as Report,
  },
  {
    id: "chemical-odor",
    title: "部分模式 / 化工厂异味核查",
    description: "命中后端的 partial 场景，适合演示 conflicting verdict 和边界化风险提示。",
    input_type: "text",
    sample_input:
      "北城区化工厂夜间异味被居民连续投诉，区生态环境局已经进场核查，但媒体称工厂停产整顿，公司又回应只暂停一条产线。",
    mode: "partial_mode",
    report: partialReport as Report,
  },
  {
    id: "morningstar-layoff",
    title: "安全模式 / 晨星生物裁员传闻",
    description: "命中 question_only 安全模式，适合演示证据不足、空时间线和保守收口。",
    input_type: "question",
    sample_input: "晨星生物已经宣布裁员40%了吗？",
    mode: "safe_mode",
    report: safeReport as Report,
  },
];

export function getLocalDemoCases(): DemoCase[] {
  return demoCases;
}

export function getLocalDemoCaseSummaries(): DemoCaseSummary[] {
  return demoCases.map(({ report, ...summary }) => summary);
}

export function getLocalDemoCase(id: string): DemoCase | undefined {
  return demoCases.find((item) => item.id === id);
}

export function getLocalDemoReport(id: string): Report | null {
  return getLocalDemoCase(id)?.report ?? null;
}
