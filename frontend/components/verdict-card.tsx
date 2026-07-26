"use client";

import type { Report, ReportProvenanceState } from "@/types/report";
import { collectEvidence } from "@/lib/report-utils";
import { getOverallCredibilityMeta } from "@/lib/report-high-score";

function getOverallVerdict(report: Report): string {
  const supported = report.claim_results.filter(c => c.verdict === "supported").length;
  const refuted = report.claim_results.filter(c => c.verdict === "refuted").length;
  const insufficient = report.claim_results.filter(c => c.verdict === "insufficient").length;
  if (refuted > 0 && refuted >= supported) return "refuted";
  if (supported > 0 && supported > refuted) return "supported";
  if (insufficient > 0) return "insufficient";
  return "insufficient";
}

function getVerdictDisplayLabel(verdict: string): string {
  switch (verdict) {
    case "supported": return "基本属实";
    case "refuted": return "不实信息";
    case "insufficient": return "证据不足";
    case "conflicting": return "各方矛盾";
    default: return "待核查";
  }
}

function getVerdictIcon(verdict: string): string {
  switch (verdict) {
    case "supported": return "✓";
    case "refuted": return "✗";
    case "insufficient": return "?";
    case "conflicting": return "!";
    default: return "·";
  }
}

export interface VerdictCardProps {
  report: Report;
  reportProvenance: ReportProvenanceState | null;
}

export function VerdictCard({ report, reportProvenance }: VerdictCardProps) {
  const verdict = getOverallVerdict(report);
  const overallMeta = getOverallCredibilityMeta(report, reportProvenance);
  const evidence = collectEvidence(report);

  return (
    <div className={`verdict-card verdict-card--${verdict}`}>
      <div className={`verdict-card__label verdict-card__label--${verdict}`}>
        <span>{getVerdictIcon(verdict)}</span>
        <span>{getVerdictDisplayLabel(verdict)}</span>
      </div>
      <div className="verdict-card__summary">{report.final_summary}</div>
      {overallMeta?.summary && (
        <div className="verdict-card__detail">{overallMeta.summary}</div>
      )}
      <div className="verdict-card__meta">
        <span className="meta-tag">证据 {evidence.length} 条</span>
        <span className="meta-tag">核查点 {report.claim_results.length} 个</span>
        {report.timeline.length > 0 && <span className="meta-tag">时间线 {report.timeline.length} 节点</span>}
        <span className="meta-tag">
          {report.provenance?.evidence_source === "retrieval_live" ? "实时检索" : "模拟数据"}
        </span>
      </div>
    </div>
  );
}
