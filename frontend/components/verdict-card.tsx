"use client";

import React from "react";
import type { Report, ReportProvenanceState } from "@/types/report";
import { getReportProvenanceMeta } from "@/lib/report-utils";
import { getOverallCredibilityMeta } from "@/lib/report-high-score";

// A supported claim whose predicate DENIES the rumor ("…辟谣/否认/不实") is
// evidence the rumor is FALSE. It must not be counted as a confirming
// ("supported") claim, or a lone "官方已辟谣" reads as 基本属实. Mirror of the
// backend DEBUNK_MARKERS / _claim_is_debunking in report_builder.py.
const DEBUNK_MARKERS = ["辟谣", "否认", "不实", "不属实", "系谣言", "实为谣言", "造谣", "假消息", "假新闻", "谣言不实"];

function isDebunkingClaim(claim: string): boolean {
  return DEBUNK_MARKERS.some(marker => (claim || "").includes(marker));
}

export function getOverallVerdict(report: Report): string {
  if (report.overall_credibility_label === "insufficient_evidence") {
    return "insufficient";
  }
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
  const citedEvidenceCount = new Set(report.claim_results.flatMap(claim => claim.evidence.map(item => item.url))).size;
  const provenance = getReportProvenanceMeta(report, reportProvenance);
  const sourceLabel = provenance?.sourceKind === "backend_live"
    ? (!report.provenance ? "分析已运行 · 证据来源待确认"
      : report.provenance.evidence_source === "retrieval_live"
        ? citedEvidenceCount > 0 ? "联网检索 · 有采信证据" : "联网检索 · 暂无采信证据"
        : report.provenance.evidence_source === "retrieval_mock" || report.provenance.evidence_source === "request_mock"
          ? "分析已运行 · 模拟或注入证据"
          : "分析已运行 · 证据链未建立")
    : provenance?.sourceLabel ?? "来源待确认";

  return (
    <div className={`verdict-card verdict-card--${verdict}`}>
      <div className={`verdict-card__label verdict-card__label--${verdict}`}>
        <span>{getVerdictIcon(verdict)}</span>
        <span>{getVerdictDisplayLabel(verdict)}</span>
      </div>
      <div className="verdict-card__summary">{report.final_summary}</div>
      {overallMeta?.summary && overallMeta.summary !== report.final_summary && (
        <div className="verdict-card__detail">{overallMeta.summary}</div>
      )}
      {report.risks.length > 0 && <p className="verdict-card__risk"><strong>核查边界</strong> {report.risks[0]}</p>}
      {citedEvidenceCount === 0 && <p className="verdict-card__risk"><strong>证据边界</strong> 当前没有被核查点引用的证据，检索命中不能视为已采信证据；请结合原始来源进一步核实。</p>}
      <div className="verdict-card__meta">
        <span className="meta-tag">证据 {citedEvidenceCount} 条</span>
        <span className="meta-tag">核查点 {report.claim_results.length} 个</span>
        {report.timeline.length > 0 && <span className="meta-tag">时间线 {report.timeline.length} 节点</span>}
        <span className="meta-tag">{sourceLabel}</span>
        {provenance?.fallbackLabel && <span className="meta-tag">{provenance.fallbackLabel}</span>}
      </div>
    </div>
  );
}
