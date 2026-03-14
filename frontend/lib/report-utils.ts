import type {
  AnalysisStatus,
  ConfidenceValue,
  Evidence,
  InputType,
  OutputMode,
  Report,
  ReportFallbackReason,
  ReportProvenance,
  ReportProvenanceState,
  ReportSourceKind,
  Verdict,
} from "@/types/report";

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

export interface ReportProvenanceMeta {
  sourceKind: ReportSourceKind;
  sourceLabel: string;
  summary: string;
  caution?: string;
  fallbackLabel?: string;
  detailBadges: string[];
  tone: "live" | "mock" | "replay" | "demo" | "fallback" | "unknown";
}

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

function getFallbackLabel(reason?: ReportFallbackReason) {
  switch (reason) {
    case "backend_offline":
      return "后端离线回退";
    case "analyze_failed":
      return "请求失败回退";
    case "missing_provenance":
      return "来源待确认";
    default:
      return undefined;
  }
}

function getBackendFallbackLabel(provenance: ReportProvenance | null | undefined) {
  if (!provenance?.fallback_used) {
    return undefined;
  }

  return provenance.fallback_reasons.length > 0 ? "后端保守降级" : "后端回退中";
}

function formatFallbackReasons(reasons: string[]) {
  return reasons.length > 0 ? reasons.join(" / ") : "未提供具体原因";
}

function getBackendDetailBadges(provenance: ReportProvenance) {
  const badges = [
    `claims:${provenance.claim_source}`,
    `evidence:${provenance.evidence_source}`,
    `timeline:${provenance.timeline_source}`,
  ];

  if (provenance.provider_used) {
    badges.push(`provider:${provenance.retrieval_provider ?? "on"}`);
  }

  if (provenance.retrieval_cache_status) {
    badges.push(`cache:${provenance.retrieval_cache_status}`);
  }

  if (provenance.fallback_used) {
    badges.push("fallback:on");
  }

  return badges;
}

function getEffectiveProvenanceState(report: Report, provenance: ReportProvenanceState | null): ReportProvenanceState {
  if (provenance) {
    return provenance;
  }

  if (report.provenance) {
    return {
      sourceKind: report.provenance.source_type,
      reportProvenance: report.provenance,
    };
  }

  return {
    sourceKind: "unknown",
    fallbackReason: "missing_provenance",
  };
}

function getBackendLiveCaution(provenance: ReportProvenance) {
  if (provenance.evidence_source !== "retrieval_live") {
    return `当前虽然标记为 backend_live，但 evidence_source=${provenance.evidence_source}，还不能把它讲成真实检索已完整跑通。`;
  }

  if (provenance.fallback_used) {
    return `后端这次仍触发了保守降级：${formatFallbackReasons(provenance.fallback_reasons)}。`;
  }

  return undefined;
}

export function getReportProvenanceMeta(
  report: Report | null,
  provenance: ReportProvenanceState | null,
): ReportProvenanceMeta | null {
  if (!report) {
    return null;
  }

  const modeMeta = getModeMeta(report.mode);
  const effectiveProvenance = getEffectiveProvenanceState(report, provenance);
  const backendProvenance = effectiveProvenance.reportProvenance ?? report.provenance ?? null;

  switch (effectiveProvenance.sourceKind) {
    case "backend_live":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: "backend_live",
        summary: `当前页面以${modeMeta.label}展示后端实时 analyze 返回，证据路径为 ${backendProvenance?.evidence_source ?? "unknown"}，时间线路径为 ${backendProvenance?.timeline_source ?? "unknown"}。`,
        caution: backendProvenance ? getBackendLiveCaution(backendProvenance) : "缺少完整 provenance 细节，讲解时仍需按保守路径理解。",
        fallbackLabel: getBackendFallbackLabel(backendProvenance),
        detailBadges: backendProvenance ? getBackendDetailBadges(backendProvenance) : [],
        tone: "live",
      };
    case "backend_mock":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: "backend_mock",
        summary: `当前页面以${modeMeta.label}展示后端 mock 联调结果，证据路径为 ${backendProvenance?.evidence_source ?? "unknown"}。`,
        caution: "这是后端 mock 路径，只适合联调或演示，不应当作真实较真已经完成。",
        fallbackLabel: getBackendFallbackLabel(backendProvenance),
        detailBadges: backendProvenance ? getBackendDetailBadges(backendProvenance) : [],
        tone: "mock",
      };
    case "backend_replay":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: "backend_replay",
        summary: `当前页面以${modeMeta.label}展示后端 replay 回放结果，适合复现 UI、测试或联调口径。`,
        caution: "这不是针对当前输入的实时 analyze，请不要把结论、时间线或 claim 讲成最新分析输出。",
        fallbackLabel: getBackendFallbackLabel(backendProvenance),
        detailBadges: backendProvenance ? getBackendDetailBadges(backendProvenance) : [],
        tone: "replay",
      };
    case "demo_payload":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: "demo_payload",
        summary: `当前页面仍以${modeMeta.label}展示仓库内 demo payload，用来稳定演示页面结构和边界。`,
        caution: "这不是本次输入的实时分析结果，请不要把结论、时间线或 claim 当成真实推理输出。",
        fallbackLabel: getFallbackLabel(effectiveProvenance.fallbackReason),
        detailBadges: [],
        tone: "demo",
      };
    case "frontend_fallback":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: "frontend_fallback",
        summary: `当前页面只保留${modeMeta.label}的保守展示壳，用来提示边界和空态，不代表后端已产出可用 Report。`,
        caution: "请不要把当前页面内容解释成真实分析；恢复接口后应重新提交输入。",
        fallbackLabel: getFallbackLabel(effectiveProvenance.fallbackReason),
        detailBadges: [],
        tone: "fallback",
      };
    default:
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: "unknown",
        summary: "当前页面拿到了可渲染数据，但 report.provenance 缺失或不完整，先按非真实分析结果理解。",
        caution: "旧 payload 或字段不足的结果都会落到这个标签，避免误讲成真实 analyze 输出。",
        fallbackLabel: getFallbackLabel(effectiveProvenance.fallbackReason),
        detailBadges: [],
        tone: "unknown",
      };
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
    investigation: {
      question: compact || "待核查问题",
      reframed_question: preview || "待核查命题",
      thinking_process: [
        {
          title: "先保留输入原貌",
          detail: "当前是前端 fallback 结果，系统只能先把原始输入保留下来，避免伪造检索结论。",
        },
        {
          title: "暂停事实锁定",
          detail: "由于真实 analyze 没有成功返回，页面无法确认具体事件、人物或传播链。",
        },
        {
          title: "输出边界而不是强判",
          detail: "在后端和检索链路恢复前，页面只展示待核查路径和风险提示，不输出确定性结论。",
        },
      ],
      possibilities: [
        {
          scenario: "输入值得继续核查，但当前没有稳定证据链",
          likelihood: "medium",
          summary: "需要后端恢复后重新发起 analyze，才能判断它究竟是事实、旧闻回流还是纯传闻。",
        },
        {
          scenario: "也可能只是缺少关键锚点，暂时无法锁定具体事件",
          likelihood: "low",
          summary: "姓名、原帖链接、平台账号和精确时间点都会显著影响系统是否能对上真实事件。",
        },
      ],
      final_conclusion: "当前不能给出真假结论，因为页面拿到的是前端 fallback，而不是真实核查结果。",
    },
    pipeline_trace: {
      steps: [
        {
          stage_key: "input_received",
          title: "接收输入",
          status: "completed",
          summary: "前端已记录当前输入，并准备调用 analyze 接口。",
          details: [`原始输入：${preview || "无"}`, `输入类型：${inputType}`],
        },
        {
          stage_key: "frontend_fallback",
          title: "前端回退",
          status: "warning",
          summary: "真实 analyze 未成功返回，页面只能渲染前端 fallback 结果。",
          details: [
            "当前链路没有拿到后端真实中间步骤。",
            "需要待接口恢复后重新提交，才能看到完整分析链路。",
          ],
        },
        {
          stage_key: "report_output",
          title: "报告输出",
          status: "warning",
          summary: "页面当前展示的是安全模式回退结果，不代表真实核查已完成。",
          details: ["mode：safe_mode", "source_type：frontend_fallback"],
        },
      ],
    },
    sources: [],
  };
}
