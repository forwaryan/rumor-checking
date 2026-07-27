"use client";

import type { Report, ReportProvenanceState } from "@/types/report";
import { collectEvidence } from "@/lib/report-utils";
import { getOverallCredibilityMeta } from "@/lib/report-high-score";

// A supported claim whose predicate DENIES the rumor ("…辟谣/否认/不实") is
// evidence the rumor is FALSE. It must not be counted as a confirming
// ("supported") claim, or a lone "官方已辟谣" reads as 基本属实. Mirror of the
// backend DEBUNK_MARKERS / _claim_is_debunking in report_builder.py.
const DEBUNK_MARKERS = ["辟谣", "否认", "不实", "不属实", "系谣言", "实为谣言", "造谣", "假消息", "假新闻", "谣言不实"];

function isDebunkingClaim(claim: string): boolean {
  return DEBUNK_MARKERS.some(marker => (claim || "").includes(marker));
}

function getOverallVerdict(report: Report): string {
  const supported = report.claim_results.filter(
    c => c.verdict === "supported" && !isDebunkingClaim(c.claim)
  ).length;
  // A supported debunking claim counts against the rumor, alongside refutations.
  const debunk = report.claim_results.filter(
    c => c.verdict === "supported" && isDebunkingClaim(c.claim)
  ).length;
  const refuted = report.claim_results.filter(c => c.verdict === "refuted").length + debunk;
  const conflicting = report.claim_results.filter(c => c.verdict === "conflicting").length;
  const insufficient = report.claim_results.filter(c => c.verdict === "insufficient").length;
  if (conflicting > 0) return "conflicting";
  // When a message has both supported and refuted claims, the dominant verdict
  // wins: if more/equal refuted, the message is overall exaggerated/false;
  // only when supported outnumbers refuted is it "mixed truth".
  if (supported > 0 && refuted > 0) {
    return refuted >= supported ? "exaggerated" : "conflicting";
  }
  if (refuted > 0) return "refuted";
  if (supported > 0) return "supported";
  if (insufficient > 0) return "insufficient";
  return "insufficient";
}

function getVerdictDisplayLabel(verdict: string): string {
  switch (verdict) {
    case "supported": return "基本属实";
    case "refuted": return "不实信息";
    case "exaggerated": return "夸大失实";
    case "insufficient": return "证据不足";
    case "conflicting": return "各方矛盾";
    default: return "待核查";
  }
}

function getVerdictIcon(verdict: string): string {
  switch (verdict) {
    case "supported": return "✓";
    case "refuted": return "✗";
    case "exaggerated": return "↑";
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
