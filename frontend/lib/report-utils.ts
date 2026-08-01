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
  SourceTier,
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

const sourceTierWeight = {
  S: 4,
  A: 3,
  B: 2,
  C: 1,
} as const;

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

export function formatProbability(value?: number | null): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return `${Math.round(value)}%`;
}

export function getBasisLabel(basis?: string | null): string | null {
  if (basis === "evidence") return "有证据";
  if (basis === "prior") return "无直接证据";
  return null;
}

export interface SourceTierMeta {
  tier: SourceTier;
  label: string;
  tone: "high" | "medium" | "low";
  hint: string;
  // Short single-word/phrase adjective displayed next to the letter pill so a
  // reader immediately gets "S = 权威一手" without needing to hover.
  shortLabel: string;
}

const sourceTierMeta: Record<SourceTier, SourceTierMeta> = {
  S: {
    tier: "S",
    label: "权威一手",
    shortLabel: "权威一手",
    tone: "high",
    hint: "官方通报、当事主体或一手权威来源，可信度最高。",
  },
  A: {
    tier: "A",
    label: "权威/主流",
    shortLabel: "权威主流",
    tone: "high",
    hint: "官方或权威媒体来源，适合作为主要判定依据。",
  },
  B: {
    tier: "B",
    label: "一般媒体",
    shortLabel: "一般媒体",
    tone: "medium",
    hint: "普通媒体或次级来源，需与更高等级来源相互印证。",
  },
  C: {
    tier: "C",
    label: "自媒体/社交",
    shortLabel: "自媒体",
    tone: "low",
    hint: "自媒体、社交或聚合转载来源，仅供参考，不宜单独采信。",
  },
};

// Turn the bare tier letter (S/A/B/C) into a human-readable label + tone so a
// low-trust self-media post is not visually indistinguishable from an
// authoritative source. Unknown tiers fall back to the most conservative (C).
export function getSourceTierMeta(tier: SourceTier | string | null | undefined): SourceTierMeta {
  if (tier && tier in sourceTierMeta) {
    return sourceTierMeta[tier as SourceTier];
  }
  return sourceTierMeta.C;
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

