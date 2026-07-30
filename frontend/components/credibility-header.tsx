"use client";

import type { Report, ReportProvenanceState } from "@/types/report";
import {
  getCompletionBreakdown,
  getOverallCredibilityMeta,
  getClaimSummaryBuckets,
  getScoreBreakdownMetrics,
} from "@/lib/report-high-score";

export interface CredibilityHeaderProps {
  report: Report;
  reportProvenance: ReportProvenanceState | null;
}

// Compact ratio bar used for both the overall credibility score and the two
// completion stages (content / propagation). We deliberately render nothing
// when the score is null instead of an "unknown" bar — an empty ghost bar
// would compete with the real ones and dilute the signal.
function ScoreBar({ percent, tone }: { percent: number | null; tone: string }) {
  if (percent === null) return null;
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className={`credibility-bar credibility-bar--${tone}`}>
      <div className="credibility-bar__fill" style={{ width: `${clamped}%` }} />
    </div>
  );
}

export function CredibilityHeader({ report, reportProvenance }: CredibilityHeaderProps) {
  const overall = getOverallCredibilityMeta(report, reportProvenance);
  const completion = getCompletionBreakdown(report, reportProvenance);
  const metrics = getScoreBreakdownMetrics(report);
  const buckets = getClaimSummaryBuckets(report);

  // The whole header only appears when the backend actually returned a
  // credibility label — mock/degraded runs shouldn't surface a big empty score
  // widget. Individual sub-sections still hide themselves if their data is
  // missing (metrics/completion sub-scores can be absent in older payloads).
  if (!overall) return null;
  const showBuckets = buckets.some((b) => b.count > 0);
  // VerdictCard already renders report.final_summary as its headline. When the
  // backend has no score_breakdown, overall.summary falls back to that same
  // final_summary — so suppress it here to avoid printing the identical
  // sentence twice in two stacked cards. The detail line (limiting factors /
  // provenance caution) is still distinct and worth keeping.
  const summaryDupesVerdict = overall.summary === report.final_summary;

  return (
    <div className={`credibility-header credibility-header--${overall.tone}`}>
      <div className="credibility-header__top">
        <div className="credibility-header__score">
          <span className="credibility-header__score-value">{overall.scoreLabel}</span>
          <span className="credibility-header__score-label">{overall.label}</span>
        </div>
        <div className="credibility-header__summary">
          {!summaryDupesVerdict && (
            <div className="credibility-header__summary-text">{overall.summary}</div>
          )}
          {overall.detail && overall.detail !== overall.summary && (
            <div className="credibility-header__summary-detail">{overall.detail}</div>
          )}
          {overall.independentSourceCount !== null && (
            <div className="credibility-header__source-count">
              独立来源 {overall.independentSourceCount} 个
            </div>
          )}
        </div>
      </div>

      {completion && (
        <div className="credibility-header__completion">
          {(["content", "propagation"] as const).map((key) => {
            const stage = completion[key];
            return (
              <div key={key} className={`completion-stage completion-stage--${stage.tone}`}>
                <div className="completion-stage__head">
                  <span className="completion-stage__title">{stage.title}</span>
                  <span className="completion-stage__value">{stage.valueLabel}</span>
                </div>
                <ScoreBar percent={stage.percent} tone={stage.tone} />
                <div className="completion-stage__desc">{stage.description}</div>
                <div className="completion-stage__foot">{stage.footnote}</div>
              </div>
            );
          })}
        </div>
      )}

      {metrics.length > 0 && (
        <div className="credibility-header__metrics">
          {metrics.map((m) => (
            <div key={m.key} className="metric-chip">
              <span className="metric-chip__label">{m.label}</span>
              <span className="metric-chip__weight">权重 {m.weightLabel}</span>
              <span className="metric-chip__score">{Math.round(m.score)}</span>
              <span className="metric-chip__desc">{m.description}</span>
            </div>
          ))}
        </div>
      )}

      {showBuckets && (
        <div className="credibility-header__buckets">
          {buckets.map((b) => (
            <div key={b.key} className={`bucket bucket--${b.tone}`} title={b.helper}>
              <span className="bucket__count">{b.count}</span>
              <span className="bucket__label">{b.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
