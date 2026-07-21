import type {
  AnalysisStatus,
  ClaimType,
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
    label: "高完成度",
    kicker: "主要证据较完整",
    summary: "事件、时间线、claim 和证据都已落盘，适合较完整展示。",
  },
  partial_mode: {
    label: "中完成度",
    kicker: "已有局部结论",
    summary: "页面只展示已核到的部分，并明确保留缺口与待补证点。",
  },
  safe_mode: {
    label: "低完成度",
    kicker: "关键证据不足",
    summary: "系统按保守口径收束，只展示边界说明，不输出过度确定结论。",
  },
};

const verdictTone: Record<Verdict, string> = {
  supported: "更倾向属实",
  refuted: "更倾向不实",
  insufficient: "仍需补证",
  conflicting: "存在冲突",
};

const claimTypeTone: Record<ClaimType, string> = {
  fact: "事实",
  opinion: "观点",
  prediction: "预测",
  unverifiable: "难直接核实",
};

const sourceTypeTone: Record<ReportSourceKind, string> = {
  backend_live: "实时联网结果",
  backend_mock: "后端模拟结果",
  unknown: "来源待确认",
};

const claimSourceTone = {
  rule: "Claim: 规则抽取",
  provider: "Claim: 模型抽取",
  provider_plus_rule: "Claim: 模型 + 规则",
} as const;

const evidenceSourceTone = {
  retrieval_live: "证据: 联网检索",
  retrieval_mock: "证据: 模拟检索",
  request_mock: "证据: 外部注入",
  none: "证据: 暂未建立",
} as const;

const timelineSourceTone = {
  retrieval: "时间线: 检索还原",
  input_seed: "时间线: 输入推断",
  none: "时间线: 暂未建立",
} as const;

const genericEventMarkers = ["待核", "网传", "某女网红", "某网红", "某主播", "用户提问", "真假", "待核事件"];
const genericSummaryMarkers = ["用户提问", "网络流传", "当前输入", "待核查", "真假"];
const genericSourceNames = new Set(["用户问题输入", "用户提供文本", "用户提供链接"]);

const sourceTierWeight = {
  S: 4,
  A: 3,
  B: 2,
  C: 1,
} as const;

export interface TopLineAssessment {
  title: string;
  summary: string;
  tone: Verdict | "neutral";
  confidenceLabel: string;
  decisiveClaim: string | null;
  evidenceCount: number;
  sourceCount: number;
}

export interface ReportProvenanceMeta {
  sourceKind: ReportSourceKind;
  sourceLabel: string;
  summary: string;
  caution?: string;
  fallbackLabel?: string;
  detailBadges: string[];
  tone: "live" | "mock" | "unknown";
}

export interface LlmUsageMeta {
  label: string;
  tone: "live" | "fallback" | "unknown";
}

export interface VerificationScoreMeta {
  score: number;
  label: string;
  modeLabel: string;
  tone: "high" | "medium" | "low";
  summary: string;
}

export function getModeMeta(mode: OutputMode) {
  return modeCopy[mode];
}

export function getVerdictLabel(verdict: Verdict) {
  return verdictTone[verdict];
}

export function getClaimTypeLabel(claimType: ClaimType) {
  return claimTypeTone[claimType];
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

export function getVerificationScoreRuleText() {
  return "基础分：证据较完整 8 分、已有局部结论 5 分、证据稀缺 2 分；明确 claim >= 2 +1；有效证据 >= 3 且含 A/S 来源 +1；时间线 >= 2 且来自检索 +1；存在冲突 -1；缺少来源信息或证据链不足 -1；后端 mock 结果最高 7 分。";
}

function getFallbackLabel(reason?: ReportFallbackReason) {
  return reason === "missing_provenance" ? "来源待确认" : undefined;
}

function getBackendFallbackLabel(provenance: ReportProvenance | null | undefined) {
  if (!provenance?.fallback_used) {
    return undefined;
  }

  return provenance.fallback_reasons.length > 0 ? "后端保守降级" : "后端进入回退";
}

function formatFallbackReasons(reasons: string[]) {
  return reasons.length > 0 ? reasons.join(" / ") : "未提供具体原因";
}

function getBackendDetailBadges(provenance: ReportProvenance) {
  const badges: string[] = [
    claimSourceTone[provenance.claim_source],
    evidenceSourceTone[provenance.evidence_source],
    timelineSourceTone[provenance.timeline_source],
  ];

  if (provenance.provider_used) {
    badges.push(`检索: ${(provenance.retrieval_provider ?? "unknown").toUpperCase()}`);
  }

  if (provenance.retrieval_cache_status) {
    badges.push(`缓存: ${provenance.retrieval_cache_status}`);
  }

  if (provenance.fallback_used) {
    badges.push("状态: 已降级");
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
    return `当前虽然标记为实时联网，但证据来源仍是 ${provenance.evidence_source}，还不能把它讲成完整的真实检索链路。`;
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

  const effectiveProvenance = getEffectiveProvenanceState(report, provenance);
  const backendProvenance = effectiveProvenance.reportProvenance ?? report.provenance ?? null;

  switch (effectiveProvenance.sourceKind) {
    case "backend_live":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: sourceTypeTone.backend_live,
        summary: "这次结果来自后端实时分析，页面展示的是本次请求真实落盘后的结果，并且证据链已经接入真实检索。",
        caution: backendProvenance
          ? getBackendLiveCaution(backendProvenance)
          : "当前缺少完整 provenance 细节，讲解时仍应按保守口径理解。",
        fallbackLabel: getBackendFallbackLabel(backendProvenance),
        detailBadges: backendProvenance ? getBackendDetailBadges(backendProvenance) : [],
        tone: "live",
      };
    case "backend_mock":
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: sourceTypeTone.backend_mock,
        summary: "这次页面展示的是后端 mock 联调结果，适合走通页面和接口，不适合当作真实核查结论。",
        caution: "当前是后端 mock 结果，只适合联调或演示，不应当作真实事件已经核实完成。",
        fallbackLabel: getBackendFallbackLabel(backendProvenance),
        detailBadges: backendProvenance ? getBackendDetailBadges(backendProvenance) : [],
        tone: "mock",
      };
    default:
      return {
        sourceKind: effectiveProvenance.sourceKind,
        sourceLabel: sourceTypeTone.unknown,
        summary: "当前页面拿到了可渲染数据，但 provenance 不完整，先按保守路径理解。",
        caution: "缺字段、旧 payload 或不完整返回都会落到这个标签，避免误讲成真实 analyze 输出。",
        fallbackLabel: getFallbackLabel(effectiveProvenance.fallbackReason),
        detailBadges: [],
        tone: "unknown",
      };
  }
}

export function getLlmUsageMeta(
  report: Report | null,
  provenance: ReportProvenanceState | null,
): LlmUsageMeta | null {
  if (!report) {
    return null;
  }

  const effectiveProvenance = getEffectiveProvenanceState(report, provenance);
  const backendProvenance = effectiveProvenance.reportProvenance ?? report.provenance ?? null;
  if (!backendProvenance) {
    return {
      label: "LLM 检索：状态未知",
      tone: "unknown",
    };
  }

  if (backendProvenance.retrieval_provider !== "kimi") {
    return {
      label: `LLM 检索：未走${backendProvenance.retrieval_provider ? `（当前是 ${backendProvenance.retrieval_provider}）` : ""}`,
      tone: "fallback",
    };
  }

  if (backendProvenance.provider_used && !backendProvenance.fallback_used) {
    return {
      label: "LLM 检索：检索 + 结构化",
      tone: "live",
    };
  }

  if (backendProvenance.provider_used) {
    return {
      label: "LLM 检索：已走但发生降级",
      tone: "fallback",
    };
  }

  return {
    label: "LLM 检索：仅检索 / 结构化未命中",
    tone: "fallback",
  };
}

export function getVerificationScoreMeta(
  report: Report,
  provenance: ReportProvenanceState | null,
): VerificationScoreMeta {
  const modeMeta = getModeMeta(report.mode);
  const effectiveProvenance = getEffectiveProvenanceState(report, provenance);
  const backendProvenance = effectiveProvenance.reportProvenance ?? report.provenance ?? null;
  const decisiveClaims = report.claim_results.filter((item) => item.verdict !== "insufficient");
  const evidence = collectEvidence(report);
  const highTierEvidenceCount = evidence.filter((item) => sourceTierWeight[item.source_tier] >= sourceTierWeight.A).length;
  const supportedCount = decisiveClaims.filter((item) => item.verdict === "supported").length;
  const refutedCount = decisiveClaims.filter((item) => item.verdict === "refuted").length;
  const hasConflict =
    decisiveClaims.some((item) => item.verdict === "conflicting") || (supportedCount > 0 && refutedCount > 0);

  let score = report.mode === "complete_mode" ? 8 : report.mode === "partial_mode" ? 5 : 2;

  if (decisiveClaims.length >= 2) {
    score += 1;
  }

  if (evidence.length >= 3 && highTierEvidenceCount >= 1) {
    score += 1;
  }

  if (report.timeline.length >= 2 && backendProvenance?.timeline_source === "retrieval") {
    score += 1;
  }

  if (hasConflict) {
    score -= 1;
  }

  if (backendProvenance?.fallback_used || backendProvenance?.evidence_source === "none" || evidence.length === 0) {
    score -= 1;
  }

  if (report.mode === "safe_mode") {
    score = Math.min(score, 4);
  } else if (report.mode === "partial_mode") {
    score = Math.min(score, 7);
  }

  if (effectiveProvenance.sourceKind === "backend_mock") {
    score = Math.min(score, 7);
  }

  score = Math.max(1, Math.min(10, score));

  let summary = "当前只适合提示边界和下一步核查点，不适合给过度确定的结论。";
  if (effectiveProvenance.sourceKind === "backend_mock") {
    summary = "当前不是实时联网结果，分数只表示这份结果的展示完整度，不代表当前输入已经被真实核查。";
  } else if (score >= 8) {
    summary = "当前公开证据、claim 和时间线已相对完整，适合较完整讲解，但仍要结合风险项理解。";
  } else if (score >= 5) {
    summary = "当前已经形成局部结论，但链路仍有缺口或边界，不应包装成完整复盘。";
  }

  return {
    score,
    label: `${score}/10`,
    modeLabel: modeMeta.label,
    tone: score >= 8 ? "high" : score >= 5 ? "medium" : "low",
    summary,
  };
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
      return "中等";
    default:
      return "低";
  }
}

function getConfidenceScore(value: ConfidenceValue) {
  if (typeof value === "number") {
    return value;
  }

  switch (value) {
    case "high":
      return 0.95;
    case "medium":
      return 0.7;
    default:
      return 0.35;
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

function isGenericText(text: string, markers: string[]) {
  const compact = text.trim();
  if (!compact) {
    return true;
  }

  return markers.some((marker) => compact.includes(marker));
}

function getLeadEvidence(report: Report) {
  return collectEvidence(report)
    .slice()
    .sort((left, right) => {
      const tierDelta = sourceTierWeight[right.source_tier] - sourceTierWeight[left.source_tier];
      if (tierDelta !== 0) {
        return tierDelta;
      }

      return new Date(right.published_at).getTime() - new Date(left.published_at).getTime();
    })[0];
}

export function getDisplayEventTitle(report: Report) {
  if (!isGenericText(report.event.title, genericEventMarkers)) {
    return report.event.title;
  }

  return getLeadEvidence(report)?.title ?? report.event.title;
}

export function getDisplayEventSummary(report: Report) {
  if (!isGenericText(report.event.summary, genericSummaryMarkers)) {
    return report.event.summary;
  }

  const leadEvidence = getLeadEvidence(report);
  if (leadEvidence?.snippet) {
    return leadEvidence.snippet;
  }

  return report.final_summary;
}

export function getDisplayEventSource(report: Report) {
  const leadEvidence = getLeadEvidence(report);
  const useLeadEvidence =
    genericSourceNames.has(report.event.source_name) ||
    report.event.source_url.includes("example.org/input/");

  if (useLeadEvidence && leadEvidence) {
    return {
      sourceName: leadEvidence.source_name,
      sourceUrl: leadEvidence.url,
      publishedAt: leadEvidence.published_at,
      isDerived: true,
    };
  }

  return {
    sourceName: report.event.source_name,
    sourceUrl: report.event.source_url,
    publishedAt: report.event.published_at,
    isDerived: false,
  };
}

export function getTopLineAssessment(report: Report): TopLineAssessment {
  const decisiveClaims = report.claim_results.filter((item) => item.verdict !== "insufficient");
  const supportedCount = decisiveClaims.filter((item) => item.verdict === "supported").length;
  const refutedCount = decisiveClaims.filter((item) => item.verdict === "refuted").length;
  const conflictingCount = decisiveClaims.filter((item) => item.verdict === "conflicting").length;
  const sortedClaims = report.claim_results
    .slice()
    .sort((left, right) => {
      const verdictRank = {
        conflicting: 4,
        refuted: 3,
        supported: 2,
        insufficient: 1,
      } as const;

      const verdictDelta = verdictRank[right.verdict] - verdictRank[left.verdict];
      if (verdictDelta !== 0) {
        return verdictDelta;
      }

      const confidenceDelta = getConfidenceScore(right.confidence) - getConfidenceScore(left.confidence);
      if (confidenceDelta !== 0) {
        return confidenceDelta;
      }

      return right.evidence.length - left.evidence.length;
    });
  const leadClaim = sortedClaims[0] ?? null;
  const evidence = collectEvidence(report);
  const credibilityLabel = (report as Report & Record<string, unknown>).overall_credibility_label;
  const hasInsufficientEvidenceLabel = credibilityLabel === "insufficient_evidence";

  let title = "当前仍需补证";
  let summary = "现有公开来源还不足以给出稳定结论，建议先看关键证据和时间线边界。";
  let tone: TopLineAssessment["tone"] = "neutral";

  if (hasInsufficientEvidenceLabel && supportedCount > 0) {
    title = "当前只能边界化支持";
    summary = "部分 claim 找到支持线索，但整体来源等级或传播链仍不足，不能把整句话包装成属实。";
    tone = "neutral";
  } else if (conflictingCount > 0 || (supportedCount > 0 && refutedCount > 0)) {
    title = "当前存在冲突信号";
    summary = "公开来源里同时出现了支持和反向线索，暂时不能讲成单向确定结论。";
    tone = "conflicting";
  } else if (refutedCount > 0) {
    title = "当前更倾向不实";
    summary = "已有公开来源对这条说法形成反驳，现阶段更适合按“不实”理解。";
    tone = "refuted";
  } else if (supportedCount > 0) {
    title = "当前更倾向属实";
    summary = "已有公开来源支持这条说法，现阶段更适合按“属实”理解。";
    tone = "supported";
  } else if (report.mode === "partial_mode") {
    title = "已拿到部分可用结论";
    summary = "页面已经找到部分可核查证据，但仍有缺口，不应包装成完整复盘。";
  } else if (report.mode === "complete_mode") {
    title = "核心链路已跑通";
    summary = "当前事件、claim 和证据都已建立，可以继续看细节和来源。";
  }

  if (leadClaim?.notes && !hasInsufficientEvidenceLabel) {
    summary = leadClaim.notes;
  }

  return {
    title,
    summary,
    tone,
    confidenceLabel: leadClaim ? formatConfidence(leadClaim.confidence) : "待补充",
    decisiveClaim: leadClaim?.claim ?? null,
    evidenceCount: leadClaim?.evidence.length ?? evidence.length,
    sourceCount: evidence.length,
  };
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
    } catch {
      return "当前输入类型是 URL，请粘贴一个有效链接。";
    }
  }

  return null;
}

