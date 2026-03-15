import { getReportProvenanceMeta, getVerificationScoreMeta } from "@/lib/report-utils";
import type { ClaimType, Report, ReportProvenanceState, Verdict } from "@/types/report";

const credibilityLabels = [
  "high_credibility",
  "medium_credibility",
  "low_credibility",
  "mixed",
  "insufficient_evidence",
] as const;
const contributionLabels = ["supports", "weakens", "mixed", "neutral"] as const;

export type CredibilityLabel = (typeof credibilityLabels)[number];
export type ContributionLabel = (typeof contributionLabels)[number];

interface ScoreWeights {
  claim: number;
  source_quality: number;
  cross_source_agreement: number;
  timeline: number;
}

export interface ScoreBreakdown {
  claim_score: number;
  source_quality_score: number;
  cross_source_agreement_score: number;
  timeline_score: number;
  weights: ScoreWeights;
  summary: string;
  limiting_factors: string[];
}

export interface ScoreBreakdownMetric {
  key: "claim" | "source_quality" | "cross_source_agreement" | "timeline";
  label: string;
  score: number;
  weightLabel: string;
  description: string;
}

export interface OverallCredibilityMeta {
  score: number | null;
  scoreLabel: string;
  labelKey: CredibilityLabel;
  label: string;
  tone: "high" | "medium" | "low" | "mixed" | "insufficient";
  summary: string;
  detail: string;
  independentSourceCount: number | null;
}

export interface CompletionStageMeta {
  title: string;
  valueLabel: string;
  percent: number | null;
  tone: "high" | "medium" | "low";
  description: string;
  footnote: string;
}

export interface CompletionBreakdown {
  content: CompletionStageMeta;
  propagation: CompletionStageMeta;
}

export interface ClaimSummaryBucket {
  key: "facts" | "possible_mistakes" | "opinions" | "pending";
  label: string;
  count: number;
  tone: "high" | "medium" | "neutral" | "low";
  helper: string;
}

export interface DisplayClaimContribution {
  claim: string;
  claimType: ClaimType;
  verdict: Verdict;
  contributionLabel: ContributionLabel;
  contributionScore: number | null;
  reason: string;
  derived: boolean;
}

const credibilityCopy: Record<
  CredibilityLabel,
  { label: string; tone: OverallCredibilityMeta["tone"]; summary: string }
> = {
  high_credibility: {
    label: "高可信",
    tone: "high",
    summary: "关键 claim、来源质量和传播链都较稳，适合当作较完整结果讲解。",
  },
  medium_credibility: {
    label: "中等可信",
    tone: "medium",
    summary: "已经形成部分可信结论，但仍有缺口，不能包装成完整复盘。",
  },
  low_credibility: {
    label: "低可信",
    tone: "low",
    summary: "当前更多是在提示边界与待核查点，不适合给出强判断。",
  },
  mixed: {
    label: "真假混杂",
    tone: "mixed",
    summary: "不同 claim 的方向不一致，需要拆开看，不能把整条新闻一刀切。",
  },
  insufficient_evidence: {
    label: "证据不足",
    tone: "insufficient",
    summary: "当前还没有足够公开证据支撑整体可信度总分。",
  },
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asExtendedReport(report: Report) {
  return report as Report & Record<string, unknown>;
}

function getBoundedScore(value: unknown) {
  return typeof value === "number" && value >= 0 && value <= 100 ? value : null;
}

function getContributionScore(value: unknown) {
  return typeof value === "number" && value >= -100 && value <= 100 ? value : null;
}

function getPositiveInteger(value: unknown) {
  return Number.isInteger(value) && (value as number) >= 0 ? (value as number) : null;
}

function getCredibilityLabel(value: unknown): CredibilityLabel | null {
  return typeof value === "string" && credibilityLabels.includes(value as CredibilityLabel)
    ? (value as CredibilityLabel)
    : null;
}

function getContributionLabel(value: unknown): ContributionLabel | null {
  return typeof value === "string" && contributionLabels.includes(value as ContributionLabel)
    ? (value as ContributionLabel)
    : null;
}

function deriveCredibilityLabel(score: number | null): CredibilityLabel {
  if (score === null) {
    return "insufficient_evidence";
  }

  if (score >= 80) {
    return "high_credibility";
  }

  if (score >= 60) {
    return "medium_credibility";
  }

  if (score >= 35) {
    return "low_credibility";
  }

  return "insufficient_evidence";
}

function getScoreWeights(value: unknown): ScoreWeights | null {
  if (!isObject(value)) {
    return null;
  }

  const claim = typeof value.claim === "number" ? value.claim : null;
  const sourceQuality = typeof value.source_quality === "number" ? value.source_quality : null;
  const crossSourceAgreement =
    typeof value.cross_source_agreement === "number" ? value.cross_source_agreement : null;
  const timeline = typeof value.timeline === "number" ? value.timeline : null;

  if (
    claim === null ||
    sourceQuality === null ||
    crossSourceAgreement === null ||
    timeline === null
  ) {
    return null;
  }

  return {
    claim,
    source_quality: sourceQuality,
    cross_source_agreement: crossSourceAgreement,
    timeline,
  };
}

export function getScoreBreakdown(report: Report | null): ScoreBreakdown | null {
  if (!report) {
    return null;
  }

  const raw = asExtendedReport(report).score_breakdown;
  if (!isObject(raw)) {
    return null;
  }

  const claimScore = getBoundedScore(raw.claim_score);
  const sourceQualityScore = getBoundedScore(raw.source_quality_score);
  const crossSourceAgreementScore = getBoundedScore(raw.cross_source_agreement_score);
  const timelineScore = getBoundedScore(raw.timeline_score);
  const weights = getScoreWeights(raw.weights);
  const summary = typeof raw.summary === "string" ? raw.summary : null;
  const limitingFactors = Array.isArray(raw.limiting_factors)
    ? raw.limiting_factors.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];

  if (
    claimScore === null ||
    sourceQualityScore === null ||
    crossSourceAgreementScore === null ||
    timelineScore === null ||
    !weights ||
    !summary
  ) {
    return null;
  }

  return {
    claim_score: claimScore,
    source_quality_score: sourceQualityScore,
    cross_source_agreement_score: crossSourceAgreementScore,
    timeline_score: timelineScore,
    weights,
    summary,
    limiting_factors: limitingFactors,
  };
}

export function getScoreBreakdownMetrics(report: Report | null): ScoreBreakdownMetric[] {
  const breakdown = getScoreBreakdown(report);
  if (!breakdown) {
    return [];
  }

  return [
    {
      key: "claim",
      label: "Claim 判定",
      score: breakdown.claim_score,
      weightLabel: `${Math.round(breakdown.weights.claim * 100)}%`,
      description: "每条 claim 是否拆清并拿到可解释 verdict。",
    },
    {
      key: "source_quality",
      label: "来源质量",
      score: breakdown.source_quality_score,
      weightLabel: `${Math.round(breakdown.weights.source_quality * 100)}%`,
      description: "是否出现独立且优先级更高的公开来源。",
    },
    {
      key: "cross_source_agreement",
      label: "跨源一致性",
      score: breakdown.cross_source_agreement_score,
      weightLabel: `${Math.round(breakdown.weights.cross_source_agreement * 100)}%`,
      description: "不同来源是否互相支持，还是仍在打架。",
    },
    {
      key: "timeline",
      label: "传播链解释",
      score: breakdown.timeline_score,
      weightLabel: `${Math.round(breakdown.weights.timeline * 100)}%`,
      description: "关键节点、转折和回应是否已串成链路。",
    },
  ];
}

export function getTimelineConfidence(report: Report | null) {
  if (!report) {
    return null;
  }

  return getBoundedScore(asExtendedReport(report).timeline_confidence);
}

export function getIndependentSourceCount(report: Report | null) {
  if (!report) {
    return null;
  }

  return getPositiveInteger(asExtendedReport(report).independent_source_count);
}

export function getOverallCredibilityMeta(
  report: Report | null,
  provenance: ReportProvenanceState | null,
): OverallCredibilityMeta | null {
  if (!report) {
    return null;
  }

  const rawScore = getBoundedScore(asExtendedReport(report).overall_credibility_score);
  const rawLabel = getCredibilityLabel(asExtendedReport(report).overall_credibility_label);
  const labelKey = rawLabel ?? deriveCredibilityLabel(rawScore);
  const labelMeta = credibilityCopy[labelKey];
  const breakdown = getScoreBreakdown(report);
  const provenanceMeta = getReportProvenanceMeta(report, provenance);
  const cautionFirst =
    provenanceMeta && provenanceMeta.sourceKind !== "backend_live" ? provenanceMeta.caution ?? provenanceMeta.summary : null;

  return {
    score: rawScore,
    scoreLabel: rawScore === null ? "待返回" : `${Math.round(rawScore)}/100`,
    labelKey,
    label: labelMeta.label,
    tone: labelMeta.tone,
    summary:
      rawScore === null && !rawLabel
        ? "当前 report 还没有返回整体可信度总分，请先按 claim、传播链和风险边界理解结果。"
        : breakdown?.summary ?? report.final_summary,
    detail:
      cautionFirst ??
      breakdown?.limiting_factors[0] ??
      provenanceMeta?.caution ??
      provenanceMeta?.summary ??
      labelMeta.summary,
    independentSourceCount: getIndependentSourceCount(report),
  };
}

function getPropagationTone(percent: number | null, nodeCount: number) {
  if (percent === null) {
    return nodeCount >= 3 ? "medium" : "low";
  }

  if (percent >= 75) {
    return "high";
  }

  if (percent >= 45) {
    return "medium";
  }

  return "low";
}

function getPropagationDescription(percent: number | null, report: Report, sourceCount: number | null) {
  if (percent === null) {
    if (report.timeline.length > 0) {
      return `已拿到 ${report.timeline.length} 个关键节点，但后端尚未返回传播链完成度分。`;
    }

    return "当前还没有形成可解释的传播链闭环。";
  }

  if (percent >= 75) {
    return "关键起点、放大节点和回应节点基本齐全，适合讲传播主链。";
  }

  if (percent >= 45) {
    return "已经形成主链路，但峰值节点或关键回应仍有缺口。";
  }

  return sourceCount && sourceCount > 1
    ? "目前只有零散传播线索，还不足以讲成完整传播图。"
    : "当前传播链仍偏弱，只适合提示线索，不适合讲成闭环。";
}

export function getCompletionBreakdown(
  report: Report | null,
  provenance: ReportProvenanceState | null,
): CompletionBreakdown | null {
  if (!report) {
    return null;
  }

  const contentScore = getVerificationScoreMeta(report, provenance);
  const propagationPercent = getTimelineConfidence(report);
  const sourceCount = getIndependentSourceCount(report);

  return {
    content: {
      title: "内容核查完成度",
      valueLabel: contentScore.label,
      percent: contentScore.score * 10,
      tone: contentScore.tone,
      description: contentScore.summary,
      footnote: contentScore.modeLabel,
    },
    propagation: {
      title: "传播链完成度",
      valueLabel: propagationPercent === null ? "待返回" : `${Math.round(propagationPercent)}/100`,
      percent: propagationPercent,
      tone: getPropagationTone(propagationPercent, report.timeline.length),
      description: getPropagationDescription(propagationPercent, report, sourceCount),
      footnote:
        sourceCount === null
          ? `关键节点 ${report.timeline.length} 个`
          : `独立来源 ${sourceCount} 个 / 关键节点 ${report.timeline.length} 个`,
    },
  };
}

export function getClaimSummaryBuckets(report: Report | null): ClaimSummaryBucket[] {
  if (!report) {
    return [];
  }

  const contentCheck = report.content_check;
  const facts = contentCheck
    ? contentCheck.likely_true.length
    : report.claim_results.filter((item) => item.claim_type === "fact" && item.verdict === "supported").length;
  const possibleMistakes = contentCheck
    ? contentCheck.likely_false.length + contentCheck.controversial.length
    : report.claim_results.filter((item) => item.verdict === "refuted" || item.verdict === "conflicting").length;
  const opinions = contentCheck
    ? contentCheck.opinions.length
    : report.claim_results.filter((item) => item.claim_type === "opinion").length;
  const pending = contentCheck
    ? contentCheck.uncertain.length
    : report.claim_results.filter((item) => item.claim_type !== "opinion" && item.verdict === "insufficient").length;

  return [
    {
      key: "facts",
      label: "事实",
      count: facts,
      tone: "high",
      helper: facts > 0 ? `${facts} 条说法已拿到稳定支持。` : "当前还没有稳定成立的事实项。",
    },
    {
      key: "possible_mistakes",
      label: "可能有误",
      count: possibleMistakes,
      tone: possibleMistakes > 0 ? "medium" : "neutral",
      helper: possibleMistakes > 0 ? "这部分需要重点解释冲突或反驳证据。" : "当前没有明显被反驳的部分。",
    },
    {
      key: "opinions",
      label: "观点",
      count: opinions,
      tone: "neutral",
      helper: opinions > 0 ? "观点会单独展示，不直接算作事实成立。" : "当前没有明显评价性表达。",
    },
    {
      key: "pending",
      label: "待补证",
      count: pending,
      tone: pending > 0 ? "low" : "neutral",
      helper: pending > 0 ? "这部分还需要更多公开来源补证。" : "当前没有额外待补证项。",
    },
  ];
}

function getFallbackContributionLabel(claimType: ClaimType, verdict: Verdict): ContributionLabel {
  if (claimType === "opinion" || verdict === "insufficient") {
    return "neutral";
  }

  if (verdict === "supported") {
    return "supports";
  }

  if (verdict === "refuted") {
    return "weakens";
  }

  return "mixed";
}

function parseContribution(value: unknown): DisplayClaimContribution | null {
  if (!isObject(value)) {
    return null;
  }

  const claim = typeof value.claim === "string" ? value.claim : null;
  const claimType =
    value.claim_type === "fact" ||
    value.claim_type === "opinion" ||
    value.claim_type === "prediction" ||
    value.claim_type === "unverifiable"
      ? value.claim_type
      : null;
  const verdict =
    value.verdict === "supported" ||
    value.verdict === "refuted" ||
    value.verdict === "insufficient" ||
    value.verdict === "conflicting"
      ? value.verdict
      : null;
  const contributionLabel = getContributionLabel(value.contribution_label);
  const reason = typeof value.reason === "string" ? value.reason : null;

  if (!claim || !claimType || !verdict || !contributionLabel || !reason) {
    return null;
  }

  return {
    claim,
    claimType,
    verdict,
    contributionLabel,
    contributionScore: getContributionScore(value.contribution_score),
    reason,
    derived: false,
  };
}

export function getClaimContributions(report: Report | null): DisplayClaimContribution[] {
  if (!report) {
    return [];
  }

  const raw = asExtendedReport(report).claim_contributions;
  if (Array.isArray(raw)) {
    const parsed = raw.map(parseContribution).filter((item): item is DisplayClaimContribution => item !== null);
    if (parsed.length > 0) {
      return parsed;
    }
  }

  return report.claim_results.map((item) => ({
    claim: item.claim,
    claimType: item.claim_type,
    verdict: item.verdict,
    contributionLabel: getFallbackContributionLabel(item.claim_type, item.verdict),
    contributionScore: null,
    reason: item.notes,
    derived: true,
  }));
}

export function getContributionLabelText(label: ContributionLabel) {
  switch (label) {
    case "supports":
      return "拉高总分";
    case "weakens":
      return "拉低总分";
    case "mixed":
      return "真假混杂";
    default:
      return "仅作边界";
  }
}

export function getContributionTone(label: ContributionLabel) {
  switch (label) {
    case "supports":
      return "high";
    case "weakens":
      return "low";
    case "mixed":
      return "mixed";
    default:
      return "neutral";
  }
}

export function getClaimContributionIntro(report: Report | null) {
  const contributions = getClaimContributions(report);
  if (!contributions.length) {
    return "当前还没有 claim 贡献解释。";
  }

  const hasPositive = contributions.some((item) => item.contributionLabel === "supports");
  const hasNegative = contributions.some(
    (item) => item.contributionLabel === "weakens" || item.contributionLabel === "mixed",
  );
  const hasMixed = contributions.some((item) => item.contributionLabel === "mixed");

  if (hasMixed || (hasPositive && hasNegative)) {
    return "这条新闻不是整条真或整条假，而是不同 claim 在同时抬高和拉低整体可信度。";
  }

  if (hasNegative) {
    return "当前主要是反驳或冲突 claim 在拉低整体可信度。";
  }

  if (hasPositive) {
    return "当前主要是被证据支持的 claim 在抬高整体可信度。";
  }

  return "当前多数 claim 仍是观点或待补证项，对整体可信度只提供边界提示。";
}
