import type {
  AnalysisStatus,
  ConfidenceValue,
  DemoCaseSummary,
  Evidence,
  InputType,
  OutputMode,
  Report,
  Verdict,
} from "@/types/report";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";

const modeCopy: Record<
  OutputMode,
  {
    label: string;
    kicker: string;
    summary: string;
  }
> = {
  complete_mode: {
    label: "完整模式",
    kicker: "主要链路已连通",
    summary: "事件、时间线、claim 和证据均已返回，可进入完整阅读。",
  },
  partial_mode: {
    label: "部分模式",
    kicker: "局部结果可用",
    summary: "页面只展示已验证部分，并显式标注缺口和后续待核查点。",
  },
  safe_mode: {
    label: "安全模式",
    kicker: "关键证据不足",
    summary: "系统保守收口，只展示边界化信息，不输出过度确定结论。",
  },
};

const verdictTone: Record<Verdict, string> = {
  supported: "可信支持",
  refuted: "明确反驳",
  insufficient: "证据不足",
  conflicting: "证据冲突",
};

export function getModeMeta(mode: OutputMode) {
  return modeCopy[mode];
}

export function getVerdictLabel(verdict: Verdict) {
  return verdictTone[verdict];
}

export function getStatusFromMode(mode: OutputMode): AnalysisStatus {
  switch (mode) {
    case "complete_mode":
      return "complete";
    case "partial_mode":
      return "partial";
    default:
      return "safe_mode";
  }
}

export function formatDisplayTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间待补充";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatConfidence(value: ConfidenceValue) {
  if (typeof value === "number") {
    return `${Math.round(value * 100)}%`;
  }

  switch (value) {
    case "high":
      return "高";
    case "medium":
      return "中";
    default:
      return "低";
  }
}

export function sortTimeline<T extends { published_at: string }>(items: T[]) {
  return [...items].sort((left, right) => {
    return new Date(left.published_at).getTime() - new Date(right.published_at).getTime();
  });
}

export function collectEvidence(report: Report) {
  const seen = new Map<string, Evidence>();

  for (const source of report.sources) {
    seen.set(source.url, source);
  }

  for (const claim of report.claim_results) {
    for (const evidence of claim.evidence) {
      if (!seen.has(evidence.url)) {
        seen.set(evidence.url, evidence);
      }
    }
  }

  return Array.from(seen.values()).sort((left, right) => {
    return new Date(right.published_at).getTime() - new Date(left.published_at).getTime();
  });
}

export function validateInput(input: string, inputType: InputType) {
  const trimmed = input.trim();

  if (!trimmed) {
    return "请先输入 URL、正文或问题，再开始分析。";
  }

  if (inputType === "url") {
    try {
      const parsed = new URL(trimmed);
      if (!/^https?:$/.test(parsed.protocol)) {
        return "URL 需要以 http:// 或 https:// 开头。";
      }
    } catch (error) {
      return "当前输入类型是 URL，请粘贴一个有效链接。";
    }
  }

  return null;
}

export function buildFallbackReport(input: string, inputType: InputType): Report {
  const compact = input.trim().replace(/\s+/g, " ");
  const preview = compact.length > 140 ? `${compact.slice(0, 140)}...` : compact;
  const now = new Date().toISOString();

  const sourceName = inputType === "url" ? "用户提供链接" : "用户提供文本";
  const sourceUrl = inputType === "url" && compact ? compact : "https://example.org/demo/manual-input";

  return {
    mode: "safe_mode",
    event: {
      title: "接口暂不可达，当前展示安全模式回退结果",
      summary: preview || "系统尚未拿到足够上下文，无法进入标准核查流程。",
      source_url: sourceUrl,
      source_name: sourceName,
      published_at: now,
      keywords: ["fallback", "safe_mode", "待核查"],
      mode: "safe_mode",
    },
    timeline: [],
    claim_results: [
      {
        claim: "当前输入值得继续核查，但系统尚未拿到足够证据形成稳定 verdict。",
        claim_type: "unverifiable",
        verdict: "insufficient",
        confidence: "low",
        evidence: [],
        notes: "这是前端的保守回退结果，用来明确提示当前链路卡在后端或检索阶段。",
      },
    ],
    final_summary:
      "当前页面没有拿到真实 Report，因此只保留边界化提示。建议稍后重试，或先使用下方稳定 demo case 继续演示。",
    risks: [
      "当前结果不是后端真实分析输出，只是前端安全回退壳。",
      "时间线、claim 和证据都未完成真实检索，请避免把它当作结论页面。",
    ],
    sources: [],
  };
}

export function getIdleDemoHints(): DemoCaseSummary[] {
  return getLocalDemoCaseSummaries();
}
