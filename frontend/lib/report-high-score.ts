import { getReportProvenanceMeta, getVerificationScoreMeta } from "@/lib/report-utils";
import type {
  CredibilityLabel,
  Report,
  ReportProvenanceState,
  ScoreBreakdown,
} from "@/types/report";

const credibilityLabels: readonly CredibilityLabel[] = [
  "high_credibility",
  "medium_credibility",
  "low_credibility",
  "mixed",
  "insufficient_evidence",
];

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

function isBoundedScore(value: number | null | undefined): value is number {
  return typeof value === "number" && value >= 0 && value <= 100;
}

function isCredibilityLabel(value: unknown): value is CredibilityLabel {
  return typeof value === "string" && credibilityLabels.includes(value as CredibilityLabel);
}

function deriveCredibilityLabel(score: number | null): CredibilityLabel {
  if (score === null) return "insufficient_evidence";
  if (score >= 80) return "high_credibility";
  if (score >= 60) return "medium_credibility";
  if (score >= 35) return "low_credibility";
  return "insufficient_evidence";
}

function readBoundedScore(value: number | null | undefined): number | null {
  return isBoundedScore(value) ? value : null;
}

export function getScoreBreakdown(report: Report | null): ScoreBreakdown | null {
  if (!report?.score_breakdown) return null;
  const raw = report.score_breakdown;
  const claim = readBoundedScore(raw.claim_score);
  const source = readBoundedScore(raw.source_quality_score);
  const cross = readBoundedScore(raw.cross_source_agreement_score);
  const timeline = readBoundedScore(raw.timeline_score);
  if (claim === null || source === null || cross === null || timeline === null) return null;
  return raw;
}

export function getScoreBreakdownMetrics(report: Report | null): ScoreBreakdownMetric[] {
  const breakdown = getScoreBreakdown(report);
  if (!breakdown) return [];
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

export function getTimelineConfidence(report: Report | null): number | null {
  return report ? readBoundedScore(report.timeline_confidence) : null;
}

function getIndependentSourceCount(report: Report | null): number | null {
  if (!report) return null;
  const value = report.independent_source_count;
  return Number.isInteger(value) && (value as number) >= 0 ? (value as number) : null;
}

export function getOverallCredibilityMeta(
  report: Report | null,
  provenance: ReportProvenanceState | null,
): OverallCredibilityMeta | null {
  if (!report) return null;

  const rawScore = readBoundedScore(report.overall_credibility_score);
  const rawLabel = isCredibilityLabel(report.overall_credibility_label)
    ? (report.overall_credibility_label as CredibilityLabel)
    : null;
  const labelKey = rawLabel ?? deriveCredibilityLabel(rawScore);
  const labelMeta = credibilityCopy[labelKey];
  const breakdown = getScoreBreakdown(report);
  const provenanceMeta = getReportProvenanceMeta(report, provenance);
  const cautionFirst =
    provenanceMeta && provenanceMeta.sourceKind !== "backend_live"
      ? provenanceMeta.caution ?? provenanceMeta.summary
      : null;

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

function getPropagationTone(percent: number | null, nodeCount: number): CompletionStageMeta["tone"] {
  if (percent === null) return nodeCount >= 3 ? "medium" : "low";
  if (percent >= 75) return "high";
  if (percent >= 45) return "medium";
  return "low";
}

function getPropagationDescription(percent: number | null, report: Report, sourceCount: number | null): string {
  if (percent === null) {
    if (report.timeline.length > 0) {
      return `已拿到 ${report.timeline.length} 个关键节点，但后端尚未返回传播链完成度分。`;
    }
    return "当前还没有形成可解释的传播链闭环。";
  }
  if (percent >= 75) return "关键起点、放大节点和回应节点基本齐全，适合讲传播主链。";
  if (percent >= 45) return "已经形成主链路，但峰值节点或关键回应仍有缺口。";
  return sourceCount && sourceCount > 1
    ? "目前只有零散传播线索，还不足以讲成完整传播图。"
    : "当前传播链仍偏弱，只适合提示线索，不适合讲成闭环。";
}

export function getCompletionBreakdown(
  report: Report | null,
  provenance: ReportProvenanceState | null,
): CompletionBreakdown | null {
  if (!report) return null;
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
  if (!report) return [];
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

