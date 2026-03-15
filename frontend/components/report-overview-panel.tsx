import {
  getClaimContributionIntro,
  getClaimContributions,
  getClaimSummaryBuckets,
  getCompletionBreakdown,
  getContributionLabelText,
  getContributionTone,
  getOverallCredibilityMeta,
  getScoreBreakdown,
  getScoreBreakdownMetrics,
} from "@/lib/report-high-score";
import { getClaimTypeLabel, getVerdictLabel } from "@/lib/report-utils";
import type { Report, ReportProvenanceState } from "@/types/report";

interface ReportOverviewPanelProps {
  report: Report | null;
  provenance: ReportProvenanceState | null;
}

export function ReportOverviewPanel({ report, provenance }: ReportOverviewPanelProps) {
  if (!report) {
    return (
      <section className="panel panel--overview">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Overview</p>
            <h2>双主流程总览</h2>
          </div>
        </div>
        <p className="empty-state">提交后，这里会先展示整体可信度、双主流程完成度和真假混杂解释。</p>
      </section>
    );
  }

  const overall = getOverallCredibilityMeta(report, provenance);
  const breakdown = getScoreBreakdown(report);
  const metrics = getScoreBreakdownMetrics(report);
  const completion = getCompletionBreakdown(report, provenance);
  const summaryBuckets = getClaimSummaryBuckets(report);
  const contributions = getClaimContributions(report).slice(0, 4);
  const contributionIntro = getClaimContributionIntro(report);

  return (
    <section className="panel panel--overview">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Overview</p>
          <h2>双主流程总览</h2>
        </div>
      </div>

      <div className="report-overview">
        <div className="report-overview__grid">
          <article className={`overview-card overview-card--credibility overview-card--${overall?.tone ?? "insufficient"}`}>
            <div className="meta-row">
              <div>
                <span className="stats-label">整体可信度</span>
                <strong className="overview-card__score">{overall?.scoreLabel ?? "待返回"}</strong>
              </div>
              <span className={`credibility-pill credibility-pill--${overall?.tone ?? "insufficient"}`}>
                {overall?.label ?? "待返回"}
              </span>
            </div>
            <p className="overview-card__summary">{overall?.summary ?? "当前后端还没有返回整体可信度总分。"}</p>
            <p className="panel-copy panel-copy--compact">{overall?.detail}</p>

            <div className="stats-grid">
              <div>
                <span className="stats-label">独立来源</span>
                <strong>{overall?.independentSourceCount ?? "待返回"}</strong>
              </div>
              <div>
                <span className="stats-label">核查 claim</span>
                <strong>{report.claim_results.length}</strong>
              </div>
              <div>
                <span className="stats-label">时间线节点</span>
                <strong>{report.timeline.length}</strong>
              </div>
            </div>
          </article>

          <article className="overview-card">
            <span className="panel-subheading">score_breakdown</span>
            <h3>四维评分拆解</h3>

            {metrics.length ? (
              <div className="metric-list">
                {metrics.map((metric) => (
                  <div key={metric.key} className="metric-row">
                    <div className="metric-row__header">
                      <div>
                        <strong>{metric.label}</strong>
                        <p>{metric.description}</p>
                      </div>
                      <div className="metric-row__score">
                        <strong>{Math.round(metric.score)}</strong>
                        <span>{metric.weightLabel}</span>
                      </div>
                    </div>
                    <div className="metric-bar" aria-hidden="true">
                      <span className="metric-bar__fill" style={{ width: `${metric.score}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-state">当前 report 还没有返回 `score_breakdown`，页面只展示已落盘的 claim 与时间线。</p>
            )}

            {breakdown ? <p className="panel-copy">{breakdown.summary}</p> : null}
            {breakdown?.limiting_factors.length ? (
              <ul className="bullet-list">
                {breakdown.limiting_factors.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
          </article>
        </div>

        <div className="report-overview__grid report-overview__grid--secondary">
          <article className="overview-card">
            <span className="panel-subheading">Double Track</span>
            <h3>传播链和内容核查分开看</h3>

            {completion ? (
              <div className="completion-grid">
                {[completion.content, completion.propagation].map((item) => (
                  <div key={item.title} className={`completion-stage completion-stage--${item.tone}`}>
                    <div className="meta-row">
                      <div>
                        <span className="stats-label">{item.title}</span>
                        <strong>{item.valueLabel}</strong>
                      </div>
                      <span className={`score-pill score-pill--${item.tone}`}>{item.footnote}</span>
                    </div>
                    <p>{item.description}</p>
                    <div className={`metric-bar${item.percent === null ? " metric-bar--empty" : ""}`} aria-hidden="true">
                      {item.percent !== null ? <span className="metric-bar__fill" style={{ width: `${item.percent}%` }} /> : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-state">当前还没有双主流程完成度可展示。</p>
            )}
          </article>

          <article className="overview-card">
            <span className="panel-subheading">Quick Scan</span>
            <h3>事实 / 观点 / 可能有误</h3>
            <div className="claim-summary-strip">
              {summaryBuckets.map((bucket) => (
                <article key={bucket.key} className={`claim-summary-card claim-summary-card--${bucket.tone}`}>
                  <span>{bucket.label}</span>
                  <strong>{bucket.count}</strong>
                  <p>{bucket.helper}</p>
                </article>
              ))}
            </div>
          </article>
        </div>

        <article className="overview-card">
          <span className="panel-subheading">Claim Contribution</span>
          <h3>真假混杂时，哪些 claim 在拉高或拉低总分</h3>
          <p className="panel-copy">{contributionIntro}</p>

          {contributions.length ? (
            <div className="contribution-list">
              {contributions.map((item) => (
                <article
                  key={`${item.claim}-${item.contributionLabel}`}
                  className={`contribution-card contribution-card--${getContributionTone(item.contributionLabel)}`}
                >
                  <div className="meta-row">
                    <span className={`contribution-pill contribution-pill--${item.contributionLabel}`}>
                      {getContributionLabelText(item.contributionLabel)}
                    </span>
                    <span className="cell-subtle">
                      {item.contributionScore === null
                        ? item.derived
                          ? "后端未返回贡献分"
                          : "贡献分待返回"
                        : `${item.contributionScore > 0 ? "+" : ""}${item.contributionScore}`}
                    </span>
                  </div>
                  <strong>{item.claim}</strong>
                  <div className="tag-row">
                    <span className={`tag tag--soft tag--${item.claimType}`}>{getClaimTypeLabel(item.claimType)}</span>
                    <span className={`tag tag--verdict tag--${item.verdict}`}>{getVerdictLabel(item.verdict)}</span>
                  </div>
                  <p>{item.reason}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="empty-state">当前没有可展示的 claim 贡献解释。</p>
          )}
        </article>
      </div>
    </section>
  );
}
