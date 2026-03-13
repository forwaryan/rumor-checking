import completeReport from "../../contracts/demo_payloads/complete_mode_report.json";
import partialReport from "../../contracts/demo_payloads/partial_mode_report.json";
import safeReport from "../../contracts/demo_payloads/safe_mode_report.json";
import type { DemoCase, DemoCaseSummary, Report } from "@/types/report";

const demoCases: DemoCase[] = [
  {
    id: "night-traffic",
    title: "完整模式 / 夜间绕行误传",
    description: "官方澄清齐全，适合演示完整时间线、claim 核查与证据回溯。",
    input_type: "url",
    sample_input: "https://example.org/demo/night-traffic-clarification",
    mode: "complete_mode",
    report: completeReport as Report,
  },
  {
    id: "cable-car",
    title: "部分模式 / 景区缆车传言",
    description: "能确认停运和滞留，但伤亡与故障原因仍待补充核实。",
    input_type: "text",
    sample_input:
      "网传某景区缆车故障导致多人伤亡，帮我看看公开信息里哪些已经证实，哪些还不能下结论。",
    mode: "partial_mode",
    report: partialReport as Report,
  },
  {
    id: "water-rumor",
    title: "安全模式 / 检测截图待核查",
    description: "只有来源不完整的截图，页面会保守展示待核查点与边界说明。",
    input_type: "question",
    sample_input:
      "这张说某品牌矿泉水抽检超标的截图靠谱吗？目前能确认到什么程度？",
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
